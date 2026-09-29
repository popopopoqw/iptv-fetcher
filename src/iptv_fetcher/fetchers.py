"""上游播放列表抓取与解析（m3u / txt 两种格式）。"""
import asyncio
import logging
import re
from typing import List, Optional

import aiohttp

from .models import Entry

log = logging.getLogger("fetcher")

EXTINF_RE = re.compile(r"^#EXTINF:\s*[^,]*,(.*)$")
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
URL_RE = re.compile(r"^[a-zA-Z][\w+.-]*://\S+$")


def _split_title(line: str) -> str:
    """取 #EXTINF 行最后一个属性引号之后的逗号后面的标题。"""
    m = EXTINF_RE.match(line)
    return m.group(1).strip() if m else ""


def parse_m3u(text: str, source: str, region_hint: str) -> List[Entry]:
    entries: List[Entry] = []
    title, attrs = "", {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            title = _split_title(line)
            attrs = {k.lower(): v for k, v in ATTR_RE.findall(line)}
        elif line.startswith("#"):
            continue  # EXTVLCOPT 等指令行忽略
        elif URL_RE.match(line):
            if title:
                entries.append(Entry(
                    name=title, url=line, source=source, region_hint=region_hint,
                    tvg_id=attrs.get("tvg-id", ""),
                    tvg_country=attrs.get("tvg-country", ""),
                    group=attrs.get("group-title", ""),
                ))
            title, attrs = "", {}
    return entries


def parse_txt(text: str, source: str, region_hint: str) -> List[Entry]:
    """「名称,地址」格式（kimwang 等），组行形如 `xx,#genre#`。"""
    entries: List[Entry] = []
    group = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "," not in line:
            continue
        name, _, url = line.partition(",")
        name, url = name.strip(), url.strip()
        if url == "#genre#":
            group = name
            continue
        if URL_RE.match(url):
            entries.append(Entry(name=name, url=url, source=source,
                                 region_hint=region_hint, group=group))
    return entries


async def _fetch_text(session: aiohttp.ClientSession, url: str,
                      timeout: int, mirror_prefixes: List[str]) -> Optional[str]:
    candidates = [url]
    if "raw.githubusercontent.com" in url:
        candidates += [m + url for m in mirror_prefixes]
    last_err = ""
    for u in candidates:
        try:
            async with session.get(u, timeout=aiohttp.ClientTimeout(total=timeout),
                                   allow_redirects=True) as resp:
                if resp.status == 200:
                    return await resp.text(errors="ignore")
                last_err = f"HTTP {resp.status}"
        except Exception as e:  # noqa: BLE001 抓取失败换下一个镜像即可
            last_err = f"{type(e).__name__}: {e}"
        log.info("源抓取失败 %s → %s", u, last_err)
    log.error("源最终不可用 %s (%s)", url, last_err)
    return None


async def fetch_source(session: aiohttp.ClientSession, src: dict,
                       mirror_prefixes: List[str], timeout: int = 40) -> List[Entry]:
    text = await _fetch_text(session, src["url"], timeout, mirror_prefixes)
    if text is None:
        return []
    kind = src.get("type", "m3u")
    if kind == "txt":
        entries = parse_txt(text, src["name"], src.get("region_hint", "cn"))
    else:
        entries = parse_m3u(text, src["name"], src.get("region_hint", "cn"))
    log.info("源 %s: %d 条", src["name"], len(entries))
    return entries


async def fetch_all(cfg) -> List[Entry]:
    """并发抓取全部上游源并按 URL 去重。"""
    conn = aiohttp.TCPConnector(limit=8, ssl=False)
    proxy = cfg.proxy or None
    async with aiohttp.ClientSession(connector=conn, trust_env=bool(cfg.proxy)) as session:
        results = await asyncio.gather(*[
            fetch_source(session, s, cfg.mirror_prefixes) for s in cfg.sources
        ])
    seen, entries = set(), []
    for batch in results:
        for e in batch:
            if e.url not in seen:
                seen.add(e.url)
                entries.append(e)
    log.info("聚合后共 %d 条（URL去重）", len(entries))
    return entries
