import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PAPERS_DIR = DATA / "papers"          # papers-YYYY.json shards (included records)
CANDIDATES_DIR = ROOT / "work"        # local-only scratch (gitignored)
SEEDS_DIR = DATA / "seeds"
SITE_DATA = ROOT / "site" / "data"     # built artifacts served by the site

CONTACT_EMAIL = os.environ.get("SOP_CONTACT_EMAIL", "torwager@gmail.com")
TOOL_NAME = "scienceofplacebo"
NCBI_API_KEY = os.environ.get("NCBI_API_KEY")  # optional, raises rate limit 3->10 req/s

# PubMed query used for daily discovery and for historical backfill.
# Tuned 2026-09-02: 90% recall against the 2,268 JIPS-curated PMIDs, ~22k hits all-time.
PUBMED_CORE = (
    '"Placebo Effect"[MeSH] OR "Nocebo Effect"[MeSH] OR placebo effect*[tiab] OR placebo response*[tiab] '
    'OR placebo responder*[tiab] OR placebo analgesi*[tiab] OR placebo hypoalgesi*[tiab] OR nocebo*[tiab] '
    'OR "open-label placebo*"[tiab] OR "open label placebo*"[tiab] OR "placebo mechanism*"[tiab] '
    'OR "placebo research"[tiab] OR "placebo studies"[tiab] OR "expectancy effect*"[tiab] '
    'OR "treatment expectation*"[tiab] OR "placebo condition*"[tiab] OR "placebo manipulation*"[tiab] '
    'OR "placebo group*"[ti] OR "placebo treatment*"[ti] OR "placebo arm*"[ti] OR "placebo rate*"[tiab] '
    'OR "response to placebo"[tiab] OR "sham surgery"[ti] OR "sham acupuncture"[ti] '
    'OR "placebo-induced"[tiab] OR "placebo induced"[tiab] OR "nocebo-induced"[tiab]'
)
PUBMED_TITLE_ONLY = (
    'placebo*[ti] NOT ("placebo-controlled"[ti] OR "placebo controlled"[ti] OR "versus placebo"[ti] '
    'OR "vs placebo"[ti] OR "vs. placebo"[ti] OR "compared with placebo"[ti] OR "compared to placebo"[ti] '
    'OR "placebo-controlled"[tiab])'
)
PUBMED_QUERY = f"({PUBMED_CORE}) OR ({PUBMED_TITLE_ONLY})"

# Broad net for the daily run: anything mentioning placebo/nocebo in title/abstract
# that is NOT already caught by PUBMED_QUERY. These get a cheap title-only pre-screen.
PUBMED_BROAD = f"(placebo*[tiab] OR nocebo*[tiab]) NOT ({PUBMED_QUERY})"

EUROPEPMC_QUERY = (
    '(TITLE:"placebo effect*" OR TITLE:"nocebo" OR TITLE:"placebo response*" OR TITLE:"open-label placebo" '
    'OR TITLE:"placebo analgesia" OR ABSTRACT:"placebo effect*" OR ABSTRACT:"nocebo effect*" '
    'OR ABSTRACT:"placebo response*" OR ABSTRACT:"open-label placebo") AND (SRC:PPR)'
)  # preprints only from Europe PMC; PubMed covers the rest

FEED_CAP = 24
