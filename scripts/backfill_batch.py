"""Submit pre-cutoff backfill candidates to the OpenAI Batch API (50% cost, separate rate limits).
Usage: python3 scripts/backfill_batch.py submit <max_year>   -> writes work/batch_ids.json
       python3 scripts/backfill_batch.py collect              -> appends results to work/classified.jsonl
"""
import json, sys, time
sys.path.insert(0, ".")
from pipeline import classify
from pipeline.llm_client import Classifier, load_taxonomy
from openai import OpenAI

client = OpenAI()
cmd = sys.argv[1]
out_path = "work/classified.jsonl"


def done_pmids():
    d = set()
    try:
        for line in open(out_path):
            j = json.loads(line)
            if j["scope"] != "error":
                d.add(j["pmid"])
    except FileNotFoundError:
        pass
    return d


if cmd == "submit":
    max_year = int(sys.argv[2])
    cands = json.load(open("work/candidates_pubmed.json"))
    done = done_pmids()
    todo = [r for p, r in cands.items() if p not in done and (r.get("year") or 0) < max_year]
    print("to submit", len(todo))
    clf = Classifier(provider="openai", model="gpt-5-mini", effort="low")
    pre, papers = [], []
    for r in todo:
        reason = classify.prefilter(r)
        if reason:
            pre.append({"pmid": r["pmid"], "scope": "exclude", "prefilter": reason})
        else:
            papers.append({**classify.to_llm_paper(r), "id": r["pmid"]})
    with open(out_path, "a") as fh:
        for p in pre:
            fh.write(json.dumps(p) + "\n")
    print("prefiltered", len(pre), "to LLM", len(papers))
    reqs = clf.batch_requests(papers)
    ids = []
    CH = 5000
    for i in range(0, len(reqs), CH):
        fn = f"work/batch_input_{i//CH}.jsonl"
        with open(fn, "w") as fh:
            for q in reqs[i:i+CH]:
                fh.write(json.dumps(q) + "\n")
        f = client.files.create(file=open(fn, "rb"), purpose="batch")
        for _ in range(60):  # wait until the upload is processed; batch creation otherwise fails with "cannot find file"
            fo = client.files.retrieve(f.id)
            if getattr(fo, "status", "processed") == "processed":
                break
            time.sleep(2)
        time.sleep(5)
        b = client.batches.create(input_file_id=f.id, endpoint="/v1/responses", completion_window="24h",
                                  metadata={"project": "scienceofplacebo", "chunk": str(i//CH)})
        ids.append(b.id); print("submitted", b.id, len(reqs[i:i+CH]))
        time.sleep(1)
    json.dump(ids, open("work/batch_ids.json", "w"))

elif cmd == "collect":
    ids = json.load(open("work/batch_ids.json"))
    done = done_pmids()
    tax_v = load_taxonomy()["taxonomy_version"]
    from pipeline.llm_client import PROMPT_VERSION
    n = 0
    pending = []
    with open(out_path, "a") as fh:
        for bid in ids:
            b = client.batches.retrieve(bid)
            print(bid, b.status, b.request_counts)
            if b.status != "completed":
                pending.append(bid); continue
            if not b.output_file_id:
                continue
            content = client.files.content(b.output_file_id).text
            for line in content.splitlines():
                j = json.loads(line)
                pmid = j["custom_id"]
                if pmid in done:
                    continue
                resp = j.get("response") or {}
                if resp.get("status_code") != 200:
                    fh.write(json.dumps({"pmid": pmid, "scope": "error", "error": str(j.get("error") or resp)[:300]}) + "\n"); continue
                body = resp["body"]
                text = "".join(c.get("text", "") for o in body.get("output", []) if o.get("type") == "message" for c in o.get("content", []))
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    fh.write(json.dumps({"pmid": pmid, "scope": "error", "error": "bad json"}) + "\n"); continue
                u = body.get("usage", {})
                cls = {"taxonomy_version": tax_v, "prompt_version": PROMPT_VERSION, "provider": "openai", "model": body.get("model", "gpt-5-mini"),
                       "input_mode": "title_abstract", "classified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **data,
                       "usage": {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"), "cost_usd": round((u.get("input_tokens", 0) * 0.125 + u.get("output_tokens", 0) * 1.0) / 1e6, 5), "batch": True}}
                fh.write(json.dumps({"pmid": pmid, "scope": classify.derive_scope(data), "classification": cls}, ensure_ascii=False) + "\n"); n += 1
    print("collected", n, "pending batches", pending)
