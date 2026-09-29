"""入口：python -m iptv_fetcher [--config PATH] [--smoke] [--fetch-only] [--skip-publish] [--ffprobe]"""
import argparse
import asyncio
import logging
import os
import time

from .fetchers import fetch_all
from .funnel import run_funnel
from .models import ROOT, load_config
from .normalize import build_candidates
# ffprobe 验证已停用（保留备用）：
# from .prober import probe_all
from .publish import publish_github, publish_r2
from .render import render_m3u, render_report, render_stats, write_outputs
from .selector import select_best

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


async def run(cfg, smoke: bool = False, fetch_only: bool = False,
              skip_publish: bool = False, ffprobe_mode: bool = False) -> dict:
    t0 = time.monotonic()
    out_dir = os.path.join(os.path.dirname(os.path.abspath(cfg.path)), "output")
    os.makedirs(out_dir, exist_ok=True)

    entries = await fetch_all(cfg)
    if not entries:
        raise SystemExit("没有任何上游源抓取成功，请检查网络或 config.yaml")
    candidates = build_candidates(entries, cfg.candidates_per_channel)
    log.info("归一化后待验证候选 %d 个", len(candidates))
    if fetch_only:
        return {"candidates": len(candidates)}

    limit = 30 if smoke else 0
    # ffprobe 完整验证模式已停用（保留备用）：
    # if ffprobe_mode:
    #     log.info("使用完整 ffprobe 模式")
    #     candidates = await probe_all(candidates, cfg, limit=limit)
    # else:
    #     candidates = await run_funnel(candidates, cfg, limit=limit)
    candidates = await run_funnel(candidates, cfg, limit=limit)
    selected = select_best(candidates, cfg)
    log.info("择优后频道 %d 个", len(selected))

    m3u = render_m3u(selected, cfg.epg_url)
    m3u_path = write_outputs(out_dir, m3u)
    render_report(candidates, os.path.join(out_dir, "report.csv"))
    stats = render_stats(candidates, selected, time.monotonic() - t0,
                         os.path.join(out_dir, "stats.json"))
    log.info("输出 %s | %s", m3u_path, stats)

    if not skip_publish:
        pub = cfg.publish or {}
        workroot = os.path.dirname(out_dir)
        publish_github(
            {"iptv_all.m3u": m3u, "report.csv": open(
                os.path.join(out_dir, "report.csv"), encoding="utf-8-sig").read()},
            os.environ.get("GH_REPO", ""), os.environ.get("GH_TOKEN", ""),
            os.environ.get("GH_BRANCH", "main"), workroot)
        r2 = (pub.get("r2") or {})
        publish_r2({"iptv_all.m3u": m3u}, r2.get("bucket", ""),
                   os.environ.get("R2_ENDPOINT", ""), r2.get("key", "iptv/iptv_all.m3u"))
    return stats


def main():
    ap = argparse.ArgumentParser(prog="iptv_fetcher")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.yaml"))
    ap.add_argument("--smoke", action="store_true", help="快速自检：仅3个源、30个探测")
    ap.add_argument("--fetch-only", action="store_true")
    ap.add_argument("--skip-publish", action="store_true")
    # ffprobe 模式开关已停用（保留备用）：
    # ap.add_argument("--ffprobe", action="store_true",
    #                 help="完整ffprobe验证（慢，默认用分级漏斗）")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.smoke:
        cfg.sources = cfg.sources[:3]
        cfg.probe_concurrency = 8
    stats = asyncio.run(run(cfg, smoke=args.smoke,
                            fetch_only=args.fetch_only, skip_publish=args.skip_publish))
    print(stats)


if __name__ == "__main__":
    main()
