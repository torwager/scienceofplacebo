"""Recall audit via Semantic Scholar bulk search (most-cited placebo/nocebo papers) -> work/audit_missing.json."""
import json, sys, time, requests
sys.path.insert(0, ".")
from pipeline import db, config

papers = db.load_all(); screened = db.load_screened()
by_pmid, by_title = db.index_by_alt_ids(papers)
cands = json.load(open("work/candidates_pubmed.json"))
cand_dois = {(c.get("doi") or "").lower() for c in cands.values()}
seen_dois = {r["doi"].lower() for r in papers.values() if r.get("doi")} | {k[4:] for k in screened if k.startswith("doi:")}
H = {"User-Agent": f"{config.TOOL_NAME} (mailto:{config.CONTACT_EMAIL})"}
QUERIES = ['"placebo effect" | "placebo effects" | "placebo analgesia" | "placebo response" | nocebo | "open-label placebo"',
           '"placebo" + ("expectation" | "expectancy" | "conditioning" | "suggestion" | "mechanism")',
           '"sham" + ("effect" | "response" | "expectation")']
FIELDS = "title,year,externalIds,citationCount,abstract,journal,authors,publicationDate,openAccessPdf,publicationTypes"
missing, checked = {}, 0
for q in QUERIES:
    token = None; got = 0
    while got < 1500:
        params = {"query": q, "sort": "citationCount:desc", "fields": FIELDS, "limit": 1000}
        if token: params["token"] = token
        for attempt in range(6):
            r = requests.get("https://api.semanticscholar.org/graph/v1/paper/search/bulk", headers=H, params=params, timeout=90)
            if r.status_code in (429, 500, 503):
                time.sleep(10 * (attempt + 1)); continue
            break
        if r.status_code != 200:
            print("S2 error", r.status_code, r.text[:120]); break
        j = r.json()
        for w in j.get("data", []):
            checked += 1; got += 1
            ext = w.get("externalIds") or {}
            doi = (ext.get("DOI") or "").lower(); pm = str(ext.get("PubMed") or "") or None
            title = w.get("title") or ""; tl = title.lower()
            if not any(k in tl for k in ("placebo", "nocebo", "sham", "expectan", "expectation", "conditioned", "conditioning", "suggestion")):
                continue
            if (doi and (doi in seen_dois or doi in cand_dois)) or (pm and (pm in by_pmid or pm in cands)) or db.norm_title(title) in by_title:
                continue
            rec = {"pmid": pm, "doi": doi or None, "title": title, "abstract": w.get("abstract") or "", "journal": (w.get("journal") or {}).get("name") or "",
                   "journal_abbrev": "", "year": w.get("year"), "date": w.get("publicationDate") or (f"{w.get('year')}-01-01" if w.get("year") else ""),
                   "authors": [a.get("name") for a in (w.get("authors") or []) if a.get("name")], "pub_types": w.get("publicationTypes") or [], "mesh": [], "keywords": [],
                   "language": "", "cited_by_count": w.get("citationCount"), "oa_pdf_url": (w.get("openAccessPdf") or {}).get("url"), "sources": ["recall_audit_s2"]}
            if db.record_id(rec) in screened: continue
            missing.setdefault(doi or db.norm_title(title), rec)
        token = j.get("token")
        if not token or not j.get("data"): break
        time.sleep(1.2)
    time.sleep(1.2)
out = sorted(missing.values(), key=lambda m: -(m.get("cited_by_count") or 0))
json.dump(out, open("work/audit_missing.json", "w"), indent=1)
print(f"checked {checked} works; {len(out)} never seen by the pipeline")
for m in out[:30]:
    print(f"  {m.get('cited_by_count'):>6}  {m.get('year')}  {m['title'][:88]}  {m.get('doi') or ''}")
