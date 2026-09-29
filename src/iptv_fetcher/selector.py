"""择优：过滤可播放+分辨率达标，同频道按分辨率/延迟取最优。"""


def min_pixels(min_resolution: int) -> int:
    """1080p → 1920*1080*0.9 ≈ 186万，容许 1920x1076 这类裁切流。"""
    w = int(min_resolution * 16 / 9)
    return int(w * min_resolution * 0.9)


def passes_resolution(result, threshold_px: int) -> bool:
    return result.playable and result.pixels >= threshold_px


def select_best(candidates, cfg):
    """返回 {key: [Candidate按优劣排序]}，只含分辨率达标的可播放频道。"""
    threshold = min_pixels(cfg.min_resolution)
    groups: dict = {}
    for c in candidates:
        if c.result and passes_resolution(c.result, threshold):
            groups.setdefault(c.key, []).append(c)

    selected: dict = {}
    for key, items in groups.items():
        def rank(c):
            r = c.result
            lat = r.latency_ms if r.latency_ms >= 0 else 10 ** 9
            return (-r.pixels, lat)
        items.sort(key=rank)
        keep = items[0]
        # 备用源要求来自不同的 URL（跨上游天然去重）
        seen_urls = {keep.entry.url}
        backups = []
        for c in items[1:]:
            if c.entry.url not in seen_urls:
                backups.append(c)
                seen_urls.add(c.entry.url)
            if len(backups) >= cfg.backups_per_channel:
                break
        selected[key] = [keep] + backups
    return selected
