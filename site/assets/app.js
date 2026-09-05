/* Science of Placebo — shared front-end logic (no build step). */
window.SOP = (function () {
  const state = { taxonomy: null, axes: {}, labels: {}, index: null, stats: null };

  async function getJSON(path) {
    const r = await fetch(path, { cache: "no-cache" });
    if (!r.ok) throw new Error(path + ": " + r.status);
    return r.json();
  }

  async function loadCore() {
    if (state.index) return { state };
    const [tax, index, stats] = await Promise.all([getJSON("data/taxonomy.json"), getJSON("data/index.json"), getJSON("data/stats.json")]);
    state.taxonomy = tax;
    state.index = index;
    state.stats = stats;
    for (const ax of tax.axes) {
      state.axes[ax.id] = ax;
      for (const v of ax.values) state.labels[ax.id + ":" + v.id] = v.label;
    }
    return { state };
  }

  function dark() {
    const t = document.documentElement.getAttribute("data-theme");
    if (t) return t === "dark";
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function chipColors(axisId, valueId) {
    const ax = state.axes[axisId];
    const c = (ax && ax.color) || {};
    const mode = dark() ? "dark" : "light";
    // per-value override (the findings axis is colored by value)
    const vc = ax && ax.value_colors && ax.value_colors[valueId] && ax.value_colors[valueId][mode];
    const cc = vc || c[mode] || { bg: "var(--surface-2)", fg: "var(--ink-2)" };
    return `--chip-bg:${cc.bg};--chip-fg:${cc.fg}`;
  }

  function label(axisId, valueId) {
    return state.labels[axisId + ":" + valueId] || valueId.replace(/_/g, " ");
  }

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

  // axes shown as chips on cards, in display order
  const CARD_AXES = ["study_focus", "article_type", "design", "population", "condition_domain", "outcome_measures", "effects", "moderators"];
  const FILTER_AXES = ["study_focus", "article_type", "design", "population", "condition_domain", "outcome_measures", "effects", "mechanisms", "moderators", "intervention_type", "species"];

  function chipsFor(rec, onClick, axes = CARD_AXES, max = 12) {
    const out = [];
    for (const ax of axes) {
      const vals = (rec.tags || {})[ax] || [];
      for (const v of vals) {
        if (out.length >= max) break;
        out.push(`<span class="chip${onClick ? "" : " static"}" data-axis="${ax}" data-value="${esc(v)}" style="${chipColors(ax, v)}" title="${esc(state.axes[ax] ? state.axes[ax].label : ax)}">${esc(label(ax, v))}</span>`);
      }
    }
    return out.join("");
  }

  function fmtDate(d) {
    if (!d) return "";
    const [y, m, day] = d.split("-");
    const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][(+m || 1) - 1];
    return day && day !== "01" ? `${+day} ${mon} ${y}` : `${mon} ${y}`;
  }

  // ---- My list: starred papers, kept in this browser (stage 1); an account will sync it later (stage 2)
  const LIST_KEY = "sop.mylist.v1";
  const list = {
    _ids: null,
    ids() { if (this._ids) return this._ids; try { this._ids = new Set(JSON.parse(localStorage.getItem(LIST_KEY) || "[]")); } catch (e) { this._ids = new Set(); } return this._ids; },
    has(id) { return this.ids().has(id); },
    size() { return this.ids().size; },
    save() { try { localStorage.setItem(LIST_KEY, JSON.stringify([...this.ids()])); } catch (e) { /* storage unavailable */ } document.dispatchEvent(new CustomEvent("sop:list", { detail: { size: this.size() } })); },
    toggle(id) { const s = this.ids(); if (s.has(id)) s.delete(id); else s.add(id); this.save(); return s.has(id); },
    add(ids) { const s = this.ids(); for (const id of ids) s.add(id); this.save(); },
    clear() { this._ids = new Set(); this.save(); },
    export() { return JSON.stringify({ site: "scienceofplacebo.org", exported: new Date().toISOString().slice(0, 10), ids: [...this.ids()] }, null, 1); },
  };
  function starBtn(id) {
    const on = list.has(id);
    return `<button class="star${on ? " on" : ""}" data-star="${esc(id)}" aria-pressed="${on}" title="${on ? "Remove from my list" : "Add to my list"}">${on ? "★" : "☆"}</button>`;
  }
  function bindStars(container) {
    container.addEventListener("click", e => {
      const b = e.target.closest("[data-star]"); if (!b) return;
      e.preventDefault(); e.stopPropagation();
      const on = list.toggle(b.dataset.star);
      document.dispatchEvent(new CustomEvent("sop:star", { detail: { id: b.dataset.star, on } }));
      document.querySelectorAll(`[data-star="${CSS.escape(b.dataset.star)}"]`).forEach(x => { x.classList.toggle("on", on); x.setAttribute("aria-pressed", on); x.textContent = on ? "★" : "☆"; x.title = on ? "Remove from my list" : "Add to my list"; });
    });
  }
  function updateListBadge() { document.querySelectorAll(".nav a[href='mylist.html']").forEach(a => { const n = list.size(); a.innerHTML = `My list${n ? ` <span class="navcount">${n}</span>` : ""}`; }); }
  document.addEventListener("sop:list", updateListBadge);

  function paperCard(r, opts = {}) {
    const isNew = opts.newSince && r.added >= opts.newSince;
    const links = [];
    if (r.u) links.push(`<a href="${esc(r.u)}" target="_blank" rel="noopener">Publisher ↗</a>`);
    if (r.pmid) links.push(`<a href="https://pubmed.ncbi.nlm.nih.gov/${esc(r.pmid)}/" target="_blank" rel="noopener">PubMed</a>`);
    links.push(`<a href="paper.html?id=${encodeURIComponent(r.id)}">Details &amp; discussion</a>`);
    return `<article class="paper" data-id="${esc(r.id)}">
      <div class="title">${starBtn(r.id)}<a href="paper.html?id=${encodeURIComponent(r.id)}">${esc(r.t)}</a></div>
      <div class="meta"><span>${esc(r.a)}</span><span>${esc(r.j)}</span><span class="date">${fmtDate(r.d) || r.y || ""}</span>
        ${isNew ? '<span class="badge new">new</span>' : ""}${r.sc === "adjacent" ? '<span class="badge adjacent" title="Placebo-related but not a study of placebo/nocebo effects or responses (e.g., attitudes, ethics, methodology)">adjacent</span>' : ""}${r.oa ? '<span class="badge oa" title="Open-access full text available">OA</span>' : ""}${r.to ? '<span class="badge" title="No abstract exists for this record; included and tagged from the title alone">title only</span>' : ""}</div>
      ${r.s ? `<div class="summary">${esc(r.s)}</div>` : ""}
      <div class="chips">${chipsFor(r, true)}</div>
      <div class="links">${links.join("")}</div>
    </article>`;
  }

  // ---- filter model: {axis: Set(values)}; a paper matches if, for each axis with selections, it has ANY selected value
  function matches(r, filters) {
    for (const ax in filters) {
      const sel = filters[ax];
      if (!sel.size) continue;
      const vals = (r.tags || {})[ax] || [];
      let hit = false;
      for (const v of vals) if (sel.has(v)) { hit = true; break; }
      if (!hit) return false;
    }
    return true;
  }

  function countValues(recs, axis) {
    const counts = {};
    for (const r of recs) for (const v of ((r.tags || {})[axis] || [])) counts[v] = (counts[v] || 0) + 1;
    return counts;
  }

  function renderFilters(container, recs, filters, onChange, axes = FILTER_AXES) {
    const parts = [];
    for (const ax of axes) {
      const def = state.axes[ax];
      if (!def) continue;
      const counts = countValues(recs, ax);
      const vals = def.values.filter(v => counts[v.id] || (filters[ax] && filters[ax].has(v.id)));
      if (!vals.length) continue;
      const open = filters[ax] && filters[ax].size ? " open" : (["study_focus", "design", "population"].includes(ax) ? " open" : "");
      const mode = dark() ? "dark" : "light";
      const axColor = ((def.color || {})[mode] || {}).fg || "var(--ink-3)";
      parts.push(`<details${open} style="--ax:${axColor}"><summary>${esc(def.label)}<span class="cnt">${vals.length}</span></summary><div class="chipset">` +
        vals.sort((a, b) => (counts[b.id] || 0) - (counts[a.id] || 0)).map(v => {
          const on = filters[ax] && filters[ax].has(v.id);
          return `<span class="chip${on ? " on" : ""}" role="button" tabindex="0" data-axis="${ax}" data-value="${esc(v.id)}" style="${chipColors(ax, v.id)}" title="${esc(v.def || "")}">${esc(v.label)} <span class="muted tnum">${counts[v.id] || 0}</span></span>`;
        }).join("") + `</div></details>`);
    }
    container.innerHTML = parts.join("");
    container.onclick = e => {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      toggle(filters, chip.dataset.axis, chip.dataset.value);
      onChange();
    };
    container.onkeydown = e => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const chip = e.target.closest(".chip");
      if (!chip) return;
      e.preventDefault();
      toggle(filters, chip.dataset.axis, chip.dataset.value);
      onChange();
    };
  }

  function toggle(filters, ax, v) {
    filters[ax] = filters[ax] || new Set();
    if (filters[ax].has(v)) filters[ax].delete(v); else filters[ax].add(v);
  }

  function activeChips(filters) {
    const out = [];
    for (const ax in filters) for (const v of filters[ax]) out.push(`<span class="chip on" data-axis="${ax}" data-value="${esc(v)}" style="${chipColors(ax, v)}">${esc(label(ax, v))} <span class="x">×</span></span>`);
    return out.join("");
  }

  function filtersToQuery(filters, extra = {}) {
    const p = new URLSearchParams();
    for (const ax in filters) if (filters[ax].size) p.set(ax, [...filters[ax]].join(","));
    for (const k in extra) if (extra[k]) p.set(k, extra[k]);
    const s = p.toString();
    history.replaceState(null, "", location.pathname + (s ? "?" + s : ""));
  }

  function filtersFromQuery() {
    const p = new URLSearchParams(location.search);
    const f = {};
    for (const [k, v] of p) if (state.axes[k]) f[k] = new Set(v.split(",").filter(Boolean));
    return { filters: f, params: p };
  }

  function bindCardChips(container, filters, onChange) {
    container.addEventListener("click", e => {
      const chip = e.target.closest(".paper .chip");
      if (!chip) return;
      toggle(filters, chip.dataset.axis, chip.dataset.value);
      onChange();
    });
  }

  // ---- export to reference managers (BibTeX, RIS, DOI list, CSV). Works from the slim index records.
  function bibKey(r) { const sur = (r.au && r.au[0] ? r.au[0].split(" ")[0] : "anon").replace(/[^A-Za-z]/g, "").toLowerCase(); const w = (r.t || "").replace(/[^A-Za-z ]/g, "").split(" ").filter(x => x.length > 3)[0] || "paper"; return `${sur}${r.y || ""}${w.toLowerCase()}`; }
  function authorsFull(r) { return (r.au || []).map(a => { const p = a.split(" "); return p.length > 1 ? `${p.slice(0, -1).join(" ")}, ${p[p.length - 1].split("").join(". ")}.` : a; }); }
  function toBibtex(recs) {
    const esc = t => String(t || "").replace(/[{}]/g, "");
    return recs.map(r => `@article{${bibKey(r)},\n  title = {${esc(r.t)}},\n  author = {${authorsFull(r).join(" and ")}},\n  journal = {${esc(r.j)}},\n  year = {${r.y || ""}},${r.doi ? `\n  doi = {${r.doi}},` : ""}${r.pmid ? `\n  pmid = {${r.pmid}},` : ""}${r.u ? `\n  url = {${r.u}},` : ""}\n  note = {From Science of Placebo, scienceofplacebo.org}\n}`).join("\n\n");
  }
  function toRis(recs) {
    return recs.map(r => ["TY  - JOUR", `TI  - ${r.t}`, ...authorsFull(r).map(a => `AU  - ${a}`), `JO  - ${r.j || ""}`, `PY  - ${r.y || ""}`, r.d ? `DA  - ${r.d.replace(/-/g, "/")}` : null, r.doi ? `DO  - ${r.doi}` : null, r.pmid ? `AN  - ${r.pmid}` : null, r.u ? `UR  - ${r.u}` : null, r.s ? `AB  - ${r.s}` : null, "DB  - Science of Placebo", "ER  - "].filter(Boolean).join("\n")).join("\n\n");
  }
  function toCsv(recs) {
    const q = v => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
    return ["title,authors,journal,year,doi,pmid,url,summary,tags"].concat(recs.map(r => [r.t, (r.au || []).join("; "), r.j, r.y, r.doi, r.pmid, r.u, r.s, Object.entries(r.tags || {}).map(([ax, vs]) => vs.map(v => label(ax, v)).join("|")).join("; ")].map(q).join(","))).join("\n");
  }
  function toDois(recs) { return recs.map(r => r.doi ? "https://doi.org/" + r.doi : (r.pmid ? "PMID:" + r.pmid : r.t)).join("\n"); }
  const EXPORTS = { bib: ["BibTeX (.bib): Zotero, Mendeley, Paperpile, JabRef", "text/x-bibtex", "bib", toBibtex], ris: ["RIS (.ris): EndNote, Zotero, Mendeley, Paperpile", "application/x-research-info-systems", "ris", toRis], doi: ["DOI list (.txt): paste into Zotero's identifier box or Paperpile's import", "text/plain", "txt", toDois], csv: ["CSV spreadsheet with tags", "text/csv", "csv", toCsv] };
  function exportRefs(recs, fmt, name = "scienceofplacebo") {
    const [, mime, ext, fn] = EXPORTS[fmt];
    const blob = new Blob([fn(recs)], { type: mime + ";charset=utf-8" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${name}-${new Date().toISOString().slice(0, 10)}.${ext}`; document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }
  function exportMenu(id) {
    return `<details class="exportmenu" id="${id}"><summary class="btn">Export ▾</summary><div class="menu-list" style="display:flex;position:absolute;right:0;min-width:330px">${Object.entries(EXPORTS).map(([k, v]) => `<a href="#" data-export="${k}">${esc(v[0])}</a>`).join("")}</div></details>`;
  }
  function bindExport(container, getRecs, name) {
    container.addEventListener("click", e => { const a = e.target.closest("[data-export]"); if (!a) return; e.preventDefault(); const recs = getRecs(); if (!recs.length) return; exportRefs(recs, a.dataset.export, name); const d = a.closest("details"); if (d) d.open = false; });
  }

  function nav() {
    const here = location.pathname.split("/").pop() || "index.html";
    document.querySelectorAll(".nav a").forEach(a => { if (a.getAttribute("href") === here) a.classList.add("active"); });
  }

  return { state, loadCore, getJSON, chipsFor, paperCard, matches, list, starBtn, bindStars, updateListBadge, exportRefs, exportMenu, bindExport, renderFilters, activeChips, toggle, filtersToQuery, filtersFromQuery, bindCardChips, label, esc, fmtDate, nav, chipColors, CARD_AXES, FILTER_AXES };
})();
