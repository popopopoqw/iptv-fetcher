"""频道名归一化与地区分类。"""
import re
from typing import Optional

from .models import Entry

# 需要剔除的画质/备注标注（出现在 [] () 【】 （） 内时整段删除）
TAG_RE = re.compile(
    r"[\[（\[【(]([^)\]】）]*)[\)）\]】]",
)
TAG_KEYWORD_RE = re.compile(
    r"\d{3,4}[pPi]|4k|8k|uhd|fhd|hd|超清|高清|标清|蓝光|原画|轮播|测试|备用|直播|"
    r"not\s*24|24/7|iptv|线|源|电信|联通|移动|ipv6|ipv4", re.I,
)
NOISE_SUFFIX_RE = re.compile(r"(高清|标清|超清|超高清|蓝光|频道|测试)$")
CCTV_RE = re.compile(
    r"^cctv[\s\-—·]?(\d{1,2})\s*([+＋]|plus)?"
    r"(综合|财经|综艺|体育|电影|国防军事|农业农村|戏曲|少儿|音乐|法语|英语|西班牙语|俄语|阿拉伯语)?",
    re.I,
)
CGTN_RE = re.compile(r"^cgtn[\s\-—·]?", re.I)

# 港澳台频道关键词
HMT_KEYWORDS = (
    "凤凰", "tvb", "翡翠", "明珠", "本港", "国际台", "香港开电视", "hoytv",
    "澳视", "澳门", "莲花", "tvbs", "东森", "中天", "民视", "三立", "台视",
    "中视", "华视", "公视", "八大", "年代", "纬来", "龙华", "靖天", "大爱",
    "原住民", "momo", "极速", "台湾", "香港", "澳門", "臺灣",
)

REGION_ORDER = ["cn-cctv", "cn-satellite", "cn-local", "cn-hmt", "foreign"]
REGION_LABEL = {
    "cn-cctv": "央视",
    "cn-satellite": "卫视",
    "cn-local": "地方台",
    "cn-hmt": "港澳台",
}


def normalize_name(name: str) -> str:
    """归一化为频道聚合键；display 清理标注但保留可读性。"""
    s = name.strip()
    # 删除括号内的画质/备注标注
    def drop(m: re.Match) -> str:
        return "" if TAG_KEYWORD_RE.search(m.group(1)) else m.group(0)
    s = TAG_RE.sub(drop, s)
    display = re.sub(r"\s{2,}", " ", s).strip()

    key = s.lower().strip()
    key = key.replace("＋", "+").replace("－", "-")
    key = re.sub(r"[\s\-—·_:：]", "", key)
    key = CGTN_RE.sub("cgtn", key)
    m = CCTV_RE.match(key)
    if m:
        num, plus = m.group(1), bool(m.group(2))
        key = f"cctv{num}{'+' if plus else ''}"
    else:
        key = NOISE_SUFFIX_RE.sub("", key)
        key = key.replace("+", "p") if key.startswith("cctv") else key
    return key


def _is_hmt(name_lc: str) -> bool:
    return any(k in name_lc for k in HMT_KEYWORDS)


def classify(entry: Entry) -> "tuple[str, str]":
    """返回 (region, country)。country 仅 foreign 有意义。"""
    name = entry.name.lower()
    if entry.tvg_country and entry.tvg_country.lower() not in ("cn", "zh", "china", ""):
        return "foreign", entry.tvg_country.strip().title() or "其他"
    if _is_hmt(name):
        return "cn-hmt", ""
    if CCTV_RE.match(name.replace(" ", "")) or name.startswith("cgtn") or "中央" in name or "央视" in name:
        return "cn-cctv", ""
    if name.endswith("卫视") or "卫视" in name:
        return "cn-satellite", ""
    if entry.region_hint == "cn":
        return "cn-local", ""
    if entry.tvg_country:
        return "foreign", entry.tvg_country.strip().title() or "其他"
    return "foreign", "其他"


def build_candidates(entries, candidates_per_channel: int = 0):
    """按归一化名聚合；candidates_per_channel>0 时限制每频道候选数（0=不限制），
    排序保持来源分散化。"""
    from .models import Candidate

    buckets: "dict[str, list[Candidate]]" = {}
    for e in entries:
        key = normalize_name(e.name)
        if not key:
            continue
        region, country = classify(e)
        buckets.setdefault(key, []).append(
            Candidate(key=key, display=e.name.strip(), entry=e,
                      region=region, country=country))

    candidates = []
    for key, items in buckets.items():
        # 来源分散化：轮询各来源取候选
        picked, pools = [], [list(items)]
        by_source: "dict[str, list[Candidate]]" = {}
        for c in items:
            by_source.setdefault(c.entry.source, []).append(c)
        pools = list(by_source.values())
        pool_idx = 0
        limit = candidates_per_channel if candidates_per_channel > 0 else float("inf")
        while len(picked) < limit and any(pools):
            pool = pools[pool_idx % len(pools)]
            if pool:
                picked.append(pool.pop(0))
            pool_idx += 1
        # 显示名取最常见样式：保留最短的非空原始名
        display = min((c.display for c in items), key=len)
        for c in picked:
            c.display = display
        candidates.extend(picked)
    return candidates
