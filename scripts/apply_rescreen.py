"""Apply work/rescreen.jsonl to the database: update classification/scope; papers now excluded are removed from
data/papers and recorded in data/screened.json."""
import json, sys, time, collections
sys.path.insert(0, ".")
from pipeline import db
from pipeline.llm_client import PROMPT_VERSION

papers = db.load_all(); screened = db.load_screened()
rows = {}
for line in open("work/rescreen.jsonl"):
    j = json.loads(line)
    if j.get("prompt_version") == PROMPT_VERSION and j["scope"] != "error":
        rows[j["id"]] = j
moves = collections.Counter(); removed = 0
for rid, j in rows.items():
    r = papers.get(rid)
    if not r:
        continue
    moves[(r.get("scope"), j["scope"])] += 1
    r["classification"] = j["classification"]
    r["scope"] = j["scope"]
    screened[rid] = {**screened.get(rid, {}), "scope": j["scope"], "date": time.strftime("%Y-%m-%d"), "reason": j["classification"]["screening"].get("exclusion_reason"), "prompt_version": PROMPT_VERSION}
    if j["scope"] == "exclude":
        del papers[rid]; removed += 1
db.save_all(papers); db.save_screened(screened)
print("applied", len(rows), "removed", removed)
for (a, b), n in sorted(moves.items(), key=lambda kv: -kv[1]):
    print(f"  {a} -> {b}: {n}")
print("papers now", len(papers), collections.Counter(r["scope"] for r in papers.values()))
