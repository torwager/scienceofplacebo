"""Europe PMC REST: preprint discovery and full-text OA availability."""
import time
import requests
from . import config

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def search(query, from_date=None, page_size=100, max_records=2000):
    """Search Europe PMC. from_date: YYYY-MM-DD (first index date). Returns list of result dicts."""
    q = query
    if from_date:
        q = f"({query}) AND (FIRST_IDATE:[{from_date} TO 3000-01-01])"
    out, cursor = [], "*"
    while len(out) < max_records:
        r = requests.get(f"{BASE}/search", timeout=60, params={
            "query": q, "format": "json", "pageSize": page_size, "cursorMark": cursor, "resultType": "core"})
        r.raise_for_status()
        j = r.json()
        hits = j.get("resultList", {}).get("result", [])
        out.extend(hits)
        nxt = j.get("nextCursorMark")
        if not hits or not nxt or nxt == cursor:
            break
        cursor = nxt
        time.sleep(0.3)
    return out


def to_record(h):
    """Map a Europe PMC core result to our candidate record shape."""
    authors = [a.get("fullName") for a in (h.get("authorList") or {}).get("author", []) if a.get("fullName")]
    date = h.get("firstPublicationDate") or ""
    return {
        "pmid": h.get("pmid"),
        "doi": (h.get("doi") or "").lower() or None,
        "pmcid": h.get("pmcid"),
        "title": h.get("title") or "",
        "abstract": h.get("abstractText") or "",
        "journal": (h.get("journalInfo") or {}).get("journal", {}).get("title") or h.get("bookOrReportDetails", {}).get("publisher", "") or ("Preprint" if h.get("source") == "PPR" else ""),
        "journal_abbrev": "",
        "year": int(date[:4]) if date[:4].isdigit() else None,
        "date": date,
        "authors": authors,
        "pub_types": ["Preprint"] if h.get("source") == "PPR" else [],
        "mesh": [],
        "keywords": h.get("keywordList", {}).get("keyword", []) if isinstance(h.get("keywordList"), dict) else [],
        "language": h.get("language") or "",
        "europepmc_id": f"{h.get('source')}:{h.get('id')}",
        "landing_url": next((u.get("url") for u in (h.get("fullTextUrlList") or {}).get("fullTextUrl", []) if u.get("documentStyle") == "html"), None),
        "oa_pdf_url": next((u.get("url") for u in (h.get("fullTextUrlList") or {}).get("fullTextUrl", []) if u.get("documentStyle") == "pdf" and u.get("availability", "").lower().startswith("open")), None),
    }


def fulltext_xml(pmcid):
    """Return OA full text XML for a PMCID if available, else None."""
    if not pmcid:
        return None
    r = requests.get(f"{BASE}/{pmcid}/fullTextXML", timeout=60)
    return r.text if r.status_code == 200 and r.text.strip() else None
