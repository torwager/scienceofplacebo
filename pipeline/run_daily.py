"""Daily worker: discover -> dedup -> prefilter -> enrich -> classify -> merge -> build site.

Usage: python -m pipeline.run_daily [--days N] [--max-llm N] [--dry-run]
Each discovery source is isolated so one failing API does not stop the others. Every candidate ever screened
is remembered in data/screened.json, so re-running with overlapping windows is safe.
"""
import argparse
import json
import sys
import time
import traceback
from datetime import date, timedelta
from . import config, db, pubmed, europepmc, openalex, classify, ingest, build_site

RUNS = config.DATA / "runs"


def discover(days):
    cands = {}
    since = (date.today() - timedelta(days=days)).strftime("%Y/%m/%d")
    since_iso = (date.today() - timedelta(days=days)).isoformat()
    report = {}
    # 1. PubMed core query, Entrez-date window (edat: when the record was added)
    try:
        ids = pubmed.search(config.PUBMED_QUERY, mindate=since, datetype="edat")
        broad = pubmed.search(config.PUBMED_BROAD, mindate=since, datetype="edat")
        for rec in pubmed.fetch(list(dict.fromkeys(ids + broad))):
            rec["sources"] = ["pubmed_query"] if rec["pmid"] in set(ids) else ["pubmed_broad"]
            cands[db.record_id(rec)] = rec
        report["pubmed"] = {"core": len(ids), "broad": len(broad)}
    except Exception as e:  # noqa: BLE001
        report["pubmed"] = {"error": str(e)[:300]}
        traceback.print_exc()
    # 2. Europe PMC preprints
    try:
        hits = europepmc.search(config.EUROPEPMC_QUERY, from_date=since_iso, max_records=500)
        n = 0
        for h in hits:
            rec = europepmc.to_record(h)
            rec["sources"] = ["europepmc_preprint"]
            rid = db.record_id(rec)
            if rid not in cands:
                cands[rid] = rec
                n += 1
        report["europepmc"] = {"hits": len(hits), "new": n}
    except Exception as e:  # noqa: BLE001
        report["europepmc"] = {"error": str(e)[:300]}
    # 3. OpenAlex (journals outside PubMed + preprints), rolling 60-day publication window
    try:
        n = 0
        works = openalex.search_recent((date.today() - timedelta(days=max(days, 60))).isoformat())
        for w in works:
            rec = openalex.to_record(w)
            rid = db.record_id(rec)
            if rid not in cands and rec.get("title"):
                cands[rid] = rec
                n += 1
        report["openalex"] = {"hits": len(works), "new": n}
    except Exception as e:  # noqa: BLE001
        report["openalex"] = {"error": str(e)[:300]}
    return cands, report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5, help="lookback window (overlap is safe)")
    ap.add_argument("--max-llm", type=int, default=300)
    ap.add_argument("--dry-run", action="store_true", help="discover and classify but do not write data/")
    args = ap.parse_args(argv)
    t0 = time.time()
    today = date.today().isoformat()
    papers = db.load_all()
    screened = db.load_screened()
    by_pmid, by_title = db.index_by_alt_ids(papers)
    cands, report = discover(args.days)
    # dedup against everything we have seen
    new = {}
    for rid, rec in cands.items():
        if rid in screened or rid in papers or db.find_existing(rec, papers, by_pmid, by_title):
            continue
        if rec.get("pmid") and any(s.get("pmid") == rec["pmid"] for s in ()):  # placeholder for pmid-only ledger
            continue
        new[rid] = rec
    print(f"discovered {len(cands)}, new {len(new)}; sources={json.dumps(report)}", flush=True)
    stats = {"date": today, "discovered": len(cands), "new": len(new), "sources": report, "prefiltered": 0, "classified": 0,
             "core": 0, "adjacent": 0, "review": 0, "exclude": 0, "errors": 0, "cost_usd": 0.0}
    n_llm = 0
    for rid, rec in new.items():
        reason = classify.prefilter(rec)
        if reason:
            screened[rid] = {"scope": "exclude", "pmid": rec.get("pmid"), "date": today, "reason": reason}
            stats["prefiltered"] += 1
            continue
        if n_llm >= args.max_llm:
            break  # leave the rest for tomorrow (still un-screened, so they will be picked up by the overlap window)
        try:
            openalex.enrich(rec)
        except Exception:  # noqa: BLE001
            pass
        try:
            cls, scope = classify.classify_record(rec)
            n_llm += 1
        except Exception as e:  # noqa: BLE001
            stats["errors"] += 1
            print("classify error", rid, str(e)[:200], flush=True)
            continue
        stats["classified"] += 1
        stats[scope] += 1
        stats["cost_usd"] += cls.get("usage", {}).get("cost_usd", 0)
        screened[rid] = {"scope": scope, "pmid": rec.get("pmid"), "date": today, "reason": cls["screening"].get("exclusion_reason")}
        if scope in ("core", "adjacent", "review"):
            ingest.upsert(papers, ingest.make_record(rec, cls, scope, date_added=today), by_pmid, by_title)
    stats["seconds"] = round(time.time() - t0)
    print(json.dumps(stats), flush=True)
    if args.dry_run:
        return 0
    db.save_all(papers)
    db.save_screened(screened)
    RUNS.mkdir(parents=True, exist_ok=True)
    json.dump(stats, open(RUNS / f"{today}.json", "w"), indent=1)
    build_site.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
