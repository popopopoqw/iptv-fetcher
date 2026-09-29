"""并发 ffprobe 验证：可播放性、分辨率、延迟（首分片TTFB）。"""
import asyncio
import json
import logging
import time
from urllib.parse import urljoin

import aiohttp

from .models import ProbeResult

log = logging.getLogger("prober")

FFPROBE_TIMEOUT_US = "10000000"  # 内部协议超时 10s


def _probe_env(proxy: str) -> dict:
    import os
    env = dict(os.environ)
    if proxy:
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy
    return env


async def _ffprobe(url: str, timeout_s: int, proxy: str) -> dict:
    cmd = [
        "ffprobe", "-v", "quiet",
        "-timeout", FFPROBE_TIMEOUT_US, "-rw_timeout", FFPROBE_TIMEOUT_US,
        "-i", url, "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height",
        "-show_entries", "format=format_name",
        "-of", "json",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        env=_probe_env(proxy))
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return json.loads(out.decode("utf-8", "ignore") or "{}")


async def _ttfb(session: aiohttp.ClientSession, url: str) -> int:
    """GET 响应头耗时（毫秒），失败返回 -1。"""
    start = time.monotonic()
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10),
                               allow_redirects=True) as resp:
            resp.release()
            return int((time.monotonic() - start) * 1000)
    except Exception:  # noqa: BLE001 延迟测量失败不影响可播放判定
        return -1


def _first_segment(playlist: str, base: str) -> str:
    for line in playlist.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line if "://" in line else urljoin(base, line)
    return ""


async def _measure_latency(session: aiohttp.ClientSession, url: str) -> int:
    """延迟 = 播放列表TTFB + 首分片TTFB。"""
    start = time.monotonic()
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10),
                               allow_redirects=True) as resp:
            if resp.status != 200:
                return -1
            body = await resp.text(errors="ignore")
        first = int((time.monotonic() - start) * 1000)
    except Exception:  # noqa: BLE001
        return -1
    seg = _first_segment(body, url)
    if not seg or not seg.startswith("http"):
        return first
    seg_ms = await _ttfb(session, seg)
    return first + seg_ms if seg_ms >= 0 else first


async def probe_one(session: aiohttp.ClientSession, url: str,
                    timeout_s: int, proxy: str) -> ProbeResult:
    result = ProbeResult(url=url)
    start = time.monotonic()
    try:
        data = await _ffprobe(url, timeout_s, proxy)
    except asyncio.TimeoutError:
        result.error = "ffprobe超时"
        result.elapsed_ms = int((time.monotonic() - start) * 1000)
        return result
    except Exception as e:  # noqa: BLE001
        result.error = f"{type(e).__name__}"
        result.elapsed_ms = int((time.monotonic() - start) * 1000)
        return result
    result.elapsed_ms = int((time.monotonic() - start) * 1000)

    streams = data.get("streams") or []
    if streams and streams[0].get("codec_name"):
        s = streams[0]
        result.playable = True
        result.codec = s.get("codec_name", "")
        result.width = int(s.get("width") or 0)
        result.height = int(s.get("height") or 0)
    else:
        result.error = "无视频流"
        return result

    if url.startswith("http"):
        result.latency_ms = await _measure_latency(session, url)
        if result.latency_ms < 0:
            result.latency_ms = result.elapsed_ms
    else:
        result.latency_ms = result.elapsed_ms
    return result


async def probe_all(candidates, cfg, limit: int = 0):
    """并发验证候选列表，原地写入 c.result。limit>0 时均匀抽样 limit 个验证。"""
    if limit and len(candidates) > limit:
        stride = max(1, len(candidates) // limit)
        candidates = candidates[::stride][:limit]
    conn = aiohttp.TCPConnector(limit=cfg.probe_concurrency * 2, ssl=False)
    sem = asyncio.Semaphore(cfg.probe_concurrency)
    done = [0]

    async def work(session, c):
        async with sem:
            c.result = await probe_one(session, c.entry.url,
                                       cfg.probe_timeout, cfg.proxy)
        done[0] += 1
        if done[0] % 50 == 0:
            log.info("验证进度 %d/%d", done[0], len(candidates))

    async with aiohttp.ClientSession(connector=conn, trust_env=bool(cfg.proxy)) as session:
        await asyncio.gather(*[work(session, c) for c in candidates])
    playable = sum(1 for c in candidates if c.result and c.result.playable)
    log.info("验证完成：%d/%d 可播放", playable, len(candidates))
    return candidates
