"""发布：git push 到 GitHub 仓库 / 上传 Cloudflare R2。凭据在 .env，未配置则跳过。"""
import logging
import os
import shutil
import subprocess

log = logging.getLogger("publish")


def _run(cmd, cwd=None) -> bool:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        log.warning("命令失败 %s: %s", " ".join(cmd[:3]), (r.stderr or "").strip()[:300])
        return False
    return True


def publish_github(files: dict, repo: str, token: str, branch: str, workroot: str) -> bool:
    if not (repo and token):
        log.info("未配置 GH_REPO/GH_TOKEN，跳过 GitHub 发布")
        return False
    workdir = os.path.join(workroot, "publish-repo")
    url = f"https://x-access-token:{token}@github.com/{repo}.git"
    if not os.path.isdir(os.path.join(workdir, ".git")):
        shutil.rmtree(workdir, ignore_errors=True)
        if not _run(["git", "clone", "--depth", "1", "-b", branch, url, workdir]):
            return False
    if not _run(["git", "pull", "--ff-only"], cwd=workdir):
        return False
    for name, content in files.items():
        with open(os.path.join(workdir, name), "w", encoding="utf-8") as f:
            f.write(content)
    if not (_run(["git", "add", "-A"], cwd=workdir)
            and _run(["git", "-c", "user.name=iptv-fetcher",
                      "-c", "user.email=iptv-fetcher@localhost",
                      "commit", "-m", "update playlist"], cwd=workdir)):
        return False
    ok = _run(["git", "push", "origin", branch], cwd=workdir)
    log.info("GitHub 发布%s", "完成" if ok else "失败")
    return ok


def publish_r2(files: dict, bucket: str, endpoint: str, key: str) -> bool:
    if not all(os.environ.get(k) for k in
               ("R2_BUCKET", "R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")):
        log.info("未配置 R2 环境变量，跳过 R2 发布")
        return False
    try:
        import boto3
        client = boto3.client(
            "s3", endpoint_url=os.environ["R2_ENDPOINT"],
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto")
        client.put_object(
            Bucket=bucket or os.environ["R2_BUCKET"], Key=key,
            Body=files["iptv_all.m3u"].encode("utf-8"),
            ContentType="application/x-mpegURL", CacheControl="max-age=3600")
        log.info("R2 发布完成: %s", key)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("R2 发布失败: %s", e)
        return False
