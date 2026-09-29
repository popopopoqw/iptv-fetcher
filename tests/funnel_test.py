import shutil
import subprocess

import pytest

from iptv_fetcher.funnel import (
    find_stream_resolution, is_fmp4, is_ts, parse_master, first_segment_uri,
)


def test_is_ts_sync_bytes():
    good = (b"\x47" + b"\x00" * 187) * 3
    assert is_ts(good)
    assert not is_ts(b"\x47" + b"\x00" * 100)          # 太短
    assert not is_ts(b"\x00" + good[1:])                # 首同步位缺失


def test_is_fmp4_boxes():
    assert is_fmp4(b"\x00\x00\x00\x18ftypiso5" + b"\x00" * 16)
    assert is_fmp4(b"\x00\x00\x01\x00moovxxxx")
    assert not is_fmp4(b"\x00\x00\x00\x18xxxxiso5" + b"\x00" * 16)


def test_parse_master_variants():
    body = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720
720/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=8000000,RESOLUTION=1920x1080
1080/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=500000
audio/index.m3u8
"""
    variants = parse_master(body, "https://cdn.example/live/master.m3u8")
    assert variants == [
        (1280, 720, "https://cdn.example/live/720/index.m3u8"),
        (1920, 1080, "https://cdn.example/live/1080/index.m3u8"),
        (0, 0, "https://cdn.example/live/audio/index.m3u8"),
    ]


def test_first_segment_uri_relative():
    body = "#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:5.0,\nseg-001.ts\n#EXTINF:5.0,\nseg-002.ts\n"
    assert first_segment_uri(body, "https://x.example/a/pl.m3u8") == \
        "https://x.example/a/seg-001.ts"
    assert first_segment_uri("#EXTM3U\n#EXTINF:1,\nhttp://abs/s.ts\n", "https://x/") == \
        "http://abs/s.ts"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="需要 ffmpeg")
@pytest.mark.parametrize("w,h", [(1920, 1080), (1280, 720), (640, 360)])
def test_sps_resolution_from_real_h264_stream(tmp_path, w, h):
    out = tmp_path / f"v_{w}x{h}.h264"
    subprocess.run([
        "ffmpeg", "-v", "quiet", "-y",
        "-f", "lavfi", "-i", f"color=gray:s={w}x{h}:d=0.2:r=25",
        "-c:v", "libx264", "-x264-params", "repeat-headers=1",
        str(out)], check=True)
    res = find_stream_resolution(out.read_bytes())
    assert res is not None
    rw, rh, codec = res
    assert codec == "h264"
    assert abs(rw - w) <= 16 and abs(rh - h) <= 16   # 允许宏块对齐/裁切的小偏差


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="需要 ffmpeg")
@pytest.mark.parametrize("w,h", [(1920, 1080), (1280, 720)])
def test_sps_resolution_from_real_hevc_stream(tmp_path, w, h):
    out = tmp_path / f"v_{w}x{h}.hevc"
    subprocess.run([
        "ffmpeg", "-v", "quiet", "-y",
        "-f", "lavfi", "-i", f"color=gray:s={w}x{h}:d=0.2:r=25",
        "-c:v", "libx265", "-x265-params", "repeat-headers=1",
        str(out)], check=True)
    res = find_stream_resolution(out.read_bytes())
    assert res is not None
    rw, rh, codec = res
    assert codec == "h265"
    assert abs(rw - w) <= 16 and abs(rh - h) <= 16


def test_sps_garbage_returns_none():
    assert find_stream_resolution(b"\x00" * 4096) is None
    assert find_stream_resolution(b"") is None
