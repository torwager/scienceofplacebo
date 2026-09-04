"""Recall audit: the most-cited placebo/nocebo papers in OpenAlex that are neither in the database nor ever screened.
Writes work/audit_missing.json (candidate records in our shape) for classification."""
import json, sys, time, requests
sys.path.insert(0, ".")
from pipeline import db, config, openalex

papers = db.load_all(); screened = db.load_screened()
by_pmid, by_title = db.index_by_alt_ids(papers)
cands = json.load(open("work/candidates_pubmed.json"))
cand_dois = {(c.get("doi") or "").lower() for c in cands.values()}
seen_dois = {r["doi"].lower() for r in papers.values() if r.get("doi")} | {k[4:] for k in screened if k.startswith("doi:")}
H = {"User-Agent": f"{config.TOOL_NAME} (mailto:{config.CONTACT_EMAIL})"}
QUERIES = ['"placebo effect"|"placebo effects"|"placebo analgesia"|"placebo response"|"placebo responses"|nocebo|"open-label placebo"|"placebo mechanism"',
           '"placebo"|"sham"']  # second: broad, only the very top by citations
missing, checked = [], 0
for qi, q in enumerate(QUERIES):
    pages = 4 if qi == 0 else 2
    cursor = "*"
    for _ in range(pages):
        for attempt in range(8):
            r = requests.get("https://api.openalex.org/works", headers=H, timeout=90, params={
            "filter": f"title_and_abstract.search:{q},type:article|review", "sort": "cited_by_count:desc", "per-page": 200, "cursor": cursor,
            "mailto": config.CONTACT_EMAIL, "select": "id,doi,title,publication_year,cited_by_count,ids,primary_location,authorships,abstract_inverted_index,publication_date,type,open_access,best_oa_location,keywords,language"})
            if r.status_code == 429:
                time.sleep(45 * (attempt + 1)); continue
            break
        r.raise_for_status(); j = r.json()
        for w in j.get("results", []):
            checked += 1
            rec = openalex.to_record(w)
            doi = (rec.get("doi") or "").lower(); pm = rec.get("pmid")
            title_l = (rec.get("title") or "").lower()
            if not any(k in title_l for k in ("placebo", "nocebo", "sham", "expectan", "expectation", "conditioned", "suggestion")):
                continue  # keep the audit to papers whose title signals the topic
            if (doi and (doi in seen_dois or doi in cand_dois)) or (pm and (pm in by_pmid or pm in cands)) or db.norm_title(rec["title"]) in by_title or db.record_id(rec) in screened:
                continue
            missing.append({**rec, "cited_by_count": w.get("cited_by_count"), "sources": ["recall_audit"]})
        cursor = (j.get("meta") or {}).get("next_cursor")
        if not cursor: break
        time.sleep(0.3)
uniq = {}
for m in missing: uniq.setdefault(m.get("doi") or m["title"], m)
missing = sorted(uniq.values(), key=lambda m: -(m.get("cited_by_count") or 0))
json.dump(missing, open("work/audit_missing.json", "w"), indent=1)
print(f"checked {checked} highly cited works; {len(missing)} never seen by the pipeline")
for m in missing[:25]:
    print(f"  {m.get('cited_by_count'):>6}  {m.get('year')}  {m['title'][:90]}  {m.get('doi') or ''}")
