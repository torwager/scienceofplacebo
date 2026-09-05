"""Resolve the review queue: find missing text (private PDF, open-access PDF, other abstract sources), reclassify;
for title-only records decide from the title alone (include only when the placebo/nocebo focus is explicit)."""
import json, re, subprocess, sys, time, requests
from pathlib import Path
sys.path.insert(0, ".")
from pipeline import db, classify, config

PDF_DIR = Path("/Users/f003vz1/Dartmouth College Dropbox/Tor Wager/A12_Computational_dev_projects/scienceofplacebo-private/pdfs")
H = {"User-Agent": "Mozilla/5.0 (scienceofplacebo; mailto:%s)" % config.CONTACT_EMAIL}
TITLE_ONLY_NOTE = ("NO ABSTRACT OR FULL TEXT EXISTS FOR THIS RECORD ANYWHERE. Decide from the title, journal and year alone and do NOT answer "
    "'uncertain': answer 'include' only when the title itself makes clear that placebo or nocebo effects, responses, mechanisms, or "
    "expectancy/suggestion/conditioning effects on symptoms are the subject of the paper (e.g. 'Placebo effects in psychotherapy', "
    "'The placebo response in depression trials', 'Posthypnotic suggestion to reduce pain'); otherwise answer 'exclude'. "
    "Tag conservatively (leave axes empty where the title gives no information).")


def pdf_text(path, limit=120000):
    try:
        t = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, timeout=120).stdout
        i = t.lower().rfind("\nreferences")
        if i > len(t) * 0.4: t = t[:i]
        return t[:limit] if len(t) > 800 else ""
    except Exception:  # noqa: BLE001
        return ""


def fetch_oa_pdf(rec):
    url = rec.get("oa_pdf_url");
    if not url: return ""
    slug = re.sub(r"[^a-z0-9]+", "_", (rec.get("title") or "")[:60].lower()).strip("_")
    dest = PDF_DIR / f"oa_{rec.get('pmid') or slug}.pdf"
    if not dest.exists():
        try:
            r = requests.get(url, headers=H, timeout=90, allow_redirects=True)
            if r.status_code != 200 or not r.content.startswith(b"%PDF-") or len(r.content) < 20000: return ""
            dest.write_bytes(r.content)
        except requests.RequestException:
            return ""
    return pdf_text(dest)


def other_abstract(rec):
    pm, doi = rec.get("pmid"), rec.get("doi")
    try:
        if pm:
            j = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params={"query": f"EXT_ID:{pm} AND SRC:MED", "format": "json", "resultType": "core"}, timeout=60).json()
            for h in j.get("resultList", {}).get("result", []):
                if h.get("abstractText"): return re.sub(r"<[^>]+>", " ", h["abstractText"])
    except Exception: pass  # noqa: BLE001
    try:
        key = f"PMID:{pm}" if pm else (f"DOI:{doi}" if doi else None)
        if key:
            j = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{key}", params={"fields": "abstract"}, headers=H, timeout=60).json()
            if j.get("abstract"): return j["abstract"]
        time.sleep(1.1)
    except Exception: pass  # noqa: BLE001
    try:
        if doi:
            j = requests.get(f"https://api.crossref.org/works/{doi}", params={"mailto": config.CONTACT_EMAIL}, timeout=60).json()
            a = j.get("message", {}).get("abstract")
            if a: return re.sub(r"<[^>]+>", " ", a)
    except Exception: pass  # noqa: BLE001
    return ""


def main():
    papers = db.load_all(); screened = db.load_screened()
    queue = [r for r in papers.values() if r.get("scope") == "review"]
    stats = {"n": len(queue), "fulltext": 0, "abstract_found": 0, "title_only": 0, "core": 0, "adjacent": 0, "exclude": 0, "review": 0, "errors": 0}
    for i, r in enumerate(queue):
        text = None; mode = None
        pp = r.get("private_pdf") or {}
        if pp.get("available") and (PDF_DIR / pp["store_key"]).exists():
            text = pdf_text(PDF_DIR / pp["store_key"]); mode = "full_text" if text else None
        if not text and r.get("oa_pdf_url"):
            text = fetch_oa_pdf(r); mode = "full_text" if text else None
        if not text and not r.get("abstract"):
            ab = other_abstract(r)
            if ab:
                r["abstract"] = ab; mode = "abstract_found"
        try:
            if mode == "full_text":
                cls, scope = classify.classify_record(r, full_text=text); stats["fulltext"] += 1
            elif mode == "abstract_found" or r.get("abstract"):
                cls, scope = classify.classify_record(r); stats["abstract_found"] += 1
            else:
                cls, scope = classify.classify_record(r, full_text=TITLE_ONLY_NOTE); cls["input_mode"] = "title_only"; stats["title_only"] += 1
                if scope == "review": scope = "exclude"
        except Exception as e:  # noqa: BLE001
            stats["errors"] += 1; print("error", r["id"], str(e)[:120], flush=True); continue
        r["classification"] = cls; r["scope"] = scope; stats[scope] += 1
        screened[r["id"]] = {**screened.get(r["id"], {}), "scope": scope, "date": time.strftime("%Y-%m-%d"), "reason": cls["screening"].get("exclusion_reason"), "prompt_version": "2.0.0", "via": "review_resolution"}
        if scope == "exclude": del papers[r["id"]]
        if i % 50 == 0:
            db.save_all(papers); db.save_screened(screened); print(i, stats, flush=True)
    db.save_all(papers); db.save_screened(screened)
    print("REVIEW_DONE", stats, flush=True)


if __name__ == "__main__":
    main()
