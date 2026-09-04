"""Database integrity pass: correct DOIs/PMCIDs against PubMed, dedupe by PMID, re-key, drop records screened as excluded.
Safe to run any time nothing else is writing data/."""
import json, sys, collections
sys.path.insert(0, ".")
from pipeline import db, pubmed

papers = db.load_all(); screened = db.load_screened()
cache = json.load(open("work/candidates_pubmed.json")) if __import__("os").path.exists("work/candidates_pubmed.json") else {}
need = sorted({r["pmid"] for r in papers.values() if r.get("pmid") and r["pmid"] not in cache})
print("fetching", len(need), "PMIDs not in the local cache", flush=True)
for rec in pubmed.fetch(need):
    cache[rec["pmid"]] = rec
fixed = 0; new_papers = {}; by_pmid = {}
for old_id, r in sorted(papers.items(), key=lambda kv: kv[0]):
    c = cache.get(r.get("pmid"))
    if c:
        if (r.get("doi") or None) != (c.get("doi") or None):
            fixed += 1
            r["doi"] = c.get("doi"); r["pmcid"] = c.get("pmcid")
            for k in ("openalex_checked", "openalex_mismatch", "cited_by_count", "oa_pdf_url", "oa_status", "openalex_id", "landing_url"):
                r.pop(k, None)
        if db.norm_title(c["title"]) != db.norm_title(r["title"]) or (c.get("abstract") or "") != (r.get("abstract") or ""):
            for f in ("title", "abstract", "authors", "journal", "journal_abbrev", "year", "date", "mesh", "keywords", "pub_types", "language"):
                r[f] = c.get(f)
    new_id = db.record_id(r); r["id"] = new_id
    if r.get("pmid") and r["pmid"] in by_pmid:
        keep = new_papers[by_pmid[r["pmid"]]]
        db.merge(keep, r)  # duplicate PMID: fold into the first one
        if old_id in screened and new_id != old_id: screened[new_id] = screened.pop(old_id)
        continue
    if old_id in screened and new_id != old_id: screened[new_id] = screened.pop(old_id)
    new_papers[new_id] = r
    if r.get("pmid"): by_pmid[r["pmid"]] = new_id
dropped = [rid for rid in new_papers if screened.get(rid, {}).get("scope") == "exclude"]
for rid in dropped: del new_papers[rid]
db.save_all(new_papers); db.save_screened(screened)
print(f"DOIs corrected {fixed}; duplicates folded {len(papers) - len(new_papers) - len(dropped)}; excluded dropped {len(dropped)}; papers {len(new_papers)}",
      collections.Counter(r["scope"] for r in new_papers.values()), flush=True)
