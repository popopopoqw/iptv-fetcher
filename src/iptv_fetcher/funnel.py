"""分级漏斗验证（方案一 L1+L2）：
L1: HTTP 拉取播放列表——非200/非m3u8淘汰；多码率主列表直接按 RESOLUTION 属性过滤。
L2: Range 拉首分片前64KB——TS 同步字节/fMP4 box 校验，并从 Annex-B 流中解析
    H.264 与 H.265/HEVC 的 SPS 得到真实分辨率（含裁切窗口换算）。
非 http(s) 协议（rtmp/udp 等）原走 ffprobe 兜底，现已停用（保留备用），
此类源直接标记为「非HTTP协议(ffprobe已停用)」。
"""
import asyncio
import logging
import re
import time
from urllib.parse import urljoin

import aiohttp

from .models import ProbeResult
# ffprobe 兜底已停用（保留备用）：
# from .prober import probe_one

log = logging.getLogger("funnel")

STREAM_INF_RE = re.compile(r"#EXT-X-STREAM-INF:(.*)")
RESOLUTION_RE = re.compile(r"RESOLUTION=(\d+)x(\d+)")
PLAYLIST_CAP = 512 * 1024


# ---------- SPS 解析（H.264 Annex-B → 宽高） ----------

class BitReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def u(self, n: int) -> int:
        v = 0
        for _ in range(n):
            byte = self.data[self.pos >> 3]
            v = (v << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v

    def ue(self) -> int:
        lz = 0
        while self.u(1) == 0:
            lz += 1
            if lz > 32:
                raise ValueError("exp-Golomb 前导零过长")
        return (1 << lz) - 1 + self.u(lz) if lz else 0

    def se(self) -> int:
        k = self.ue()
        return (k + 1) // 2 if k % 2 else -(k // 2)


HIGH_PROFILES = {100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135}


def _scaling_list(br: BitReader, size: int) -> None:
    last = nxt = 8
    for _ in range(size):
        if nxt != 0:
            delta = br.se()
            nxt = (last + delta + 256) % 256
        if nxt != 0:
            last = nxt


def strip_emulation(data: bytes) -> bytes:
    """去除 RBSP 防竞争字节（00 00 03 → 00 00），SPS 位读前必须处理。"""
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        if i + 2 < n and data[i] == 0 and data[i + 1] == 0 and data[i + 2] == 3:
            out += b"\x00\x00"
            i += 3
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


def parse_sps(data: bytes):
    """解析 SPS NAL 单元载荷（不含起始码和 NAL 头），返回 (width, height)。"""
    br = BitReader(data)
    br.u(1)             # forbidden_zero
    br.u(2)             # nal_ref_idc
    br.u(5)             # nal_type(=7)，调用方已保证
    profile = br.u(8)
    br.u(8)             # constraint flags
    br.u(8)             # level_idc
    br.ue()             # seq_parameter_set_id
    chroma = 1
    if profile in HIGH_PROFILES:
        chroma = br.ue()
        if chroma == 3:
            br.u(1)     # separate_colour_plane_flag
        br.ue()         # bit_depth_luma_minus8
        br.ue()         # bit_depth_chroma_minus8
        br.ue()         # qpprime_y_zero_transform_bypass
        if br.u(1):     # seq_scaling_matrix_present
            for i in range(8 if chroma != 3 else 12):
                if br.u(1):
                    _scaling_list(br, 16 if i < 6 else 64)
    br.ue()             # log2_max_frame_num_minus4
    poc = br.ue()       # pic_order_cnt_type
    if poc == 0:
        br.ue()
    elif poc == 1:
        br.u(1)
        for _ in range(br.ue()):
            br.se()
    br.ue()             # max_num_ref_frames
    br.u(1)             # gaps_in_frame_num_value_allowed
    w_mbs = br.ue()     # pic_width_in_mbs_minus1
    h_map = br.ue()     # pic_height_in_map_units_minus1
    frame_mbs_only = br.u(1)
    if not frame_mbs_only:
        br.u(1)         # mb_adaptive_frame_field_flag
    br.u(1)             # direct_8x8_inference_flag
    crop = [0, 0, 0, 0]
    if br.u(1):         # frame_cropping_flag
        crop = [br.ue() for _ in range(4)]
    # 4:2:0 的 CropUnit；4:4:4/高位深罕见于 IPTV，按 2/2 处理偏差可忽略
    crop_x, crop_y = (1, 2 - frame_mbs_only) if chroma in (0, 3) else (2, 2 * (2 - frame_mbs_only))
    width = (w_mbs + 1) * 16 - (crop[0] + crop[1]) * crop_x
    height = (2 - frame_mbs_only) * (h_map + 1) * 16 - (crop[2] + crop[3]) * crop_y
    return width, height


def parse_hevc_sps(data: bytes):
    """解析 H.265/HEVC SPS 载荷（去掉2字节NAL头后），返回 (width, height)。
    HEVC 的宽高直接以亮度样本数给出，无需宏块换算。"""
    br = BitReader(data)
    br.u(4)                 # sps_video_parameter_set_id
    max_sub_minus1 = br.u(3)
    br.u(1)                 # sps_temporal_id_nesting_flag
    # ---- profile_tier_level(1, max_sub_minus1) ----
    br.u(2)                 # general_profile_space
    br.u(1)                 # general_tier_flag
    br.u(5)                 # general_profile_idc
    br.u(32)                # general_profile_compatibility_flags
    br.u(4)                 # progressive/interlaced/non_packed/frame_only
    br.u(43)                # 保留约束位
    br.u(1)                 # inbld/保留位
    br.u(8)                 # general_level_idc
    flags = [(br.u(1), br.u(1)) for _ in range(max_sub_minus1)]
    for pp, lp in flags:
        if pp:
            br.u(88)
        if lp:
            br.u(8)
    # ---- SPS 正文 ----
    br.ue()                 # sps_seq_parameter_set_id
    chroma = br.ue()        # chroma_format_idc
    if chroma == 3:
        br.u(1)             # separate_colour_plane_flag
    width = br.ue()         # pic_width_in_luma_samples
    height = br.ue()        # pic_height_in_luma_samples
    if br.u(1):             # conformance_window_flag
        off = [br.ue() for _ in range(4)]
        sub = {0: (1, 1), 1: (2, 2), 2: (2, 1), 3: (1, 1)}[chroma]
        width -= (off[0] + off[1]) * sub[0]
        height -= (off[2] + off[3]) * sub[1]
    return width, height


def find_stream_resolution(buf: bytes):
    """在 Annex-B 字节流中查找 H.264(NAL type 7) 或 HEVC(NAL type 33) 的 SPS，
    返回 (width, height, codec)，找不到返回 None。"""
    starts = []
    i = buf.find(b"\x00\x00\x01")
    while i != -1 and len(starts) < 96:
        starts.append(i + 3)
        i = buf.find(b"\x00\x00\x01", i + 3)
    for idx, start in enumerate(starts):
        end = starts[idx + 1] - 3 if idx + 1 < len(starts) else len(buf)
        head = buf[start:end]
        if len(head) < 4:
            continue
        try:
            # H.264: NAL头1字节，类型=byte&0x1F，SPS=7，forbidden_bit须为0
            if (head[0] & 0x1F) == 7 and not (head[0] & 0x80):
                return (*parse_sps(strip_emulation(head[1:])), "h264")
            # HEVC: NAL头2字节，类型=(byte>>1)&0x3F，SPS=33
            if ((head[0] >> 1) & 0x3F) == 33:
                return (*parse_hevc_sps(strip_emulation(head[2:])), "h265")
        except Exception:  # noqa: BLE001 截断的 SPS 换下一个起始码
            continue
    return None


def is_ts(buf: bytes) -> bool:
    return len(buf) >= 376 and all(
        buf[i] == 0x47 for i in range(0, 376, 188))


def is_fmp4(buf: bytes) -> bool:
    if len(buf) < 8:
        return False
    return buf[4:8] in (b"ftyp", b"styp", b"moov", b"moof", b"emsg", b"free", b"skip")


# ---------- 播放列表解析 ----------

def parse_master(body: str, base_url: str):
    """返回 [(w, h, uri)] 变体列表，无 RESOLUTION 属性的变体 w=h=0。"""
    variants, uri = [], ""
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-STREAM-INF"):
            m = RESOLUTION_RE.search(line)
            variants.append((int(m.group(1)), int(m.group(2)), "") if m else (0, 0, ""))
            continue
        if line.startswith("#"):
            continue
        if variants and not variants[-1][2]:
            variants[-1] = (*variants[-1][:2], urljoin(base_url, line))
    return [v for v in variants if v[2]]


def first_segment_uri(body: str, base_url: str) -> str:
    for raw in body.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            return urljoin(base_url, line)
    return ""


# ---------- L1/L2 主流程 ----------

async def _get(session, url, timeout, headers=None):
    """GET 并读取有限字节，返回 (status, ttfb_ms, bytes)。"""
    t0 = time.monotonic()
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout, connect=5),
                           headers=headers or {}) as resp:
        data = await resp.content.read(PLAYLIST_CAP)
        return resp.status, int((time.monotonic() - t0) * 1000), data


def _validate_segment(data: bytes, declared: "tuple[int,int]", threshold: int,
                      ttfb_sum: int, result: ProbeResult) -> None:
    """L2：分片内容校验 + 分辨率判定（SPS 优先，声明值兜底）。"""
    if is_ts(data):
        res = find_stream_resolution(data)
        if res:
            result.playable = True
            result.width, result.height, result.codec = res
        elif declared[0] and declared[0] * declared[1] >= threshold:
            result.playable = True
            result.codec = "ts(分辨率取声明值)"
            result.width, result.height = declared
        else:
            result.error = "L2:TS有效但未解析到SPS/声明分辨率"
    elif is_fmp4(data):
        if declared[0] and declared[0] * declared[1] >= threshold:
            result.playable = True
            result.codec = "fmp4"
            result.width, result.height = declared
        else:
            result.error = "L2:fMP4无分辨率信息"
    else:
        result.error = "L2:非TS/fMP4数据"
    result.latency_ms = ttfb_sum


async def check_one(session, c, cfg, threshold: int, sem_l2: asyncio.Semaphore):
    url = c.entry.url
    r = ProbeResult(url=url)
    if not url.startswith(("http://", "https://")):
        # ffprobe 兜底已停用（保留备用）：
        # c.result = await probe_one(None, url, cfg.probe_timeout, cfg.proxy)
        # return
        r.error = "非HTTP协议(ffprobe已停用)"
        c.result = r
        return
    http_timeout = int((cfg.funnel or {}).get("http_timeout", 8))
    seg_bytes = int((cfg.funnel or {}).get("segment_bytes", 65536))
    try:
        status, ttfb, data = await _get(session, url, http_timeout)
    except Exception as e:  # noqa: BLE001
        r.error = f"L1:{type(e).__name__}"
        r.elapsed_ms = -1
        c.result = r
        return
    if status != 200:
        r.error = f"L1:HTTP{status}"
        c.result = r
        return
    text = data.decode("utf-8", "ignore").lstrip("\ufeff \t\r\n")

    if text.startswith("#EXTM3U"):
        if "#EXT-X-STREAM-INF" in text:            # 多码率主列表
            variants = parse_master(text, url)
            if not variants:
                r.error = "L1:主列表无变体"
                c.result = r
                return
            best = max(variants, key=lambda v: v[0] * v[1])
            if best[0] and best[0] * best[1] < threshold:
                r.error = f"L1:分辨率不足{best[0]}x{best[1]}"
                c.result = r
                return
            declared = (best[0], best[1])
            try:  # 拉最优变体的媒体列表再走 L2
                st2, ttfb2, d2 = await _get(session, best[2], http_timeout)
            except Exception as e:  # noqa: BLE001
                r.error = f"L2:{type(e).__name__}"
                c.result = r
                return
            if st2 != 200 or not d2:
                r.error = f"L2:变体列表HTTP{st2}"
                c.result = r
                return
            seg = first_segment_uri(d2.decode("utf-8", "ignore"), best[2])
            if not seg:
                r.error = "L2:媒体列表无分片"
                c.result = r
                return
            async with sem_l2:
                try:
                    st3, ttfb3, d3 = await _get(
                        session, seg, http_timeout,
                        headers={"Range": f"bytes=0-{seg_bytes - 1}"})
                except Exception as e:  # noqa: BLE001
                    r.error = f"L2:{type(e).__name__}"
                    c.result = r
                    return
            if st3 >= 400:
                r.error = f"L2:分片HTTP{st3}"
                c.result = r
                return
            await asyncio.get_event_loop().run_in_executor(
                None, _validate_segment, d3, declared, threshold, ttfb + ttfb2 + ttfb3, r)
        else:                                        # 媒体列表
            seg = first_segment_uri(text, url)
            if not seg:
                r.error = "L2:媒体列表无分片"
                c.result = r
                return
            async with sem_l2:
                try:
                    st2, ttfb2, d2 = await _get(
                        session, seg, http_timeout,
                        headers={"Range": f"bytes=0-{seg_bytes - 1}"})
                except Exception as e:  # noqa: BLE001
                    r.error = f"L2:{type(e).__name__}"
                    c.result = r
                    return
            if st2 >= 400:
                r.error = f"L2:分片HTTP{st2}"
                c.result = r
                return
            await asyncio.get_event_loop().run_in_executor(
                None, _validate_segment, d2, (0, 0), threshold, ttfb + ttfb2, r)
    elif is_ts(data) or is_fmp4(data):              # 直接流地址(.ts/.php等)
        await asyncio.get_event_loop().run_in_executor(
            None, _validate_segment, data, (0, 0), threshold, ttfb, r)
    else:
        r.error = "L1:非播放列表内容"
    c.result = r


async def run_funnel(candidates, cfg, limit: int = 0):
    """漏斗验证主入口，契约与 probe_all 相同（原地写 c.result）。"""
    from .selector import min_pixels
    threshold = min_pixels(cfg.min_resolution)

    if limit and len(candidates) > limit:
        stride = max(1, len(candidates) // limit)
        candidates = candidates[::stride][:limit]

    l1 = int((cfg.funnel or {}).get("l1_concurrency", 300))
    l2 = asyncio.Semaphore(int((cfg.funnel or {}).get("l2_concurrency", 150)))
    sem = asyncio.Semaphore(l1)
    conn = aiohttp.TCPConnector(limit=l1, ssl=False)
    done = [0]

    async def work(session, c):
        async with sem:
            await check_one(session, c, cfg, threshold, l2)
        done[0] += 1
        if done[0] % 500 == 0:
            log.info("漏斗进度 %d/%d", done[0], len(candidates))

    async with aiohttp.ClientSession(connector=conn, trust_env=bool(cfg.proxy)) as session:
        await asyncio.gather(*[work(session, c) for c in candidates])

    from collections import Counter
    reasons = Counter(
        (c.result.error.split(":")[0] if c.result and c.result.error else
         "可播放" if c.result and c.result.playable else "其他")
        for c in candidates)
    log.info("漏斗完成: %s", dict(reasons))
    return candidates
