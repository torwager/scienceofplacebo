"""One-time: classify all backfill candidates (work/candidates_pubmed.json) -> work/classified.jsonl (resumable).
Order: JIPS-seeded papers first, then newest to oldest. Runs N threads against the LLM provider.
"""
import json, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, ".")
from pipeline import classify

WORKERS = int(sys.argv[1]) if len(sys.argv) > 1 else 12
MIN_YEAR = int(sys.argv[2]) if len(sys.argv) > 2 else 0
cands = json.load(open("work/candidates_pubmed.json"))
done = set()
out_path = "work/classified.jsonl"
try:
    for line in open(out_path):
        j = json.loads(line)
        if j["scope"] != "error":
            done.add(j["pmid"])
except FileNotFoundError:
    pass
todo = [r for p, r in cands.items() if p not in done and (r.get("year") or 0) >= MIN_YEAR]
todo.sort(key=lambda r: ("jips" not in r.get("sources", []), -(r.get("year") or 0)))
print(f"{len(cands)} candidates, {len(done)} done, {len(todo)} to do", flush=True)
lock = threading.Lock()
fh = open(out_path, "a")
stats = {"n": 0, "cost": 0.0, "pre": 0, "err": 0, "t0": time.time()}


def work(rec):
    reason = classify.prefilter(rec)
    if reason:
        return {"pmid": rec["pmid"], "scope": "exclude", "prefilter": reason}
    for attempt in range(8):
        try:
            cls, scope = classify.classify_record(rec)
            return {"pmid": rec["pmid"], "scope": scope, "classification": cls}
        except Exception as e:  # noqa: BLE001
            if attempt == 7:
                return {"pmid": rec["pmid"], "scope": "error", "error": str(e)[:300]}
            time.sleep((20 if "429" in str(e) else 5) * (attempt + 1))


with ThreadPoolExecutor(WORKERS) as ex:
    futs = [ex.submit(work, r) for r in todo]
    for f in as_completed(futs):
        r = f.result()
        with lock:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n"); fh.flush()
            stats["n"] += 1
            if "prefilter" in r: stats["pre"] += 1
            if r["scope"] == "error": stats["err"] += 1
            stats["cost"] += (r.get("classification") or {}).get("usage", {}).get("cost_usd", 0)
            if stats["n"] % 100 == 0:
                el = time.time() - stats["t0"]
                print(f"{stats['n']}/{len(todo)} cost=${stats['cost']:.2f} prefiltered={stats['pre']} errors={stats['err']} {el/60:.1f}min rate={stats['n']/el*3600:.0f}/h", flush=True)
print("DONE", stats, flush=True)
