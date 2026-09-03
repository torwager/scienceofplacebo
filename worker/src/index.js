/**
 * Science of Placebo community API (Cloudflare Worker + KV).
 *
 * GET  /auth/login?return=<url>   start GitHub OAuth (state stored in KV for 10 min)
 * GET  /auth/callback             exchange code, create a session cookie (30 days), redirect back
 * POST /auth/logout               clear the session
 * GET  /api/me                    { login, avatar, stars: [...] } or 401
 * PUT  /api/stars   {ids:[...]}   replace the signed-in user's list (used to merge a browser list on first sign-in)
 * POST /api/star    {id, on}      add or remove one paper
 * GET  /api/picks                 { updated, picks: [{id, n}] } most-starred papers (public, cached 5 min)
 *
 * KV keys: state:<nonce> -> return url; sess:<token> -> {uid, login, avatar}; user:<uid> -> {login, avatar, stars, updated};
 *          counts -> {paperId: n}. Secrets (wrangler secret put): GITHUB_CLIENT_SECRET.
 */
const SESSION_DAYS = 30;

function cors(env, req, extra = {}) {
  const origin = req.headers.get("Origin");
  const allowed = [env.SITE_ORIGIN, "https://torwager.github.io", "http://localhost:8765"];
  const h = { "Vary": "Origin", ...extra };
  if (origin && allowed.includes(origin)) {
    h["Access-Control-Allow-Origin"] = origin;
    h["Access-Control-Allow-Credentials"] = "true";
    h["Access-Control-Allow-Methods"] = "GET,POST,PUT,OPTIONS";
    h["Access-Control-Allow-Headers"] = "Content-Type";
  }
  return h;
}
const json = (env, req, data, status = 200, extra = {}) => new Response(JSON.stringify(data), { status, headers: cors(env, req, { "Content-Type": "application/json; charset=utf-8", ...extra }) });
const rand = () => { const b = new Uint8Array(24); crypto.getRandomValues(b); return [...b].map(x => x.toString(16).padStart(2, "0")).join(""); };
const cookieOf = (req, name) => { const m = (req.headers.get("Cookie") || "").match(new RegExp("(?:^|;\\s*)" + name + "=([^;]+)")); return m ? m[1] : null; };
const sessionCookie = (token, maxAge) => `sop_session=${token}; Path=/; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=None`;

async function session(env, req) {
  const t = cookieOf(req, "sop_session");
  if (!t) return null;
  return env.STORE.get("sess:" + t, "json");
}
async function user(env, uid) { return (await env.STORE.get("user:" + uid, "json")) || { stars: [] }; }
async function saveUser(env, uid, u) { u.updated = new Date().toISOString(); await env.STORE.put("user:" + uid, JSON.stringify(u)); }
async function bumpCounts(env, changes) {
  // changes: {paperId: +1|-1}. Read-modify-write; fine at this site's scale.
  const counts = (await env.STORE.get("counts", "json")) || {};
  for (const [id, d] of Object.entries(changes)) { counts[id] = (counts[id] || 0) + d; if (counts[id] <= 0) delete counts[id]; }
  await env.STORE.put("counts", JSON.stringify(counts));
}
function safeReturn(env, url) {
  try { const u = new URL(url); if ([env.SITE_ORIGIN, "https://torwager.github.io", "http://localhost:8765"].includes(u.origin)) return u.toString(); } catch (e) { /* fall through */ }
  return env.SITE_ORIGIN + "/join.html";
}

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(env, req) });
    try {
      if (url.pathname === "/auth/login") {
        const state = rand();
        await env.STORE.put("state:" + state, safeReturn(env, url.searchParams.get("return") || ""), { expirationTtl: 600 });
        const gh = new URL("https://github.com/login/oauth/authorize");
        gh.searchParams.set("client_id", env.GITHUB_CLIENT_ID);
        gh.searchParams.set("redirect_uri", url.origin + "/auth/callback");
        gh.searchParams.set("state", state);
        gh.searchParams.set("scope", "read:user");
        return Response.redirect(gh.toString(), 302);
      }
      if (url.pathname === "/auth/callback") {
        const state = url.searchParams.get("state") || "", code = url.searchParams.get("code") || "";
        const ret = await env.STORE.get("state:" + state);
        if (!ret || !code) return new Response("Sign-in link expired. Please try again.", { status: 400 });
        ctx.waitUntil(env.STORE.delete("state:" + state));
        const tok = await fetch("https://github.com/login/oauth/access_token", { method: "POST", headers: { "Accept": "application/json", "Content-Type": "application/json", "User-Agent": "scienceofplacebo" },
          body: JSON.stringify({ client_id: env.GITHUB_CLIENT_ID, client_secret: env.GITHUB_CLIENT_SECRET, code, redirect_uri: url.origin + "/auth/callback" }) });
        const tj = await tok.json();
        if (!tj.access_token) return new Response("GitHub did not return a token.", { status: 502 });
        const gu = await (await fetch("https://api.github.com/user", { headers: { "Authorization": "Bearer " + tj.access_token, "User-Agent": "scienceofplacebo", "Accept": "application/vnd.github+json" } })).json();
        if (!gu.id) return new Response("Could not read your GitHub profile.", { status: 502 });
        const uid = String(gu.id);
        const u = await user(env, uid); u.login = gu.login; u.avatar = gu.avatar_url; await saveUser(env, uid, u);
        const token = rand();
        await env.STORE.put("sess:" + token, JSON.stringify({ uid, login: gu.login, avatar: gu.avatar_url }), { expirationTtl: SESSION_DAYS * 86400 });
        return new Response(null, { status: 302, headers: { "Location": ret, "Set-Cookie": sessionCookie(token, SESSION_DAYS * 86400) } });
      }
      if (url.pathname === "/auth/logout" && req.method === "POST") {
        const t = cookieOf(req, "sop_session");
        if (t) await env.STORE.delete("sess:" + t);
        return json(env, req, { ok: true }, 200, { "Set-Cookie": sessionCookie("", 0) });
      }
      if (url.pathname === "/api/picks") {
        const counts = (await env.STORE.get("counts", "json")) || {};
        const picks = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 200).map(([id, n]) => ({ id, n }));
        return json(env, req, { updated: new Date().toISOString(), picks }, 200, { "Cache-Control": "public, max-age=300" });
      }
      const s = await session(env, req);
      if (url.pathname === "/api/me") {
        if (!s) return json(env, req, { error: "not signed in" }, 401);
        const u = await user(env, s.uid);
        return json(env, req, { login: s.login, avatar: s.avatar, stars: u.stars || [] });
      }
      if (!s) return json(env, req, { error: "not signed in" }, 401);
      if (url.pathname === "/api/stars" && req.method === "PUT") {
        const body = await req.json();
        const ids = [...new Set((body.ids || []).filter(x => typeof x === "string" && x.length < 200))].slice(0, 5000);
        const u = await user(env, s.uid); const before = new Set(u.stars || []);
        const changes = {}; for (const id of ids) if (!before.has(id)) changes[id] = 1; for (const id of before) if (!ids.includes(id)) changes[id] = -1;
        u.stars = ids; await saveUser(env, s.uid, u); if (Object.keys(changes).length) await bumpCounts(env, changes);
        return json(env, req, { stars: u.stars });
      }
      if (url.pathname === "/api/star" && req.method === "POST") {
        const { id, on } = await req.json();
        if (typeof id !== "string" || id.length > 200) return json(env, req, { error: "bad id" }, 400);
        const u = await user(env, s.uid); const set = new Set(u.stars || []); const had = set.has(id);
        if (on) set.add(id); else set.delete(id);
        u.stars = [...set]; await saveUser(env, s.uid, u);
        if (had !== !!on) await bumpCounts(env, { [id]: on ? 1 : -1 });
        return json(env, req, { stars: u.stars });
      }
      return json(env, req, { error: "not found" }, 404);
    } catch (e) {
      console.error(JSON.stringify({ level: "error", path: url.pathname, message: e.message }));
      return json(env, req, { error: "server error" }, 500);
    }
  },
};
