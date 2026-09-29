from iptv_fetcher.fetchers import parse_m3u, parse_txt

M3U_SAMPLE = """#EXTM3U x-tvg-url="https://epg.example/e.xml"
#EXTINF:-1 tvg-id="1" tvg-country="CN" group-title="央视",CCTV-1 综合
https://example.com/cctv1.m3u8
#EXTINF:-1 tvg-id="2" tvg-country="US" group-title="News",CNN (720p)
#EXTVLCOPT:http-user-agent=Mozilla/5.0
https://example.com/cnn.m3u8
#EXTINF:-1,坏条目-无地址
"""

TXT_SAMPLE = """更新时间,#genre#
20260928,https://example.com/update.mp4
央视频道,#genre#
CCTV1,http://example.com/1.m3u8
CCTV5+,http://example.com/5p.m3u8
"""


def test_parse_m3u_basic():
    entries = parse_m3u(M3U_SAMPLE, "test", "cn")
    assert len(entries) == 2
    e1, e2 = entries
    assert e1.name == "CCTV-1 综合"
    assert e1.url == "https://example.com/cctv1.m3u8"
    assert e1.tvg_country == "CN"
    assert e1.group == "央视"
    assert e2.name == "CNN (720p)"


def test_parse_m3u_skips_vlcopt():
    entries = parse_m3u(M3U_SAMPLE, "test", "cn")
    assert entries[1].url == "https://example.com/cnn.m3u8"


def test_parse_txt():
    entries = parse_txt(TXT_SAMPLE, "test", "cn")
    assert len(entries) == 3
    assert entries[0].name == "20260928"  # 更新时间行也是合法条目
    assert entries[1].name == "CCTV1"
    assert entries[1].group == "央视频道"
    assert entries[2].url == "http://example.com/5p.m3u8"
