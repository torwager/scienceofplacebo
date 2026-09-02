"""Build refs.json (for the pdfdownload skill scripts) from the database: one entry per included paper with a DOI."""
import json, re, sys
sys.path.insert(0, ".")
from pipeline import db

papers = db.load_all()
refs = []
for r in papers.values():
    if r.get("scope") not in ("core", "adjacent") or not r.get("doi"):
        continue
    au = r.get("authors") or []
    sur = (au[0] if isinstance(au[0], str) else au[0].get("family", "")).split()[0] if au else "anon"
    words = re.sub(r"[^a-z0-9 ]", "", (r.get("title") or "").lower()).split()[:5]
    slug = re.sub(r"[^a-z0-9_]", "", f"{sur.lower()}_{r.get('year') or 'nd'}_{'_'.join(words)}")[:90]
    refs.append({"doi": r["doi"], "slug": slug, "pdf": None, "id": r["id"], "pmid": r.get("pmid"), "pmcid": r.get("pmcid"), "title": r.get("title"), "year": r.get("year")})
out = sys.argv[1] if len(sys.argv) > 1 else "work/pdf_refs.json"
json.dump(refs, open(out, "w"), indent=0)
print(len(refs), "refs ->", out)
