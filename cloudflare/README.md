# Cloudflare 配置指南

两种方案：**方案 B（Worker + R2，推荐）**结果存在 Cloudflare 自己的存储里，
不依赖 GitHub raw 的可达性；**方案 A（仅 Worker 代理）**零存储、5 分钟搞定。

共同前置：一个 Cloudflare 账号（免费版即可）。

## 方案 B：Worker + R2（推荐）

### 1. 创建 R2 bucket

Dashboard → R2 Object Storage → Create bucket → 名字如 `iptv`。
（首次使用需开通 R2，免费额度 10GB 存储/月，本列表约 1MB，远用不完。）

### 2. 创建 R2 API 令牌（给 GitHub Actions 上传用）

R2 概览页 → Manage R2 API Tokens → Create API Token：
- 权限：Object Read & Write
- Specify bucket：只勾刚建的 `iptv`
- 创建后记下三样：Access Key ID、Secret Access Key、
  Endpoint（形如 `https://<账户ID>.r2.cloudflarestorage.com`，只出现一次）

### 3. 在 GitHub 仓库配置 Secrets

仓库 Settings → Secrets and variables → Actions → New repository secret，
添加四个（workflow 已内置读取）：

| Secret 名 | 值 |
|---|---|
| `R2_BUCKET` | `iptv` |
| `R2_ENDPOINT` | `https://<账户ID>.r2.cloudflarestorage.com` |
| `R2_ACCESS_KEY_ID` | 第 2 步的 Access Key ID |
| `R2_SECRET_ACCESS_KEY` | 第 2 步的 Secret Access Key |

配好后下次 Action 运行会自动把 `iptv_all.m3u` 上传到 R2 的
`iptv/iptv_all.m3u`（日志里出现「R2 发布完成」即成功）。

### 4. 部署 Worker（绑定 R2）

编辑本目录 `wrangler.toml`：

```toml
[[r2_buckets]]
binding = "IPTV_BUCKET"
bucket_name = "iptv"        # 与 R2_BUCKET 一致
```

然后部署（任选其一）：

```bash
# 方式1：本机有 node
cd cloudflare && npx wrangler deploy
# 首次会浏览器登录 Cloudflare 授权

# 方式2：Dashboard 网页操作（不想装 node）
# Workers & Pages → Create → Worker → 创建后 Edit code
# 把 worker.js 全文粘贴进去 → Save and deploy
# 再 Settings → Variables and Bindings → Add → R2 Bucket
#   Variable name 填 IPTV_BUCKET，选择 iptv bucket
```

部署后拿到地址：`https://<worker名>.<账户名>.workers.dev/iptv_all.m3u`
——这就是固定订阅链接，优先读 R2（新），读不到自动回退代理 GitHub raw（旧）。

## 方案 A：仅 Worker 代理（最简）

跳过上面 1-3 步，只做第 4 步，但使用环境变量回退模式：
`wrangler.toml` 的 `[vars]` 里把 `GITHUB_RAW_URL` 改成你的实际仓库地址：

```toml
[vars]
GITHUB_RAW_URL = "https://raw.githubusercontent.com/popopopoqw/iptv-fetcher/main/output/iptv_all.m3u"
```

Worker 直接代理该地址并加 1 小时缓存。结果仍在 GitHub 仓库里，
Worker 只提供固定入口 + 全球 CDN。

## 国内可用性提示

`*.workers.dev` 域名在中国大陆经常被 DNS 污染，直连不稳定。如果你有
托管在 Cloudflare 的自有域名：Worker 设置 → Domains & Routes → Add Custom
Domain（如 `iptv.你的域名.com`），绑定后国内访问即可恢复。没有域名时，
播放器端建议先用 jsDelivr 链接，海外网络用 workers.dev。

## 订阅链接清单

| 渠道 | 链接 | 特点 |
|---|---|---|
| GitHub raw | `https://raw.githubusercontent.com/<repo>/main/output/iptv_all.m3u` | 最源头，国内可能被墙 |
| jsDelivr | `https://cdn.jsdelivr.net/gh/<repo>@main/output/iptv_all.m3u` | 国内快，CDN 缓存数小时 |
| Worker | `https://<worker>.<账户>.workers.dev/iptv_all.m3u` | 固定、带缓存，国内需自定义域名 |
| Worker 自定义域名 | `https://iptv.你的域名/iptv_all.m3u` | 国内可用，最佳 |
| Worker 明细 | 同上，路径换 `/report` | 验证明细 CSV |
