"""Merge records that exist on origin/main but not locally (e.g., added by the daily workflow while local batch jobs ran).
Run after `git fetch`. Local records win on conflicts; remote-only papers and screened ids are added."""
import json, subprocess, sys, tempfile, os
sys.path.insert(0, ".")
from pipeline import db

def remote_json(path):
    try:
        return json.loads(subprocess.run(["git", "show", f"origin/main:{path}"], capture_output=True, text=True, check=True).stdout)
    except subprocess.CalledProcessError:
        return None

papers = db.load_all(); screened = db.load_screened()
files = subprocess.run(["git", "ls-tree", "--name-only", "origin/main", "data/papers/"], capture_output=True, text=True).stdout.split()
by_pmid, by_title = db.index_by_alt_ids(papers)
added = 0
for f in files:
    for r in remote_json(f) or []:
        if r["id"] in papers or db.find_existing(r, papers, by_pmid, by_title):
            continue
        if screened.get(r["id"], {}).get("scope") == "exclude":
            continue  # deliberately removed locally (re-screen, protocol rule); do not resurrect
        papers[r["id"]] = r; added += 1
        if r.get("pmid"): by_pmid[str(r["pmid"])] = r["id"]
        by_title[db.norm_title(r["title"])] = r["id"]
rs = remote_json("data/screened.json") or {}
added_s = 0
for k, v in rs.items():
    if k not in screened:
        screened[k] = v; added_s += 1
db.save_all(papers); db.save_screened(screened)
print(f"reconciled: +{added} papers, +{added_s} screened entries from origin/main; papers now {len(papers)}")
