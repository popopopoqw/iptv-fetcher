# iptv-fetcher

自动抓取公开 IPTV 聚合源 → 分级漏斗验证（可播放性/真实分辨率/延迟，纯 HTTP）→
去重择优（同频道取分辨率最高、延迟最低者）→ 生成按「中国 → 国外」排序的 M3U →
发布到 GitHub 仓库与 Cloudflare R2/Worker 供播放器订阅。

## 工作流程

```
8个上游聚合源 ──抓取解析──▶ 按频道名归一化聚合(默认不限候选数)
──▶ L1 播放列表HTTP检查: 非200/非m3u8淘汰; 多码率主列表按RESOLUTION属性过滤
──▶ L2 首分片(Range 64KB)校验: TS同步字节/fMP4 box + H.264 SPS解析真实分辨率
──▶ 过滤≥阈值(默认1080p) ──▶ 择优: 分辨率降序→延迟升序
──▶ iptv_all.m3u(央视→卫视→地方台→港澳台→国外按国家) + report.csv
──▶ git push GitHub + 上传 R2（未配置凭据自动跳过）
```

默认走分级漏斗验证（纯 asyncio HTTP，L1 并发 300），1.5 万候选约 10-20 分钟。
ffprobe 已完全停用（太慢）：相关代码注释保留在 `prober.py` 与 `__main__.py`，
运行时零 ffmpeg 依赖（Docker 镜像也不装）。rtmp/udp 等非 HTTP 源会标记为
「非HTTP协议(ffprobe已停用)」并跳过。

## 本地运行

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# 系统需已安装 git（发布用）；运行时无需 ffmpeg，
# 仅本地跑 SPS 单元测试时需要（无 ffmpeg 该测试自动跳过）

.venv/bin/python -m pytest tests/ -q          # 单元测试
.venv/bin/python -m iptv_fetcher --smoke      # 快速自检(3源/30探测)
.venv/bin/python -m iptv_fetcher              # 全量运行(约30-60分钟)
```

输出在 `output/`：`iptv_all.m3u`（订阅列表）、`report.csv`（全量验证明细）、
`stats.json`（统计）。

## 配置（config.yaml）

| 配置 | 说明 |
|---|---|
| `min_resolution` | 分辨率阈值，默认 1080（按像素面积判定，1920x1076 视为达标） |
| `candidates_per_channel` | 每个频道最多验证几个候选源，0=不限制（默认全量验证） |
| `backups_per_channel` | 每个频道保留几个备用源 |
| `probe_concurrency` / `probe_timeout` | 已停用的 ffprobe 参数，保留备用 |
| `funnel.l1_concurrency` / `l2_concurrency` | 漏斗 L1/L2 的 HTTP 并发数 |
| `funnel.http_timeout` / `segment_bytes` | 单请求超时与首分片读取字节数 |
| `proxy` | 出网代理（抓取与延迟测量用 aiohttp 代理） |
| `sources` | 上游源列表，可增删；`region_hint` 决定无归属频道的默认地区 |
| `mirror_prefixes` | GitHub raw 直连失败时的镜像前缀，依次重试 |

## 部署方式一：GitHub Actions 定时任务（推荐，免服务器）

把本项目整体推到 GitHub 仓库即可，`.github/workflows/update.yml` 已就绪：

- 每日北京时间 08:00 自动运行（UTC 00:00，Actions 的 cron 偶有几分钟延迟属正常），
  也可在仓库 Actions 页面手动触发（workflow_dispatch）
- 运行流程：抓取 8 个上游源 → 漏斗验证 → 结果（`output/iptv_all.m3u`、
  `report.csv`、`stats.json`）自动提交回仓库 → R2 上传（可选）
- 可选启用 R2：在仓库 Settings → Secrets and variables → Actions 添加
  `R2_BUCKET` / `R2_ENDPOINT` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` 四个密钥
- 订阅链接即 `https://raw.githubusercontent.com/<用户名>/<仓库>/main/output/iptv_all.m3u`
  （也可开 Pages，或配 Cloudflare Worker 分发，见 `cloudflare/`）

注意：Actions 运行器在美国，对国内直连源的可达性与本地/国内网络不同，
验证结果反映的是「海外访问视角」；国内源失败率会偏高。如需国内视角，
用部署方式二在国内 VM 跑，结果推回同一仓库。

## 部署方式二：虚拟机（Docker 或 cron）

适合需要「国内网络视角」验证结果的场景。

Docker：

```bash
cp .env.example .env   # 填写凭据（GH_* 用于把结果推回 GitHub 仓库）
cd deploy && docker compose up -d --build
```

容器启动即运行一次，之后每天 03:00 自动运行。

裸机 + cron：项目放到 `/opt/iptv-fetcher`，然后

```bash
crontab -e
# 加入 deploy/crontab.example 里的那一行
```

## 发布订阅链接

Actions 方式下结果已自动提交到仓库（见方式一），无需额外配置；订阅链接：
`https://raw.githubusercontent.com/<用户名>/<仓库>/main/output/iptv_all.m3u`。
VM 方式或需要额外发布渠道时，凭据放 `.env`（见 `.env.example`），互相独立、都可选：

- **GitHub**：程序自动 push 到 `GH_REPO`。订阅链接即
  `https://raw.githubusercontent.com/<GH_REPO>/main/output/iptv_all.m3u`，
  也可开启仓库 Pages。
- **Cloudflare Worker + R2**：
  1. 创建 R2 bucket，生成 S3 API 令牌，填入 `.env` 的 R2_* 四项；
  2. `cd cloudflare && cp wrangler.toml wrangler.toml && npx wrangler deploy`，
     按需启用 `[[r2_buckets]]` 绑定或仅保留 `GITHUB_RAW_URL` 回退；
  3. 订阅链接即 Worker 分配的 `https://<worker>.<account>.workers.dev/iptv_all.m3u`。

## 注意事项

- 验证结果与运行网络的地理位置相关：国内源在海外 VM 上可能大量超时，
  反之亦然；必要时配置 `proxy`。
- 漏斗验证的是「HTTP 层可拉到有效媒体数据+分辨率达标」，码率过低的源仍可能有卡顿。
- 上游均为互联网公开分享源，仅供个人学习测试，请自行评估合规性。
