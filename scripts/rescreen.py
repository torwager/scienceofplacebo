"""Re-screen every paper currently in the database (core/adjacent/review) with the current prompt version.
Writes work/rescreen.jsonl (resumable); apply with scripts/apply_rescreen.py."""
import json, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, ".")
from pipeline import db, classify
from pipeline.llm_client import PROMPT_VERSION

WORKERS = int(sys.argv[1]) if len(sys.argv) > 1 else 16
OUT = "work/rescreen.jsonl"
papers = db.load_all()
done = set()
try:
    for line in open(OUT):
        j = json.loads(line)
        if j.get("prompt_version") == PROMPT_VERSION and j["scope"] != "error":
            done.add(j["id"])
except FileNotFoundError:
    pass
todo = [r for r in papers.values() if r["id"] not in done]
todo.sort(key=lambda r: -(r.get("year") or 0))
print(f"{len(papers)} papers, {len(done)} done, {len(todo)} to re-screen with prompt {PROMPT_VERSION}", flush=True)
lock = threading.Lock(); fh = open(OUT, "a"); stats = {"n": 0, "cost": 0.0, "t0": time.time(), "changed": 0}


def work(r):
    for attempt in range(8):
        try:
            cls, scope = classify.classify_record(r)
            return {"id": r["id"], "scope": scope, "prompt_version": PROMPT_VERSION, "classification": cls, "old_scope": r.get("scope")}
        except Exception as e:  # noqa: BLE001
            if attempt == 7:
                return {"id": r["id"], "scope": "error", "prompt_version": PROMPT_VERSION, "error": str(e)[:200]}
            time.sleep((20 if "429" in str(e) else 5) * (attempt + 1))


with ThreadPoolExecutor(WORKERS) as ex:
    for f in as_completed([ex.submit(work, r) for r in todo]):
        res = f.result()
        with lock:
            fh.write(json.dumps(res, ensure_ascii=False) + "\n"); fh.flush()
            stats["n"] += 1; stats["cost"] += (res.get("classification") or {}).get("usage", {}).get("cost_usd", 0)
            if res["scope"] != res.get("old_scope"): stats["changed"] += 1
            if stats["n"] % 200 == 0:
                el = time.time() - stats["t0"]; print(f"{stats['n']}/{len(todo)} changed={stats['changed']} cost=${stats['cost']:.2f} rate={stats['n']/el*3600:.0f}/h", flush=True)
print("RESCREEN_DONE", stats, flush=True)
