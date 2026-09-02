"""Placebo in the news: news stories, podcast episodes and blog posts about placebo/nocebo effects.

Sources (no keys): Google News RSS (news + many blogs), Apple iTunes Search (podcast episodes).
Optional LLM relevance pass (title + snippet) drops false positives such as "placebo-controlled trial" press releases.
Runs every 2 days from .github/workflows/news.yml; keeps 180 days of items in data/news.json.
"""
import html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import requests
from . import config

NEWS_PATH = config.DATA / "news.json"
H = {"User-Agent": f"Mozilla/5.0 ({config.TOOL_NAME} news bot; {config.CONTACT_EMAIL})"}
QUERIES = ['"placebo effect"', '"nocebo effect"', '"placebo effects" OR "nocebo effects"', '"open-label placebo"', '"placebo response"']
PODCAST_TERMS = ["placebo effect", "nocebo", "placebo"]
KEEP_DAYS = 180
RELEVANT = re.compile(r"placebo|nocebo", re.I)
NOISE = re.compile(r"placebo-controlled|versus placebo|vs\.? placebo|compared (with|to) placebo|placebo group|placebo arm|phase (2|3|II|III)", re.I)


def google_news(query):
    url = "https://news.google.com/rss/search"
    r = requests.get(url, params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}, headers=H, timeout=60)
    r.raise_for_status()
    items = []
    for it in re.findall(r"<item>(.*?)</item>", r.text, re.S):
        def g(tag):
            m = re.search(rf"<{tag}>(.*?)</{tag}>", it, re.S)
            return html.unescape(re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1))).strip() if m else ""
        title, link, pub, src = g("title"), g("link"), g("pubDate"), g("source")
        try:
            date = parsedate_to_datetime(pub).astimezone(timezone.utc).date().isoformat()
        except Exception:  # noqa: BLE001
            date = ""
        src = src or (title.rsplit(" - ", 1)[-1] if " - " in title else "")
        title = title.rsplit(" - ", 1)[0] if " - " in title else title
        items.append({"title": title, "url": link, "date": date, "source": src, "kind": "news", "snippet": ""})
    return items


def podcasts(term):
    r = requests.get("https://itunes.apple.com/search", params={"term": term, "media": "podcast", "entity": "podcastEpisode", "limit": 50}, headers=H, timeout=60)
    r.raise_for_status()
    out = []
    for e in r.json().get("results", []):
        title = e.get("trackName") or ""
        if not RELEVANT.search(title + " " + (e.get("description") or "")[:400]):
            continue
        out.append({"title": title, "url": e.get("trackViewUrl") or e.get("collectionViewUrl") or "", "date": (e.get("releaseDate") or "")[:10],
                    "source": e.get("collectionName") or "Podcast", "kind": "podcast", "snippet": re.sub(r"<[^>]+>", " ", e.get("description") or "")[:280].strip()})
    return out


def norm_url(u):
    return re.sub(r"[?#].*$", "", u.strip().lower())


def llm_filter(items):
    """Optional: ask the LLM whether each item is really about placebo/nocebo effects (title-level, cheap)."""
    try:
        from .llm_client import Classifier  # noqa: F401  (ensures provider libs are importable)
        from .classify import get_classifier
        clf = get_classifier()
    except Exception:  # noqa: BLE001
        return items
    schema = {"type": "object", "additionalProperties": False, "required": ["keep"],
              "properties": {"keep": {"type": "array", "items": {"type": "boolean"}}}}
    system = ("You curate a 'placebo effects in the news' page for a scientific audience. Given a numbered list of headlines "
              "(news stories, podcast episodes, blog posts), answer for each whether it is genuinely ABOUT placebo or nocebo effects, "
              "placebo responses, expectation effects on health, or placebo research/researchers. Answer false for drug-trial results "
              "that merely mention a placebo comparator, and for 'placebo' used metaphorically (politics, sport tactics, products). "
              "Return JSON {keep: [bool,...]} with exactly one boolean per line, in order.")
    out = []
    for i in range(0, len(items), 40):
        chunk = items[i:i + 40]
        user = "\n".join(f"{j + 1}. [{it['kind']}] {it['title']} ({it['source']})" for j, it in enumerate(chunk))
        try:
            if clf.provider == "anthropic":
                resp = clf._client.messages.create(model=clf.model, max_tokens=400, system=system, messages=[{"role": "user", "content": user}],
                                                   output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}})
                keep = json.loads(next(b.text for b in resp.content if b.type == "text"))["keep"]
            else:
                resp = clf._client.responses.create(model=clf.model, input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                                                    text={"format": {"type": "json_schema", "name": "keep", "schema": schema, "strict": True}}, max_output_tokens=400,
                                                    **({"reasoning": {"effort": "low"}} if clf.model.startswith("gpt-5") else {}))
                keep = json.loads(resp.output_text)["keep"]
            if len(keep) != len(chunk):
                out.extend(chunk); continue
            out.extend(it for it, k in zip(chunk, keep) if k)
        except Exception:  # noqa: BLE001
            out.extend(chunk)
    return out


def main(use_llm=True):
    existing = json.load(open(NEWS_PATH)) if NEWS_PATH.exists() else {"updated": "", "items": []}
    seen = {norm_url(it["url"]) for it in existing["items"]}
    fresh = []
    for q in QUERIES:
        try:
            fresh.extend(google_news(q))
        except Exception as e:  # noqa: BLE001
            print("google news error", q, e)
        time.sleep(1)
    for t in PODCAST_TERMS:
        try:
            fresh.extend(podcasts(t))
        except Exception as e:  # noqa: BLE001
            print("podcast error", t, e)
        time.sleep(1)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).date().isoformat()
    new, local_seen = [], set()
    for it in fresh:
        k = norm_url(it["url"])
        if not it["url"] or k in seen or k in local_seen or not it["title"]:
            continue
        if it["date"] and it["date"] < cutoff:
            continue
        if NOISE.search(it["title"]) and not re.search(r"placebo effect|nocebo|placebo response", it["title"], re.I):
            continue
        if re.match(r"^(Figure|Table|Fig\.)\s*\d", it["title"]) or re.search(r"\| (Journal of|Nature|Science|The Lancet|JAMA|BMJ)\b", it["title"]):
            continue  # journal figure pages and article pages are papers, not news
        local_seen.add(k)
        new.append(it)
    print(f"fetched {len(fresh)}, new candidates {len(new)}")
    if use_llm and new:
        kept = llm_filter(new)
        print(f"LLM kept {len(kept)} of {len(new)}")
        new = kept
    today = datetime.now(timezone.utc).date().isoformat()
    for it in new:
        it["added"] = today
    items = [it for it in existing["items"] if (it.get("date") or it.get("added", "")) >= cutoff] + new
    items.sort(key=lambda it: (it.get("date") or it.get("added", ""), it["title"]), reverse=True)
    NEWS_PATH.write_text(json.dumps({"updated": today, "items": items}, indent=1, ensure_ascii=False))
    print(f"news.json: {len(items)} items")
    return len(new)


if __name__ == "__main__":
    import sys
    main(use_llm="--no-llm" not in sys.argv)
