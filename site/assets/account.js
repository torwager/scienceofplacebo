/* Community account (stage 2): GitHub sign-in through the community API, synced "My list".
   Does nothing until SOP_CONFIG.communityApi is set. */
window.SOPAccount = (function () {
  const api = (window.SOP_CONFIG || {}).communityApi || "";
  const state = { user: null, ready: false };
  const MERGED_KEY = "sop.mylist.merged";
  async function call(path, opts = {}) {
    const r = await fetch(api + path, { credentials: "include", headers: { "Content-Type": "application/json" }, ...opts });
    if (r.status === 401) return null;
    if (!r.ok) throw new Error("community API " + r.status);
    return r.json();
  }
  async function init() {
    if (!api) { state.ready = true; render(); return state; }
    try {
      const me = await call("/api/me");
      if (me) {
        state.user = me;
        // first sign-in on this browser: merge the local list into the account, then adopt the account list
        const local = [...SOP.list.ids()];
        let stars = me.stars || [];
        if (local.length && localStorage.getItem(MERGED_KEY) !== me.login) {
          const merged = [...new Set([...stars, ...local])];
          const res = await call("/api/stars", { method: "PUT", body: JSON.stringify({ ids: merged }) });
          stars = (res && res.stars) || merged;
          try { localStorage.setItem(MERGED_KEY, me.login); } catch (e) { /* ignore */ }
        }
        SOP.list._ids = new Set(stars); SOP.list.save();
        try { localStorage.setItem(MERGED_KEY, me.login); } catch (e) { /* ignore */ }
      }
    } catch (e) { console.warn("community API unavailable", e.message); }
    state.ready = true; render();
    return state;
  }
  // keep the account in sync with star clicks
  document.addEventListener("sop:star", e => { if (state.user && api) call("/api/star", { method: "POST", body: JSON.stringify({ id: e.detail.id, on: e.detail.on }) }).catch(() => {}); });
  function signIn() { location.href = api + "/auth/login?return=" + encodeURIComponent(location.href); }
  async function signOut() { try { await call("/auth/logout", { method: "POST" }); } catch (e) { /* ignore */ } state.user = null; try { localStorage.removeItem(MERGED_KEY); } catch (e) { /* ignore */ } render(); }
  function render() {
    document.querySelectorAll("[data-account]").forEach(el => {
      if (!api) { el.innerHTML = el.dataset.account === "full" ? '<p class="muted small" style="margin:0">Accounts are not open yet. Your list is saved in this browser; use Export on the My list page to move it.</p>' : ""; return; }
      if (state.user) el.innerHTML = `<span class="small">Signed in as <b>${SOP.esc(state.user.login)}</b> · your list is synced to your account.</span> <button class="btn link" data-signout>Sign out</button>`;
      else el.innerHTML = `<button class="btn primary" data-signin>Sign in with GitHub</button> <span class="small muted">Saves your list across devices and lets your stars count toward the community picks.</span>`;
    });
  }
  document.addEventListener("click", e => { if (e.target.closest("[data-signin]")) signIn(); if (e.target.closest("[data-signout]")) signOut(); });
  return { state, init, signIn, signOut, api, call };
})();
document.addEventListener("DOMContentLoaded", () => { if (window.SOP) SOPAccount.init(); });
