"""Copy placebo-related PDFs from the local Paperpile (Google Drive) folder into the private collection.
Selection: filename keyword match (first pass) and, once the database exists, title match against included papers.
Destination is OUTSIDE the public repo: ~/Documents/scienceofplacebo-private/pdfs/
"""
import json, os, re, shutil, sys, hashlib
from pathlib import Path
sys.path.insert(0, ".")
from pipeline import db, config

PP = Path.home() / "Library/CloudStorage/GoogleDrive-tor.d.wager@dartmouth.edu/My Drive/Paperpile"
DEST = Path.home() / "Documents/scienceofplacebo-private/pdfs"
KW = re.compile(r"placebo|nocebo|expectan|expectation|open[- ]label|sham|conditioning|suggestion|hypnosis|hypnotic|belief|mindset|context effect|treatment context", re.I)
PAT = re.compile(r"^(?P<auth>.+?)\s+(?P<year>\d{4}[a-z]?)\s+-\s+(?P<title>.+?)(?:\s+\((?P<dup>\d+)\))?\.pdf$", re.I)


def scan():
    recs = []
    for sub in ["All Papers", "Starred Papers"]:
        for root, _, files in os.walk(PP / sub):
            for f in files:
                if not f.lower().endswith(".pdf"):
                    continue
                m = PAT.match(f)
                recs.append({"path": os.path.join(root, f), "file": f, "title": m.group("title") if m else "",
                             "year": m.group("year")[:4] if m else "", "dup": bool(m and m.group("dup"))})
    return recs


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    papers = db.load_all()
    _, by_title = db.index_by_alt_ids(papers)
    manifest_path = DEST.parent / "manifest.json"
    manifest = json.load(open(manifest_path)) if manifest_path.exists() else {}
    recs = scan()
    seen_titles = set()
    n_copied = 0
    for r in sorted(recs, key=lambda r: (r["dup"], r["path"])):
        nt = db.norm_title(r["title"])
        matched_id = by_title.get(nt)
        if not (matched_id or KW.search(r["file"])):
            continue
        if nt in seen_titles:
            continue
        seen_titles.add(nt)
        safe = re.sub(r"[^\w\-. ]+", "_", r["file"])[:180]
        if not safe.lower().endswith(".pdf"):
            safe += ".pdf"
        dest = DEST / safe
        if not dest.exists():
            try:
                shutil.copy2(r["path"], dest)
                n_copied += 1
            except OSError as e:
                print("skip", r["file"], e)
                continue
        manifest[safe] = {"paper_id": matched_id, "title": r["title"], "year": r["year"], "source": "paperpile",
                          "sha1": hashlib.sha1(open(dest, "rb").read(1 << 20)).hexdigest()}
    json.dump(manifest, open(manifest_path, "w"), indent=1)
    print(f"copied {n_copied} new; collection now {len(manifest)} PDFs at {DEST}")


if __name__ == "__main__":
    main()
