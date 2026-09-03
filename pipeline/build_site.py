"""Build the static site's data files from data/ into site/data/.

Outputs (all consumed by site/*.html JS):
  site/data/index.json        slim record per core/adjacent paper (drives feed, filters, browse)
  site/data/papers/YYYY.json  full records (abstract, authors, classification) per year
  site/data/text/YYYY.json    id + title + abstract + keywords for client-side full-text search
  site/data/taxonomy.json     chip labels/colors
  site/data/stats.json        counts, last-updated
  site/data/events.json, resources.json   copied from data/
  site/feed.xml               RSS of the latest core papers
"""
import json
import shutil
import time
from xml.sax.saxutils import escape
from . import config, db, ingest

SITE_URL = "https://scienceofplacebo.org"


KIND_OF = {"empirical_primary": "empirical", "secondary_analysis": "empirical", "case_report": "empirical", "methods_measurement": "empirical",
           "meta_analysis": "review", "systematic_review": "review", "narrative_review": "review",
           "theory_commentary": "theory", "editorial_letter": "theory", "protocol": "theory"}


def derive_kind(tags):
    k = KIND_OF.get(tags.get("article_type"))
    if k:
        tags["kind"] = k
    return tags


def slim(rec):
    cls = rec.get("classification") or {}
    tags = dict(cls.get("tags") or {})
    authors = rec.get("authors") or []
    first = authors[0] if authors else ""
    if isinstance(first, dict):
        first = first.get("family", "")
    a = first + (" et al." if len(authors) > 2 else (" & " + (authors[1] if isinstance(authors[1], str) else authors[1].get("family", "")) if len(authors) == 2 else ""))
    return {
        "id": rec["id"],
        "t": rec.get("title", ""),
        "a": a,
        "y": rec.get("year"),
        "d": rec.get("date") or "",
        "j": rec.get("journal_abbrev") or rec.get("journal") or "",
        "u": ingest.publisher_url(rec),
        "pmid": rec.get("pmid"),
        "doi": rec.get("doi"),
        "s": cls.get("summary") or "",
        "sc": rec.get("scope"),
        "oa": bool(rec.get("oa_pdf_url")),
        "pdf": bool((rec.get("private_pdf") or {}).get("available")),
        "n": cls.get("sample_size"),
        "c": (cls.get("screening") or {}).get("confidence"),
        "cit": rec.get("cited_by_count"),
        "added": rec.get("date_added") or "",
        "tags": {k: (v if isinstance(v, list) else [v]) for k, v in tags.items() if v and v not in ("not_applicable", ["not_applicable"], "none_reported", ["none_reported"])},
        "kw": (cls.get("free_keywords") or [])[:8],
        "au": [a if isinstance(a, str) else (a.get("family", "") + " " + "".join(w[0] for w in (a.get("given") or "").split())).strip() for a in authors][:40],
    }


def rss(items):
    now = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0"><channel>',
           f"<title>Science of Placebo: new papers</title><link>{SITE_URL}/</link>",
           "<description>Newly published peer-reviewed studies of placebo and nocebo effects and responses.</description>",
           f"<lastBuildDate>{now}</lastBuildDate>"]
    for r in items:
        link = r["u"] or f"{SITE_URL}/paper.html?id={r['id']}"
        out.append(f"<item><title>{escape(r['t'])}</title><link>{escape(link)}</link><guid isPermaLink=\"false\">{escape(r['id'])}</guid>"
                   f"<description>{escape((r['a'] + ' (' + str(r['y']) + '). ' + r['j'] + '. ' + r['s']).strip())}</description></item>")
    out.append("</channel></rss>")
    return "\n".join(out)


def bibliometrics(visible, index):
    """Aggregate counts for the bibliometrics page. Only core+adjacent (visible) papers."""
    from collections import Counter, defaultdict
    by_year = Counter(); kind_year = defaultdict(Counter); focus_year = defaultdict(Counter)
    tag_counts = defaultdict(Counter); journals = Counter(); first_authors = Counter(); last_authors = Counter(); all_authors = Counter()
    modality_year = defaultdict(Counter); design_year = defaultdict(Counter); pop_year = defaultdict(Counter); cond_year = defaultdict(Counter)
    n_abstract = 0; oa = Counter(); jips = 0; cites = []
    for r, s in zip(visible, index):
        y = r.get("year")
        if not y:
            continue
        by_year[y] += 1
        tags = s["tags"]
        for ax, vals in tags.items():
            for v in vals:
                tag_counts[ax][v] += 1
        kind = KIND_OF.get((tags.get("article_type") or [None])[0])
        if kind:
            kind_year[y][kind] += 1
        for f in tags.get("study_focus", []):
            focus_year[y][f] += 1
        for m in tags.get("outcome_measures", []):
            modality_year[y][m] += 1
        for d in tags.get("design", []):
            design_year[y][d] += 1
        for pp in tags.get("population", []):
            pop_year[y][pp] += 1
        for c in tags.get("condition_domain", []):
            cond_year[y][c] += 1
        j = r.get("journal_abbrev") or r.get("journal")
        if j:
            journals[j] += 1
        au = [a if isinstance(a, str) else a.get("family", "") for a in (r.get("authors") or [])]
        if au:
            first_authors[au[0]] += 1
            last_authors[au[-1]] += 1
            for a in set(au):
                all_authors[a] += 1
        if r.get("abstract"):
            n_abstract += 1
        oa[r.get("oa_status") or "unknown"] += 1
        if "jips" in (r.get("sources") or []):
            jips += 1
        if r.get("cited_by_count") is not None:
            cites.append((r["cited_by_count"], s["id"], s["t"], s["a"], y, j or ""))
    cites.sort(reverse=True)
    years = sorted(by_year)
    def series(d):
        keys = sorted({k for y in d for k in d[y]}, key=lambda k: -sum(d[y][k] for y in d))
        return {"keys": keys, "rows": [[y] + [d[y][k] for k in keys] for y in years]}
    return {
        "n": len(visible), "n_with_abstract": n_abstract, "n_jips_seed": jips,
        "years": years, "per_year": [by_year[y] for y in years],
        "kind_by_year": series(kind_year), "focus_by_year": series(focus_year), "modality_by_year": series(modality_year),
        "design_by_year": series(design_year), "population_by_year": series(pop_year), "condition_by_year": series(cond_year),
        "tag_counts": {ax: c.most_common() for ax, c in tag_counts.items()},
        "top_journals": journals.most_common(30), "top_first_authors": first_authors.most_common(30),
        "top_last_authors": last_authors.most_common(30), "top_authors": all_authors.most_common(40),
        "oa_status": oa.most_common(), "most_cited": [{"cites": c, "id": i, "t": t, "a": a, "y": y, "j": j} for c, i, t, a, y, j in cites[:30]],
        "n_journals": len(journals), "n_authors": len(all_authors),
    }


def researcher_graph(visible, index, min_papers=8):
    """Nodes: authors with >= min_papers papers. Edges: co-authorship counts, and tag-profile cosine similarity (top-5 per author)."""
    import math
    from collections import Counter, defaultdict
    def name(a):
        return a if isinstance(a, str) else (a.get("family", "") + " " + "".join(w[0] for w in (a.get("given") or "").split())).strip()
    papers_of = defaultdict(list)
    for r, s in zip(visible, index):
        for a in {name(a) for a in (r.get("authors") or []) if name(a)}:
            papers_of[a].append(s)
    nodes = [a for a, ps in papers_of.items() if len(ps) >= min_papers]
    nodes.sort(key=lambda a: -len(papers_of[a]))
    nodes = nodes[:700]
    idx = {a: i for i, a in enumerate(nodes)}
    co = Counter(); shared = defaultdict(list)
    for r, s in zip(visible, index):
        au = sorted({name(a) for a in (r.get("authors") or []) if name(a) in idx})
        for i in range(len(au)):
            for j in range(i + 1, len(au)):
                co[(au[i], au[j])] += 1
                if len(shared[(au[i], au[j])]) < 6:
                    shared[(au[i], au[j])].append({"id": s["id"], "t": s["t"], "y": s["y"]})
    # tag profiles
    profiles = {}
    for a in nodes:
        c = Counter()
        for s in papers_of[a]:
            for ax, vals in s["tags"].items():
                if ax in ("kind", "species", "age_group"):
                    continue
                for v in vals:
                    c[ax + ":" + v] += 1
            for k in s.get("kw", []):
                c["kw:" + k.lower()] += 1
        n = math.sqrt(sum(v * v for v in c.values())) or 1
        profiles[a] = {k: v / n for k, v in c.items()}
    sim_edges = []
    for i, a in enumerate(nodes):
        pa = profiles[a]
        sims = []
        for b in nodes[i + 1:]:
            pb = profiles[b]
            dot = sum(v * pb.get(k, 0) for k, v in pa.items() if k in pb)
            if dot > 0.25:
                sims.append((dot, b))
        sims.sort(reverse=True)
        for dot, b in sims[:6]:
            sim_edges.append({"s": idx[a], "t": idx[b], "w": round(dot, 3)})
    def top_tags(a):
        c = Counter()
        for s in papers_of[a]:
            for ax in ("condition_domain", "mechanisms", "population", "outcome_measures", "design"):
                for v in s["tags"].get(ax, []):
                    c[(ax, v)] += 1
        return [[ax, v, n] for (ax, v), n in c.most_common(8)]
    out_nodes = []
    for a in nodes:
        ps = papers_of[a]
        ys = [s["y"] for s in ps if s["y"]]
        out_nodes.append({"id": idx[a], "name": a, "n": len(ps), "y0": min(ys) if ys else None, "y1": max(ys) if ys else None,
                          "tags": top_tags(a), "papers": [{"id": s["id"], "t": s["t"], "y": s["y"]} for s in sorted(ps, key=lambda s: -(s["y"] or 0))[:5]]})
    co_edges = [{"s": idx[a], "t": idx[b], "w": n, "papers": shared[(a, b)]} for (a, b), n in co.items()]
    return {"min_papers": min_papers, "nodes": out_nodes, "coauthor": co_edges, "similarity": sim_edges}


def main():
    papers = db.load_all()
    site = config.SITE_DATA
    shutil.rmtree(site, ignore_errors=True)
    (site / "papers").mkdir(parents=True)
    (site / "text").mkdir(parents=True)
    visible = [r for r in papers.values() if r.get("scope") in ("core", "adjacent")]
    visible.sort(key=lambda r: (r.get("date") or "", r["id"]), reverse=True)
    index = [slim(r) for r in visible]
    json.dump(index, open(site / "index.json", "w"), ensure_ascii=False, separators=(",", ":"))
    by_year = {}
    for r in visible:
        by_year.setdefault(r.get("year") or 0, []).append(r)
    for y, rs in by_year.items():
        json.dump({r["id"]: r for r in rs}, open(site / "papers" / f"{y}.json", "w"), ensure_ascii=False, separators=(",", ":"))
        json.dump([{"id": r["id"], "t": r["title"], "ab": r.get("abstract") or "", "kw": " ".join((r.get("keywords") or []) + ((r.get("classification") or {}).get("free_keywords") or []))} for r in rs],
                  open(site / "text" / f"{y}.json", "w"), ensure_ascii=False, separators=(",", ":"))
    shutil.copy(config.ROOT / "pipeline" / "taxonomy.json", site / "taxonomy.json")
    for name in ("events.json", "resources.json"):
        src = config.DATA / name
        if src.exists():
            shutil.copy(src, site / name)
    review = [slim(r) for r in papers.values() if r.get("scope") == "review"]
    review.sort(key=lambda r: r["d"], reverse=True)
    json.dump(review[:500], open(site / "review_queue.json", "w"), ensure_ascii=False, separators=(",", ":"))
    years = sorted(y for y in by_year if y)
    stats = {
        "updated": time.strftime("%Y-%m-%d"),
        "n_core": sum(1 for r in visible if r["scope"] == "core"),
        "n_adjacent": sum(1 for r in visible if r["scope"] == "adjacent"),
        "n_review": len(review),
        "n_screened": len(db.load_screened()),
        "years": years,
        "shards": {str(y): len(rs) for y, rs in by_year.items()},
        "n_with_oa_pdf": sum(1 for r in visible if r.get("oa_pdf_url")),
        "n_with_private_pdf": sum(1 for r in visible if (r.get("private_pdf") or {}).get("available")),
    }
    json.dump(stats, open(site / "stats.json", "w"), indent=1)
    json.dump(bibliometrics(visible, index), open(site / "bibliometrics.json", "w"), ensure_ascii=False, separators=(",", ":"))
    json.dump(researcher_graph(visible, index), open(site / "graph.json", "w"), ensure_ascii=False, separators=(",", ":"))
    for name in ("news.json",):
        src = config.DATA / name
        if src.exists():
            shutil.copy(src, site / name)
    core = [r for r in index if r["sc"] == "core"]
    core_recent = sorted(core, key=lambda r: (r["added"], r["d"]), reverse=True)[:config.FEED_CAP]
    (config.ROOT / "site" / "feed.xml").write_text(rss(core_recent))
    print(f"site data: {len(index)} visible papers ({stats['n_core']} core), {len(by_year)} year shards, {len(review)} in review queue")


if __name__ == "__main__":
    main()
