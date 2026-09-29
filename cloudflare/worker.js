/**
 * IPTV 订阅分发 Worker：
 * 优先读 R2 绑定（IPTV_BUCKET）里的列表；未绑定或对象缺失时回退代理 GitHub raw。
 * 环境变量（wrangler.toml [vars]）：GITHUB_RAW_URL，如
 *   https://raw.githubusercontent.com/<user>/<repo>/main/iptv_all.m3u
 */
const R2_KEY = "iptv/iptv_all.m3u";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/report") {
      return serve(await getFrom(env, "report.csv"), "text/csv; charset=utf-8");
    }
    if (url.pathname !== "/" && url.pathname !== "/iptv_all.m3u") {
      return new Response("not found", { status: 404 });
    }
    return serve(await getFrom(env, R2_KEY), "application/x-mpegURL; charset=utf-8");
  },
};

async function getFrom(env, key) {
  if (env.IPTV_BUCKET) {
    const obj = await env.IPTV_BUCKET.get(key);
    if (obj) return new Response(obj.body, { status: 200 });
  }
  if (env.GITHUB_RAW_URL) {
    const target = key.endsWith(".csv")
      ? env.GITHUB_RAW_URL.replace(/iptv_all\.m3u$/, "report.csv")
      : env.GITHUB_RAW_URL;
    const resp = await fetch(target, { cf: { cacheTtl: 3600, cacheEverything: true } });
    if (resp.ok) return new Response(resp.body, { status: resp.status });
  }
  return new Response("playlist unavailable", { status: 503 });
}

function serve(body, contentType) {
  if (body.status !== 200) return body;
  const headers = new Headers(body.headers);
  headers.set("Content-Type", contentType);
  headers.set("Cache-Control", "max-age=3600");
  headers.set("Access-Control-Allow-Origin", "*");
  return new Response(body.body, { status: 200, headers });
}
