"""Record which papers have a PDF in the private collection (metadata only; files never enter the repo)."""
import json, sys, hashlib
from pathlib import Path
sys.path.insert(0, ".")
from pipeline import db

DEST = Path("/Users/f003vz1/Dartmouth College Dropbox/Tor Wager/A12_Computational_dev_projects/scienceofplacebo-private")
refs = json.load(open("work/pdf_refs.json"))
papers = db.load_all()
n = 0
for ref in refs:
    if not ref.get("pdf") or ref["id"] not in papers:
        continue
    p = Path(ref["pdf"]) if Path(ref["pdf"]).is_absolute() else DEST / "pdfs" / ref["pdf"]
    if p.exists():
        papers[ref["id"]]["private_pdf"] = {"available": True, "store_key": p.name, "source": ref.get("status", "download"),
                                            "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16]}
        n += 1
db.save_all(papers)
print("papers with private PDF:", n)
