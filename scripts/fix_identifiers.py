"""Re-derive DOI/PMCID for every paper with a PMID (after the parser fix) and re-key records whose id changed.
Also patches work/candidates_pubmed.json so later scripts use correct DOIs."""
import json, sys
sys.path.insert(0, ".")
from pipeline import db, pubmed

papers = db.load_all(); screened = db.load_screened()
pmids = sorted({r["pmid"] for r in papers.values() if r.get("pmid")})
print("refetching", len(pmids), flush=True)
fresh = {}
for rec in pubmed.fetch(pmids, progress=lambda i, n: print(f"{i}/{n}", flush=True) if i % 2000 < 200 else None):
    fresh[rec["pmid"]] = rec
changed = 0; rekeyed = 0
new_papers = {}
for old_id, r in papers.items():
    f = fresh.get(r.get("pmid"))
    if f:
        if (r.get("doi") or None) != (f.get("doi") or None) or (r.get("pmcid") or None) != (f.get("pmcid") or None):
            changed += 1
        r["doi"] = f.get("doi"); r["pmcid"] = f.get("pmcid")
        for k in ("openalex_checked", "openalex_mismatch", "cited_by_count", "oa_pdf_url", "oa_status", "openalex_id", "landing_url"):
            r.pop(k, None)  # will be re-enriched against the correct DOI
    new_id = db.record_id(r)
    if new_id != old_id:
        rekeyed += 1
        r["id"] = new_id
        if old_id in screened:
            screened[new_id] = screened.pop(old_id)
    new_papers[new_id] = r
db.save_all(new_papers); db.save_screened(screened)
print(f"identifiers changed: {changed}; records re-keyed: {rekeyed}; papers: {len(new_papers)}", flush=True)
# patch the local candidate cache too
try:
    cands = json.load(open("work/candidates_pubmed.json"))
    n = 0
    for pmid, rec in cands.items():
        f = fresh.get(pmid)
        if f:
            rec["doi"] = f.get("doi"); rec["pmcid"] = f.get("pmcid"); n += 1
    json.dump(cands, open("work/candidates_pubmed.json", "w")); print("candidates patched", n)
except FileNotFoundError:
    pass
