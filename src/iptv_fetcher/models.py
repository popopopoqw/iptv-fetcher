"""公共数据模型与配置加载。"""
import os
from dataclasses import dataclass, field
from typing import List, Optional

import yaml
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class Entry:
    """上游列表解析出的一条频道条目。"""
    name: str          # 原始显示名
    url: str
    source: str
    region_hint: str = "cn"   # cn / foreign：该源的无归属频道默认地区
    tvg_id: str = ""
    tvg_country: str = ""
    group: str = ""


@dataclass
class ProbeResult:
    url: str
    playable: bool = False
    width: int = 0
    height: int = 0
    codec: str = ""
    latency_ms: int = -1      # 首分片TTFB，-1=未知（如rtmp/udp用probe耗时兜底）
    elapsed_ms: int = 0       # ffprobe 总耗时
    error: str = ""

    @property
    def pixels(self) -> int:
        return self.width * self.height


@dataclass
class Candidate:
    """归一化后的待验证候选。"""
    key: str            # 归一化频道名
    display: str        # 清理后的显示名
    entry: Entry
    region: str = ""    # cn-cctv / cn-satellite / cn-local / cn-hmt / foreign
    country: str = ""   # 国外频道的国家
    result: Optional[ProbeResult] = None


@dataclass
class Config:
    min_resolution: int = 1080
    candidates_per_channel: int = 0
    backups_per_channel: int = 2
    probe_concurrency: int = 16
    probe_timeout: int = 25
    funnel: dict = field(default_factory=dict)
    proxy: str = ""
    epg_url: str = ""
    mirror_prefixes: List[str] = field(default_factory=list)
    sources: List[dict] = field(default_factory=list)
    publish: dict = field(default_factory=dict)
    path: str = ""


def load_config(path: str) -> Config:
    load_dotenv(os.path.join(ROOT, ".env"))
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cfg = Config(
        min_resolution=int(raw.get("min_resolution", 1080)),
        candidates_per_channel=int(raw.get("candidates_per_channel", 0) or 0),
        backups_per_channel=int(raw.get("backups_per_channel", 2)),
        probe_concurrency=int(raw.get("probe_concurrency", 16)),
        probe_timeout=int(raw.get("probe_timeout", 25)),
        proxy=raw.get("proxy", "") or "",
        epg_url=raw.get("epg_url", "") or "",
        mirror_prefixes=list(raw.get("mirror_prefixes", []) or []),
        sources=list(raw.get("sources", []) or []),
        publish=dict(raw.get("publish", {}) or {}),
        funnel=dict(raw.get("funnel", {}) or {}),
        path=path,
    )
    return cfg
