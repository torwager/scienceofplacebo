"""Build the browser-route worklist: papers still without a PDF, core first, then most cited. Writes work/pdf_proxy_refs.json
(same shape as refs.json, consumed by the pdfdownload click_through / make_sheet scripts)."""
import json, sys
sys.path.insert(0, ".")
from pipeline import db
refs = json.load(open("work/pdf_refs.json"))
papers = db.load_all()
have = {r["doi"] for r in refs if r.get("pdf")}
todo = [r for r in refs if not r.get("pdf") and r.get("status") in ("no_oa_pdf", "blocked", None)]
def key(r):
    p = papers.get(r["id"]) or {}
    return (0 if p.get("scope") == "core" else 1, -(p.get("cited_by_count") or 0), -(p.get("year") or 0))
todo.sort(key=key)
json.dump(todo, open("work/pdf_proxy_refs.json", "w"), indent=0)
import collections
print(f"proxy worklist: {len(todo)} papers ({sum(1 for r in todo if (papers.get(r['id']) or {}).get('scope')=='core')} core); statuses {collections.Counter(r.get('status') for r in todo)}")
