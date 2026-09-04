"""Classify the never-seen papers found by audit_recall.py and merge included ones into the database."""
import json, sys, time
sys.path.insert(0, ".")
from pipeline import db, classify, ingest
try:
    missing = json.load(open("work/audit_missing.json"))
except FileNotFoundError:
    print("no audit file"); sys.exit(0)
papers = db.load_all(); screened = db.load_screened(); by_pmid, by_title = db.index_by_alt_ids(papers)
stats = {"n": 0, "core": 0, "adjacent": 0, "review": 0, "exclude": 0, "skip": 0}
for rec in missing:
    rid = db.record_id(rec)
    if rid in screened or db.find_existing(rec, papers, by_pmid, by_title) or classify.prefilter(rec):
        stats["skip"] += 1; continue
    try:
        cls, scope = classify.classify_record(rec)
    except Exception as e:  # noqa: BLE001
        print("error", rid, str(e)[:100]); continue
    stats["n"] += 1; stats[scope] += 1
    screened[rid] = {"scope": scope, "pmid": rec.get("pmid"), "date": time.strftime("%Y-%m-%d"), "reason": cls["screening"].get("exclusion_reason"), "via": "recall_audit"}
    if scope in ("core", "adjacent", "review"):
        ingest.upsert(papers, ingest.make_record(rec, cls, scope, date_added=(rec.get("date") or time.strftime("%Y-%m-%d"))[:10]), by_pmid, by_title)
db.save_all(papers); db.save_screened(screened); print("audit classified", stats)
