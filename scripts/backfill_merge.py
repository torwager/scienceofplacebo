"""Merge work/classified.jsonl (+ work/candidates_pubmed.json) into data/papers/*.json and data/screened.json.
Safe to re-run; only records with scope core/adjacent/review are stored as papers; every screened id is remembered.
"""
import json, sys, time
sys.path.insert(0, ".")
from pipeline import db, ingest

DATE_ADDED = sys.argv[1] if len(sys.argv) > 1 else time.strftime("%Y-%m-%d")
cands = json.load(open("work/candidates_pubmed.json"))
papers = db.load_all()
screened = db.load_screened()
by_pmid, by_title = db.index_by_alt_ids(papers)
counts = {}
for line in open("work/classified.jsonl"):
    r = json.loads(line)
    cand = cands.get(r["pmid"])
    if not cand:
        continue
    scope = r["scope"]
    counts[scope] = counts.get(scope, 0) + 1
    rid = db.record_id(cand)
    screened[rid] = {"scope": scope, "pmid": r["pmid"], "date": DATE_ADDED,
                     "reason": r.get("prefilter") or (r.get("classification") or {}).get("screening", {}).get("exclusion_reason")}
    if scope in ("core", "adjacent", "review"):
        # keep the original date_added if the paper is already there
        rec = ingest.make_record(cand, r.get("classification"), scope, date_added=(cand.get("date") or DATE_ADDED)[:10])
        ingest.upsert(papers, rec, by_pmid, by_title)
db.save_all(papers)
db.save_screened(screened)
print("scopes:", counts, "| papers in DB:", len(papers), "| screened:", len(screened))
