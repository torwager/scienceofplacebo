"""PubMed E-utilities: search and fetch. No API key required (3 req/s); NCBI_API_KEY raises to 10 req/s."""
import json
import time
import requests
from lxml import etree
from . import config

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _params(extra):
    p = {"db": "pubmed", "tool": config.TOOL_NAME, "email": config.CONTACT_EMAIL}
    if config.NCBI_API_KEY:
        p["api_key"] = config.NCBI_API_KEY
    p.update(extra)
    return p


def _request(method, endpoint, retries=4, **kw):
    for attempt in range(retries):
        try:
            r = requests.request(method, f"{EUTILS}/{endpoint}", timeout=120, **kw)
            if r.status_code == 429:
                time.sleep(2 + 2 * attempt)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 + 2 * attempt)
    raise RuntimeError("unreachable")


def search(term, mindate=None, maxdate=None, datetype="edat", retmax=100000):
    """Return list of PMIDs. Dates as YYYY/MM/DD. datetype: edat (Entrez add date) or pdat.

    PubMed caps retstart+retmax at 10,000, so large result sets are split by publication year.
    """
    ids, retstart = [], 0
    while True:
        extra = {"term": term, "retmode": "json", "retmax": min(retmax - retstart, 10000), "retstart": retstart}
        if mindate:
            extra.update({"datetype": datetype, "mindate": mindate, "maxdate": maxdate or "3000"})
        r = _request("post", "esearch.fcgi", data=_params(extra))
        res = json.loads(r.text, strict=False)["esearchresult"]  # PubMed JSON can contain raw control chars
        total = int(res.get("count", 0))
        if total > 9999 and not mindate and retstart == 0:
            return _search_by_year(term, retmax)
        ids.extend(res.get("idlist", []))
        retstart += len(res.get("idlist", []))
        if retstart >= total or retstart >= retmax or retstart >= 9999 or not res.get("idlist"):
            break
        time.sleep(0.34)
    return ids


def _search_by_year(term, retmax):
    ids = []
    for y in range(1940, 2031):
        sub = f"({term}) AND {y}[dp]"
        got = search(sub, retmax=10000)
        ids.extend(got)
        time.sleep(0.34)
        if len(ids) >= retmax:
            break
    return list(dict.fromkeys(ids))


def count(term):
    r = _request("get", "esearch.fcgi", params=_params({"term": term, "retmode": "json", "rettype": "count"}))
    return int(r.json()["esearchresult"]["count"])


def _date_from(art):
    ad = art.find(".//ArticleDate")
    if ad is not None and ad.findtext("Year"):
        return f"{ad.findtext('Year')}-{int(ad.findtext('Month') or 1):02d}-{int(ad.findtext('Day') or 1):02d}"
    pd = art.find(".//JournalIssue/PubDate")
    if pd is None:
        return ""
    y = pd.findtext("Year") or (pd.findtext("MedlineDate") or "")[:4]
    if not y or not y[:4].isdigit():
        return ""
    m = pd.findtext("Month") or "1"
    mm = MONTHS.get(m[:3].title(), int(m) if m.isdigit() else 1)
    d = pd.findtext("Day") or "1"
    return f"{y[:4]}-{mm:02d}-{int(d):02d}"


def parse_records(xml_bytes):
    root = etree.fromstring(xml_bytes)
    recs = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//MedlineCitation/PMID")
        a = art.find(".//Article")
        t = a.find("ArticleTitle") if a is not None else None
        title = "".join(t.itertext()).strip() if t is not None else ""
        parts = []
        for x in art.findall(".//Abstract/AbstractText"):
            label = x.get("Label")
            txt = "".join(x.itertext()).strip()
            parts.append(f"{label}: {txt}" if label and label.upper() not in ("UNLABELLED",) else txt)
        abstract = " ".join(parts)
        authors = []
        for au in art.findall(".//AuthorList/Author"):
            ln, ini, coll = au.findtext("LastName"), au.findtext("Initials"), au.findtext("CollectiveName")
            if ln:
                authors.append(f"{ln} {ini or ''}".strip())
            elif coll:
                authors.append(coll)
        doi = pmcid = None
        # Only the article's own ids: PubmedData/ArticleIdList (NOT the ArticleIdLists inside the reference list)
        for aid in art.findall("./PubmedData/ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi" and aid.text:
                doi = aid.text.strip().lower()
            if aid.get("IdType") == "pmc" and aid.text:
                pmcid = aid.text.strip()
        if not doi:
            for el in art.findall(".//Article/ELocationID"):
                if el.get("EIdType") == "doi" and el.text:
                    doi = el.text.strip().lower()
        date = _date_from(art)
        recs.append({
            "pmid": pmid,
            "doi": doi,
            "pmcid": pmcid,
            "title": title,
            "abstract": abstract,
            "journal": art.findtext(".//Journal/Title") or "",
            "journal_abbrev": art.findtext(".//Journal/ISOAbbreviation") or "",
            "year": int(date[:4]) if date[:4].isdigit() else None,
            "date": date,
            "authors": authors,
            "pub_types": [pt.text for pt in art.findall(".//PublicationTypeList/PublicationType") if pt.text],
            "mesh": [m.findtext("DescriptorName") for m in art.findall(".//MeshHeadingList/MeshHeading")],
            "keywords": [k.text.strip() for k in art.findall(".//KeywordList/Keyword") if k.text],
            "language": art.findtext(".//Language") or "",
        })
    return recs


def fetch(pmids, batch=200, progress=None):
    """Fetch full PubMed records for a list of PMIDs. Yields dicts."""
    pmids = list(pmids)
    for i in range(0, len(pmids), batch):
        chunk = pmids[i:i + batch]
        r = _request("post", "efetch.fcgi", data=_params({"id": ",".join(chunk), "retmode": "xml"}))
        for rec in parse_records(r.content):
            yield rec
        if progress:
            progress(min(i + batch, len(pmids)), len(pmids))
        time.sleep(0.34)
