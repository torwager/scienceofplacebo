"""One-time reference mining: read the reference lists of the PDFs in the private collection, pull out
references that look placebo-related, resolve them to PubMed/Crossref records, and hand the ones we have
never screened to the classifier. Finds papers the PubMed query missed, especially older ones without
abstracts or MeSH terms.

Usage: python3 scripts/mine_references.py [--max-llm N] [--resolve-only]
Outputs: work/mined_refs.json (all extracted refs + resolution), then classified rows appended to
work/classified_mined.jsonl and merged into data/ (scope core/adjacent/review) via ingest.
"""
import json, re, subprocess, sys, time, difflib
from pathlib import Path
sys.path.insert(0, ".")
from pipeline import db, pubmed, config, classify, ingest, openalex
import requests

PDF_DIR = Path("/Users/f003vz1/Dartmouth College Dropbox/Tor Wager/A12_Computational_dev_projects/scienceofplacebo-private/pdfs")
OUT = Path("work/mined_refs.json")
CLS = Path("work/classified_mined.jsonl")
KEY = re.compile(r"placebo|nocebo|expectan|suggestion|conditioning|conditioned|sham|hypnos|open[- ]label|context effect|meaning response|dummy|inert", re.I)
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>)\]]+)", re.I)
YEAR_RE = re.compile(r"\((19[4-9]\d|20[0-2]\d)[a-z]?\)|\b(19[4-9]\d|20[0-2]\d)\b")
args = sys.argv[1:]
MAX_LLM = int(args[args.index("--max-llm") + 1]) if "--max-llm" in args else 3000


def pdf_text(p):
    try:
        return subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True, timeout=120).stdout
    except Exception:  # noqa: BLE001
        return ""


def reference_section(txt):
    m = None
    for pat in (r"\n\s*(References|REFERENCES|Bibliography|Literature Cited)\s*\n", r"\n\s*References\b"):
        ms = list(re.finditer(pat, txt))
        if ms:
            m = ms[-1]; break
    return txt[m.end():] if m else txt[-len(txt) // 3:]


def split_refs(sec):
    sec = re.sub(r"[ \t]+", " ", sec)
    # numbered (1. / [1] / 1) styles) or blank-line separated
    parts = re.split(r"\n\s*(?:\[\d{1,3}\]|\d{1,3}\.|\d{1,3}\))\s+", "\n" + sec)
    if len(parts) < 5:
        parts = re.split(r"\n\s*\n", sec)
    if len(parts) < 5:
        parts = re.split(r"\n(?=[A-Z][A-Za-z\-']+,? [A-Z]\.?)", sec)
    refs = [" ".join(p.split()) for p in parts]
    return [r for r in refs if 40 < len(r) < 700 and YEAR_RE.search(r)]


def guess_title(ref):
    """Best-effort title from APA ('Authors (Year). Title. Journal') or Vancouver ('Authors. Title. Journal Year;')."""
    m = re.search(r"\((19[4-9]\d|20[0-2]\d)[a-z]?\)\.?\s*(.+?)\.\s", ref)
    if m and 15 < len(m.group(2)) < 250:
        return m.group(2)
    parts = [p.strip() for p in re.split(r"(?<=[a-z\)])\.\s+(?=[A-Z])", ref) if p.strip()]
    if len(parts) >= 2:
        cand = parts[1] if len(parts[0]) < 120 else parts[0]
        if 15 < len(cand) < 250 and not re.search(r"\d{4};|\bvol\b|\bpp\b", cand):
            return cand
    return None


def similar(a, b):
    return difflib.SequenceMatcher(None, db.norm_title(a), db.norm_title(b)).ratio()


def resolve_pubmed(title, year):
    q = f'"{title[:180]}"[ti]'
    try:
        ids = pubmed.search(q, retmax=3)
        if not ids and year:
            words = [w for w in re.findall(r"[A-Za-z]{4,}", title) if w.lower() not in ("with", "from", "that", "this", "study", "effect", "effects")][:6]
            if len(words) >= 3:
                ids = pubmed.search(" AND ".join(w + "[ti]" for w in words) + f" AND {year}[dp]", retmax=3)
        for rec in pubmed.fetch(ids[:3]):
            if similar(rec["title"], title) >= 0.85:
                return rec
    except Exception:  # noqa: BLE001
        return None
    return None


def main():
    papers = db.load_all(); screened = db.load_screened()
    by_pmid, by_title = db.index_by_alt_ids(papers)
    mined = json.load(open(OUT)) if OUT.exists() else {"scanned": [], "refs": {}}
    scanned = set(mined["scanned"])
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    print(f"{len(pdfs)} PDFs, {len(scanned)} already scanned", flush=True)
    for n, p in enumerate(pdfs):
        if p.name in scanned:
            continue
        txt = pdf_text(p)
        for ref in split_refs(reference_section(txt)):
            if not KEY.search(ref):
                continue
            doi = DOI_RE.search(ref)
            key = ("doi:" + doi.group(1).rstrip(".").lower()) if doi else ("t:" + db.norm_title(guess_title(ref) or "")[:80])
            if key in ("t:",):
                continue
            entry = mined["refs"].setdefault(key, {"ref": ref[:400], "title": guess_title(ref), "doi": doi.group(1).rstrip(".").lower() if doi else None,
                                                  "year": (YEAR_RE.search(ref).group(1) or YEAR_RE.search(ref).group(2)), "cited_by": []})
            if p.name not in entry["cited_by"]:
                entry["cited_by"].append(p.name)
        scanned.add(p.name); mined["scanned"] = sorted(scanned)
        if n % 50 == 0:
            json.dump(mined, open(OUT, "w")); print(f"scanned {n}/{len(pdfs)}, refs {len(mined['refs'])}", flush=True)
    json.dump(mined, open(OUT, "w"))
    print(f"placebo-related references extracted: {len(mined['refs'])}", flush=True)
    # ---- resolve + screen
    candidates = sorted(mined["refs"].items(), key=lambda kv: -len(kv[1]["cited_by"]))
    n_llm = 0; stats = {"resolved": 0, "already": 0, "new": 0, "core": 0, "adjacent": 0, "review": 0, "exclude": 0}
    for key, e in candidates:
        if e.get("resolved") is not None:
            continue
        rec = None
        if e["doi"]:
            try:
                ids = pubmed.search(f'{e["doi"]}[doi]', retmax=1)
                rec = next(iter(pubmed.fetch(ids)), None) if ids else None
            except Exception:  # noqa: BLE001
                rec = None
            if rec is None:
                w = openalex.by_doi(e["doi"])
                if w:
                    rec = openalex.to_record(w)
        elif e["title"]:
            rec = resolve_pubmed(e["title"], e["year"])
        e["resolved"] = bool(rec)
        if not rec:
            continue
        stats["resolved"] += 1
        rid = db.record_id(rec)
        if rid in screened or db.find_existing(rec, papers, by_pmid, by_title):
            stats["already"] += 1; e["status"] = "already_in_db"; continue
        if n_llm >= MAX_LLM or classify.prefilter(rec):
            e["status"] = "skipped"; continue
        rec["sources"] = ["reference_mining"]
        try:
            openalex.enrich(rec)
            cls, scope = classify.classify_record(rec); n_llm += 1
        except Exception as ex:  # noqa: BLE001
            e["status"] = "error:" + str(ex)[:100]; continue
        stats["new"] += 1; stats[scope] += 1; e["status"] = scope; e["id"] = rid
        screened[rid] = {"scope": scope, "pmid": rec.get("pmid"), "date": time.strftime("%Y-%m-%d"), "reason": cls["screening"].get("exclusion_reason"), "via": "reference_mining"}
        with open(CLS, "a") as fh:
            fh.write(json.dumps({"id": rid, "scope": scope, "cited_by": e["cited_by"]}) + "\n")
        if scope in ("core", "adjacent", "review"):
            ingest.upsert(papers, ingest.make_record(rec, cls, scope, date_added=(rec.get("date") or time.strftime("%Y-%m-%d"))[:10]), by_pmid, by_title)
        if stats["new"] % 50 == 0:
            db.save_all(papers); db.save_screened(screened); json.dump(mined, open(OUT, "w")); print(stats, flush=True)
    db.save_all(papers); db.save_screened(screened); json.dump(mined, open(OUT, "w"))
    print("DONE", stats, flush=True)


if __name__ == "__main__":
    main()
