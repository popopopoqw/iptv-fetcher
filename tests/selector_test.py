from iptv_fetcher.models import Candidate, Config, Entry, ProbeResult
from iptv_fetcher.selector import min_pixels, select_best


def _cand(key, url, source, playable, w, h, latency):
    c = Candidate(key=key, display=key, entry=Entry(key, url, source))
    c.result = ProbeResult(url=url, playable=playable, width=w, height=h,
                           latency_ms=latency)
    return c


def _cfg(**kw):
    return Config(min_resolution=kw.get("min_resolution", 1080),
                  backups_per_channel=kw.get("backups_per_channel", 2))


def test_min_pixels_threshold():
    th = min_pixels(1080)
    assert 1920 * 1076 >= th      # 裁切流算1080p
    assert 1280 * 720 < th        # 720p 不达标
    assert 1080 * 404 < th        # 宽1080但矮不算


def test_select_best_orders_by_resolution_then_latency():
    cands = [
        _cand("cctv1", "http://a", "s1", True, 1920, 1080, 900),
        _cand("cctv1", "http://b", "s2", True, 1920, 1080, 300),
        _cand("cctv1", "http://c", "s3", True, 1280, 720, 10),   # 不达标
        _cand("cctv1", "http://d", "s4", False, 3840, 2160, 5),  # 不可播
        _cand("cctv1", "http://e", "s5", True, 3840, 2160, 800), # 最高分辨率优先
    ]
    sel = select_best(cands, _cfg())
    assert list(sel) == ["cctv1"]
    ranked = sel["cctv1"]
    assert ranked[0].entry.url == "http://e"          # 4K最优先
    assert ranked[1].entry.url == "http://b"          # 同分辨率看延迟
    assert ranked[2].entry.url == "http://a"
    assert len(ranked) == 3                           # 主源+2备用


def test_select_filters_low_resolution_channels():
    cands = [_cand("a", "http://a", "s1", True, 1280, 720, 50)]
    assert select_best(cands, _cfg()) == {}
    # 阈值降到720p后保留
    sel = select_best(cands, _cfg(min_resolution=720))
    assert "a" in sel
