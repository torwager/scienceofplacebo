#!/bin/bash
# One sitting of the browser route: drive the signed-in Chrome through EZproxy for N papers (default 80), 5 s apart,
# stopping at the first access-denied/rate-limit page. Then file whatever landed and flag papers in the database.
# Preconditions: Chrome open and signed in to the Dartmouth proxy (open one proxied link and pass Duo first).
cd "/Users/f003vz1/Documents/GitHub/scienceofplacebo"
N=${1:-80}
DEST="/Users/f003vz1/Dartmouth College Dropbox/Tor Wager/A12_Computational_dev_projects/scienceofplacebo-private/pdfs"
SK=/Users/f003vz1/.claude/skills/pdfdownload/scripts
export PDFDOWNLOAD_EZPROXY="https://dartmouth.idm.oclc.org/login"
python3 scripts/make_proxy_worklist.py
python3 $SK/click_through.py --refs work/pdf_proxy_refs.json --dir "$DEST" --ezproxy "$PDFDOWNLOAD_EZPROXY" --delay 5 --max "$N" 2>&1 | tee -a work/proxy_batches.log
python3 $SK/file_downloads.py --refs work/pdf_proxy_refs.json --dir "$DEST" 2>&1 | tail -3 | tee -a work/proxy_batches.log
# copy results back into the master refs file and flag papers with private PDFs
python3 - <<'PY'
import json
main = {r["id"]: r for r in json.load(open("work/pdf_refs.json"))}
for r in json.load(open("work/pdf_proxy_refs.json")):
    if r.get("pdf"): main[r["id"]].update({"pdf": r["pdf"], "status": r.get("status", "downloaded")})
    elif r.get("status"): main[r["id"]]["status"] = r["status"]
json.dump(list(main.values()), open("work/pdf_refs.json", "w"), indent=0)
PY
python3 scripts/mark_private_pdfs.py | tee -a work/proxy_batches.log
echo "BATCH_DONE $(date)" >> work/proxy_batches.log
