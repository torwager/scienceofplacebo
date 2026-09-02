"""Seed scraper for the JIPS placebo database (https://jips.online/).

JIPS posts a hand-curated monthly list of placebo/nocebo publications (2016-2025), each with a PubMed link.
We use the WordPress REST API to pull every post and extract PMIDs and DOIs. JIPS is credited on the site.
"""
import json
import re
import time
import requests
from bs4 import BeautifulSoup
from . import config

H = {"User-Agent": f"Mozilla/5.0 ({config.TOOL_NAME} seed builder; {config.CONTACT_EMAIL})"}


def fetch_posts():
    posts, page = [], 1
    while True:
        r = requests.get("https://jips.online/wp-json/wp/v2/posts", headers=H, timeout=60,
                         params={"per_page": 100, "page": page, "_fields": "id,link,date,title,content"})
        if r.status_code != 200:
            break
        items = r.json()
        if not items:
            break
        posts.extend(items)
        page += 1
        time.sleep(0.5)
    return posts


def extract_ids(posts):
    """Return {pmid: {"post": title, "date": date, "url": link}} and a set of DOIs."""
    by_pmid, dois = {}, set()
    for p in posts:
        html = p["content"]["rendered"]
        title = BeautifulSoup(p["title"]["rendered"], "lxml").get_text()
        text = BeautifulSoup(html, "lxml").get_text("\n")
        for pmid in set(re.findall(r"pubmed(?:\.ncbi\.nlm\.nih\.gov)?/(\d{6,9})", html)):
            by_pmid.setdefault(pmid, {"post": title, "date": p["date"][:10], "url": p["link"]})
        for d in re.findall(r"doi:\s*(10\.\d{4,9}/[^\s<\"]+)", text, re.I):
            dois.add(d.rstrip(".").lower())
    return by_pmid, dois


def main():
    posts = fetch_posts()
    by_pmid, dois = extract_ids(posts)
    out = config.SEEDS_DIR / "jips_seed.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"source": "https://jips.online/", "n_posts": len(posts), "pmids": by_pmid, "dois": sorted(dois)},
              open(out, "w"), indent=1)
    print(f"JIPS: {len(posts)} posts, {len(by_pmid)} PMIDs, {len(dois)} DOIs -> {out}")


if __name__ == "__main__":
    main()
