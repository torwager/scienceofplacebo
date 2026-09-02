"""Turn a candidate record + classification into a database record, and merge into the DB."""
import time
from . import db


def make_record(cand, cls, scope, sources=None, date_added=None):
    rec = {
        "id": db.record_id(cand),
        "title": cand.get("title", ""),
        "authors": cand.get("authors") or [],
        "journal": cand.get("journal") or "",
        "journal_abbrev": cand.get("journal_abbrev") or "",
        "year": cand.get("year"),
        "date": cand.get("date") or "",
        "doi": cand.get("doi"),
        "pmid": cand.get("pmid"),
        "pmcid": cand.get("pmcid"),
        "openalex_id": cand.get("openalex_id"),
        "abstract": cand.get("abstract") or "",
        "keywords": cand.get("keywords") or [],
        "mesh": cand.get("mesh") or [],
        "pub_types": cand.get("pub_types") or [],
        "oa_status": cand.get("oa_status"),
        "oa_pdf_url": cand.get("oa_pdf_url"),
        "landing_url": cand.get("landing_url"),
        "cited_by_count": cand.get("cited_by_count"),
        "scope": scope,
        "classification": cls,
        "sources": sorted(set(sources or cand.get("sources") or [])),
        "date_added": date_added or time.strftime("%Y-%m-%d"),
        "private_pdf": cand.get("private_pdf"),
    }
    return rec


def publisher_url(rec):
    if rec.get("doi"):
        return f"https://doi.org/{rec['doi']}"
    if rec.get("landing_url"):
        return rec["landing_url"]
    if rec.get("pmid"):
        return f"https://pubmed.ncbi.nlm.nih.gov/{rec['pmid']}/"
    return None


def upsert(papers, rec, by_pmid, by_title):
    """Insert or merge rec into papers dict. Returns 'added' | 'updated'."""
    existing_id = db.find_existing(rec, papers, by_pmid, by_title)
    if existing_id:
        ex = papers[existing_id]
        db.merge(ex, rec)
        if rec.get("classification") and (not ex.get("classification") or
                                          rec["classification"].get("prompt_version", "") >= ex["classification"].get("prompt_version", "")):
            ex["classification"] = rec["classification"]
            ex["scope"] = rec["scope"]
        return "updated"
    papers[rec["id"]] = rec
    if rec.get("pmid"):
        by_pmid[str(rec["pmid"])] = rec["id"]
    by_title[db.norm_title(rec["title"])] = rec["id"]
    return "added"
