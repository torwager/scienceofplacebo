"""One-time (re-runnable): fetch OpenAlex metadata for every paper in the DB in batches of 50 DOIs
(citation counts, open-access status and PDF URL, landing page), then save the DB."""
import json, sys, time, requests
sys.path.insert(0, ".")
from pipeline import db, config

papers = db.load_all()
by_doi = {r["doi"].lower(): r for r in papers.values() if r.get("doi")}
todo = [d for d, r in by_doi.items() if r.get("openalex_checked") != "2026-09-02v2"]
print("to enrich", len(todo), flush=True)
H = {"User-Agent": f"{config.TOOL_NAME} (mailto:{config.CONTACT_EMAIL})"}
SEL = "id,doi,title,open_access,best_oa_location,primary_location,cited_by_count,publication_date"
import difflib
done = 0; mism = 0
for i in range(0, len(todo), 50):
    chunk = todo[i:i + 50]
    for attempt in range(4):
        try:
            r = requests.get("https://api.openalex.org/works", headers=H, timeout=90, params={
                "filter": "doi:" + "|".join(chunk), "per-page": 50, "select": SEL, "mailto": config.CONTACT_EMAIL})
            if r.status_code == 429:
                time.sleep(10 * (attempt + 1)); continue
            r.raise_for_status(); break
        except requests.RequestException as e:
            print("retry", e, flush=True); time.sleep(5 * (attempt + 1))
    else:
        continue
    for w in r.json().get("results", []):
        d = (w.get("doi") or "").replace("https://doi.org/", "").lower()
        rec = by_doi.get(d)
        if not rec:
            continue
        sim = difflib.SequenceMatcher(None, db.norm_title(w.get("title") or ""), db.norm_title(rec.get("title") or "")).ratio()
        if w.get("title") and sim < 0.6:
            rec["openalex_mismatch"] = True
            rec["cited_by_count"] = None; rec["oa_pdf_url"] = None; rec["oa_status"] = None; rec["openalex_id"] = None
            mism += 1
            continue
        rec.pop("openalex_mismatch", None)
        oa = w.get("open_access") or {}
        best = w.get("best_oa_location") or {}
        rec["openalex_id"] = w.get("id")
        rec["oa_status"] = oa.get("oa_status")
        rec["oa_pdf_url"] = best.get("pdf_url") or (oa.get("oa_url") if oa.get("is_oa") else None)
        rec["landing_url"] = (w.get("primary_location") or {}).get("landing_page_url")
        rec["cited_by_count"] = w.get("cited_by_count")
        done += 1
    for d in chunk:
        by_doi[d]["openalex_checked"] = "2026-09-02v2"
    if (i // 50) % 20 == 0:
        print(f"{i + len(chunk)}/{len(todo)} matched {done}", flush=True)
        db.save_all(papers)
    time.sleep(0.25)
db.save_all(papers)
print("DONE matched", done, "mismatched", mism, "of", len(todo), flush=True)
