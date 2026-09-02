"""OpenAlex + Unpaywall enrichment: open-access PDF URL, publisher landing page, citation count."""
import time
import requests
from . import config

OA = "https://api.openalex.org/works"
UNPAYWALL = "https://api.unpaywall.org/v2"
H = {"User-Agent": f"{config.TOOL_NAME} (mailto:{config.CONTACT_EMAIL})"}


def by_doi(doi):
    if not doi:
        return None
    try:
        r = requests.get(f"{OA}/https://doi.org/{doi}", headers=H, timeout=60,
                         params={"mailto": config.CONTACT_EMAIL, "select": "id,doi,title,open_access,best_oa_location,primary_location,cited_by_count,publication_date,type"})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def by_pmid(pmid):
    try:
        r = requests.get(f"{OA}/pmid:{pmid}", headers=H, timeout=60,
                         params={"mailto": config.CONTACT_EMAIL, "select": "id,doi,title,open_access,best_oa_location,primary_location,cited_by_count,publication_date,type"})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def enrich(rec):
    """Mutates rec with oa_pdf_url, oa_status, landing_url, cited_by_count, openalex_id."""
    w = by_doi(rec.get("doi")) or (by_pmid(rec["pmid"]) if rec.get("pmid") else None)
    if not w:
        return rec
    rec["openalex_id"] = w.get("id")
    if not rec.get("doi") and w.get("doi"):
        rec["doi"] = w["doi"].replace("https://doi.org/", "").lower()
    oa = w.get("open_access") or {}
    rec["oa_status"] = oa.get("oa_status")
    best = w.get("best_oa_location") or {}
    rec["oa_pdf_url"] = best.get("pdf_url") or (oa.get("oa_url") if oa.get("is_oa") else None)
    prim = w.get("primary_location") or {}
    rec["landing_url"] = prim.get("landing_page_url")
    rec["cited_by_count"] = w.get("cited_by_count")
    if not rec.get("date") and w.get("publication_date"):
        rec["date"] = w["publication_date"]
    time.sleep(0.11)  # polite: OpenAlex allows 10 req/s
    return rec


def unpaywall_pdf(doi):
    try:
        r = requests.get(f"{UNPAYWALL}/{doi}", params={"email": config.CONTACT_EMAIL}, timeout=60)
        if r.status_code != 200:
            return None
        j = r.json()
        loc = j.get("best_oa_location") or {}
        return loc.get("url_for_pdf") or loc.get("url")
    except requests.RequestException:
        return None


SEARCH_TERMS = '"placebo effect"|"placebo effects"|"placebo response"|"placebo responses"|"placebo analgesia"|nocebo|"open-label placebo"|"treatment expectation"|"expectancy effects"'


def search_recent(from_date, per_page=200, max_pages=5):
    """Works published since from_date matching the placebo phrase set (articles + preprints)."""
    out, cursor = [], "*"
    for _ in range(max_pages):
        r = requests.get(OA, headers=H, timeout=60, params={
            "filter": f"title_and_abstract.search:{SEARCH_TERMS},type:article|preprint,from_publication_date:{from_date}",
            "per-page": per_page, "cursor": cursor, "mailto": config.CONTACT_EMAIL,
            "select": "id,doi,title,authorships,publication_date,publication_year,type,primary_location,open_access,best_oa_location,ids,abstract_inverted_index,keywords,cited_by_count,language"})
        r.raise_for_status()
        j = r.json()
        out.extend(j.get("results", []))
        cursor = (j.get("meta") or {}).get("next_cursor")
        if not cursor or not j.get("results"):
            break
        time.sleep(0.2)
    return out


def _abstract(inv):
    if not inv:
        return ""
    pos = {}
    for w, idxs in inv.items():
        for i in idxs:
            pos[i] = w
    return " ".join(pos[i] for i in sorted(pos))


def to_record(w):
    ids = w.get("ids") or {}
    pmid = (ids.get("pmid") or "").rsplit("/", 1)[-1] or None
    src = (w.get("primary_location") or {}).get("source") or {}
    date = w.get("publication_date") or ""
    return {
        "pmid": pmid,
        "doi": (w.get("doi") or "").replace("https://doi.org/", "").lower() or None,
        "pmcid": (ids.get("pmcid") or "").rsplit("/", 1)[-1] or None,
        "openalex_id": w.get("id"),
        "title": w.get("title") or "",
        "abstract": _abstract(w.get("abstract_inverted_index")),
        "journal": src.get("display_name") or ("Preprint" if w.get("type") == "preprint" else ""),
        "journal_abbrev": "",
        "year": w.get("publication_year"),
        "date": date,
        "authors": [((a.get("author") or {}).get("display_name") or "") for a in (w.get("authorships") or [])],
        "pub_types": ["Preprint"] if w.get("type") == "preprint" else [],
        "mesh": [],
        "keywords": [k.get("display_name") for k in (w.get("keywords") or []) if k.get("display_name")],
        "language": w.get("language") or "",
        "oa_status": (w.get("open_access") or {}).get("oa_status"),
        "oa_pdf_url": (w.get("best_oa_location") or {}).get("pdf_url"),
        "landing_url": (w.get("primary_location") or {}).get("landing_page_url"),
        "cited_by_count": w.get("cited_by_count"),
        "sources": ["openalex"],
    }
