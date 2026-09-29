"""渲染输出：M3U（中国在前、国外按国家）、验证明细 CSV、统计 JSON。"""
import csv
import json
import os
from collections import Counter

from .normalize import REGION_LABEL, REGION_ORDER


def _group_title(c) -> str:
    if c.region == "foreign":
        return f"国外-{c.country or '其他'}"
    return REGION_LABEL.get(c.region, "其他")


def render_m3u(selected, epg_url: str = "") -> str:
    """selected: {key: [Candidate]}。顺序：央视→卫视→地方台→港澳台→国外(按国家)。"""
    lines = ["#EXTM3U"]
    if epg_url:
        lines[0] += f' x-tvg-url="{epg_url}"'

    def region_rank(c):
        return (REGION_ORDER.index(c.region) if c.region in REGION_ORDER else 99,
                c.country or "", c.display)

    channels = sorted((items[0] for items in selected.values()), key=region_rank)
    for main in channels:
        for idx, c in enumerate(selected[main.key]):
            label = c.display if idx == 0 else f"{c.display}·备用{idx}"
            lines.append(
                f'#EXTINF:-1 tvg-name="{c.key}" group-title="{_group_title(c)}",{label}')
            lines.append(c.entry.url)
    return "\n".join(lines) + "\n"


def render_report(candidates, out_csv: str) -> None:
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["频道名", "归一化", "地区", "国家", "来源", "URL",
                    "可播放", "编码", "分辨率", "像素", "延迟ms", "耗时ms", "失败原因"])
        for c in candidates:
            r = c.result
            w.writerow([
                c.display, c.key, c.region, c.country, c.entry.source, c.entry.url,
                "是" if (r and r.playable) else "否",
                r.codec if r else "", f"{r.width}x{r.height}" if r else "",
                r.pixels if r else 0,
                r.latency_ms if r else -1, r.elapsed_ms if r else 0,
                (r.error if r else "") or "",
            ])


def render_stats(candidates, selected, elapsed_s: float, out_json: str) -> dict:
    playable = sum(1 for c in candidates if c.result and c.result.playable)
    hd = sum(1 for items in selected.values() for _ in items)
    stats = {
        "elapsed_seconds": round(elapsed_s, 1),
        "channels_final": len(selected),
        "entries_final": hd,
        "candidates_probed": len(candidates),
        "candidates_playable": playable,
        "regions": dict(Counter(i[0].region for i in selected.values())),
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    return stats


def write_outputs(out_dir: str, m3u: str) -> str:
    path = os.path.join(out_dir, "iptv_all.m3u")
    with open(path, "w", encoding="utf-8") as f:
        f.write(m3u)
    return path
