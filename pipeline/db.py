"""JSON database of included papers, sharded by year under data/papers/papers-YYYY.json.

Record identity: doi (lowercase) if present, else pmid, else a hash of the normalized title.
Also keeps data/screened.json: every candidate we have ever screened (id -> decision) so we never re-screen.
"""
import hashlib
import json
import re
from pathlib import Path
from . import config

SCREENED = config.DATA / "screened.json"


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def record_id(rec):
    if rec.get("doi"):
        return "doi:" + rec["doi"].lower().strip()
    if rec.get("pmid"):
        return "pmid:" + str(rec["pmid"])
    return "title:" + hashlib.sha1(norm_title(rec.get("title")).encode()).hexdigest()[:16]


def load_all():
    papers = {}
    for f in sorted(config.PAPERS_DIR.glob("papers-*.json")):
        for r in json.load(open(f)):
            papers[r["id"]] = r
    return papers


def save_all(papers):
    config.PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    by_year = {}
    for r in papers.values():
        by_year.setdefault(r.get("year") or 0, []).append(r)
    for f in config.PAPERS_DIR.glob("papers-*.json"):
        f.unlink()
    for y, rs in by_year.items():
        rs.sort(key=lambda r: (r.get("date") or "", r["id"]), reverse=True)
        with open(config.PAPERS_DIR / f"papers-{y or 'unknown'}.json", "w") as fh:
            json.dump(rs, fh, indent=0, ensure_ascii=False)


def load_screened():
    return json.load(open(SCREENED)) if SCREENED.exists() else {}


def save_screened(s):
    SCREENED.parent.mkdir(parents=True, exist_ok=True)
    with open(SCREENED, "w") as fh:
        json.dump(s, fh, indent=0, ensure_ascii=False)


def index_by_alt_ids(papers):
    """Map pmid -> id and normalized title -> id, for dedup of candidates lacking a DOI."""
    by_pmid, by_title = {}, {}
    for r in papers.values():
        if r.get("pmid"):
            by_pmid[str(r["pmid"])] = r["id"]
        by_title[norm_title(r.get("title"))] = r["id"]
    return by_pmid, by_title


def find_existing(rec, papers, by_pmid, by_title):
    rid = record_id(rec)
    if rid in papers:
        return rid
    if rec.get("pmid") and str(rec["pmid"]) in by_pmid:
        return by_pmid[str(rec["pmid"])]
    nt = norm_title(rec.get("title"))
    if nt and nt in by_title:
        return by_title[nt]
    return None


def merge(existing, new):
    """Fill missing fields of an existing record from a new candidate; never downgrade."""
    for k, v in new.items():
        if k in ("id", "tags", "screen", "date_added"):
            continue
        if v and not existing.get(k):
            existing[k] = v
    if new.get("abstract") and len(new["abstract"]) > len(existing.get("abstract") or ""):
        existing["abstract"] = new["abstract"]
    src = set(existing.get("sources") or []) | set(new.get("sources") or [])
    existing["sources"] = sorted(src)
    return existing
