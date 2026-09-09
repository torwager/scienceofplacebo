"""Ingest a reference-manager export (RIS or CSV) from a subscription database such as Embase, PsycINFO, Scopus or
Web of Science: resolve each record to a PubMed/OpenAlex record where possible, skip anything already screened, then
prefilter, classify with the current prompt and merge included papers. Records with no PubMed/OpenAlex match are
screened from the export's own title/abstract.

Usage: python3 scripts/ingest_export.py path/to/export.ris --source embase [--max-llm 3000]
Then: python3 scripts/integrity.py && python3 -m pipeline.build_site && git add data && git commit && git push
"""
import csv, json, re, sys, time
sys.path.insert(0, ".")
from pipeline import db, pubmed, openalex, classify, ingest

args = sys.argv[1:]
path = args[0]; source = args[args.index("--source") + 1] if "--source" in args else "manual_export"
MAX_LLM = int(args[args.index("--max-llm") + 1]) if "--max-llm" in args else 3000


def parse_ris(text):
    recs, cur = [], {}
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])  - ?(.*)$", line)
        if not m:
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "ER":
            if cur: recs.append(cur)
            cur = {}; continue
        cur.setdefault(tag, []).append(val)
    if cur: recs.append(cur)
    out = []
    for r in recs:
        g = lambda *tags: next((r[t][0] for t in tags if r.get(t)), "")
        doi = g("DO", "DI"); m = re.search(r"10\.\d{4,9}/\S+", doi or " ".join(r.get("UR", []))); doi = m.group(0).lower().rstrip(".") if m else None
        pm = next((re.sub(r"\D", "", v) for v in r.get("AN", []) + r.get("ID", []) if re.fullmatch(r"(PMID:?\s*)?\d{6,9}", v.strip())), None)
        year = re.search(r"\d{4}", g("PY", "Y1", "DA") or ""); year = int(year.group(0)) if year else None
        out.append({"title": g("TI", "T1"), "abstract": g("AB", "N2"), "doi": doi, "pmid": pm, "authors": r.get("AU", []) + r.get("A1", []), "journal": g("JO", "JF", "T2"),
                    "journal_abbrev": g("JA", ""), "year": year, "date": f"{year}-01-01" if year else "", "pub_types": [], "mesh": [], "keywords": r.get("KW", []), "language": ""})
    return out


def parse_csv(text):
    out = []
    for row in csv.DictReader(text.splitlines()):
        low = {k.lower().strip(): (v or "").strip() for k, v in row.items() if k}
        pick = lambda *keys: next((low[k] for k in keys if k in low and low[k]), "")
        doi = pick("doi", "di"); m = re.search(r"10\.\d{4,9}/\S+", doi); doi = m.group(0).lower() if m else None
        pm = re.sub(r"\D", "", pick("pmid", "pubmed id", "pubmed_id")) or None
        year = re.search(r"\d{4}", pick("year", "publication year", "py") or ""); year = int(year.group(0)) if year else None
        out.append({"title": pick("title", "article title", "ti"), "abstract": pick("abstract", "ab"), "doi": doi, "pmid": pm, "authors": [a.strip() for a in re.split(r";|\|", pick("authors", "author", "au")) if a.strip()],
                    "journal": pick("journal", "source title", "source", "so"), "journal_abbrev": "", "year": year, "date": f"{year}-01-01" if year else "", "pub_types": [], "mesh": [], "keywords": [], "language": ""})
    return out


text = open(path, encoding="utf-8", errors="replace").read()
recs = parse_ris(text) if not path.lower().endswith(".csv") else parse_csv(text)
print(f"parsed {len(recs)} records from {path}", flush=True)
papers = db.load_all(); screened = db.load_screened(); by_pmid, by_title = db.index_by_alt_ids(papers)
stats = {"resolved_pubmed": 0, "resolved_openalex": 0, "unresolved": 0, "already": 0, "prefiltered": 0, "classified": 0, "core": 0, "adjacent": 0, "review": 0, "exclude": 0, "errors": 0}
for r in recs:
    if not r["title"]:
        continue
    full = None
    try:
        if r.get("pmid"):
            full = next(iter(pubmed.fetch([r["pmid"]])), None)
        if not full and r.get("doi"):
            ids = pubmed.search(f'{r["doi"]}[doi]', retmax=1); time.sleep(0.34)
            full = next(iter(pubmed.fetch(ids)), None) if ids else None
        if not full and not r.get("doi"):
            ids = pubmed.search(f'"{r["title"][:180]}"[ti]', retmax=1); time.sleep(0.34)
            cand = next(iter(pubmed.fetch(ids)), None) if ids else None
            if cand and db.norm_title(cand["title"]) == db.norm_title(r["title"]): full = cand
    except Exception:  # noqa: BLE001
        full = None
    if full:
        stats["resolved_pubmed"] += 1; rec = full
    else:
        w = openalex.by_doi(r["doi"]) if r.get("doi") else None
        if w:
            stats["resolved_openalex"] += 1; rec = openalex.to_record(w)
            if not rec.get("abstract"): rec["abstract"] = r["abstract"]
        else:
            stats["unresolved"] += 1; rec = r
    rec["sources"] = [source]
    rid = db.record_id(rec)
    if rid in screened or db.find_existing(rec, papers, by_pmid, by_title):
        stats["already"] += 1; continue
    reason = classify.prefilter(rec)
    if reason:
        screened[rid] = {"scope": "exclude", "pmid": rec.get("pmid"), "date": time.strftime("%Y-%m-%d"), "reason": reason, "via": source}; stats["prefiltered"] += 1; continue
    if stats["classified"] >= MAX_LLM:
        break
    try:
        cls, scope = classify.classify_record(rec)
    except Exception as e:  # noqa: BLE001
        stats["errors"] += 1; print("error", rid, str(e)[:100]); continue
    stats["classified"] += 1; stats[scope] += 1
    screened[rid] = {"scope": scope, "pmid": rec.get("pmid"), "date": time.strftime("%Y-%m-%d"), "reason": cls["screening"].get("exclusion_reason"), "prompt_version": cls.get("prompt_version"), "via": source}
    if scope in ("core", "adjacent", "review"):
        try: openalex.enrich(rec)
        except Exception: pass  # noqa: BLE001
        ingest.upsert(papers, ingest.make_record(rec, cls, scope, date_added=time.strftime("%Y-%m-%d")), by_pmid, by_title)
    if stats["classified"] % 100 == 0:
        db.save_all(papers); db.save_screened(screened); print(stats, flush=True)
db.save_all(papers); db.save_screened(screened)
print("EXPORT_INGEST_DONE", stats, flush=True)
