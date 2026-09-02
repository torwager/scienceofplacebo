"""One-time: fetch all PubMed candidates for the historical backfill into work/candidates_pubmed.json."""
import json, sys
sys.path.insert(0, ".")
from pipeline import pubmed, config

ids = pubmed.search(config.PUBMED_QUERY)
print("candidate PMIDs", len(ids), flush=True)
seed = json.load(open(config.SEEDS_DIR / "jips_seed.json"))["pmids"]
allids = sorted(set(ids) | set(seed), key=int)
print("with JIPS seeds", len(allids), flush=True)
out = {}
for rec in pubmed.fetch(allids, progress=lambda i, n: print(f"{i}/{n}", flush=True) if i % 2000 < 200 else None):
    rec["sources"] = (["pubmed_query"] if rec["pmid"] in set(ids) else []) + (["jips"] if rec["pmid"] in seed else [])
    out[rec["pmid"]] = rec
json.dump(out, open("work/candidates_pubmed.json", "w"))
print("saved", len(out), flush=True)
