"""PubMed recall audit: alternative queries that the main discovery query does not cover.
Candidates never seen by the pipeline are fetched, prefiltered, classified and merged. Usage: [--max-llm N] [--count-only]"""
import json, sys, time
sys.path.insert(0, ".")
from pipeline import db, pubmed, classify, ingest, openalex

QUERIES = {
  "placebo_vs_no_treatment": 'placebo[tiab] AND ("no treatment"[tiab] OR "no-treatment"[tiab] OR "natural history"[tiab] OR "waiting list"[tiab] OR "wait-list"[tiab] OR "waitlist"[tiab] OR "untreated control"[tiab] OR "treatment as usual"[tiab])',
  "expectancy_titles": '(expectanc*[ti] OR expectation*[ti]) AND (pain[tiab] OR analgesi*[tiab] OR symptom*[tiab] OR treatment[tiab] OR outcome*[tiab] OR side effect*[tiab] OR "adverse event*"[tiab])',
  "conditioning_titles": '(conditioning[ti] OR conditioned[ti]) AND (analgesi*[tiab] OR immun*[tiab] OR "drug response*"[tiab] OR placebo[tiab] OR pharmacolog*[tiab] OR hypoalgesi*[tiab] OR hyperalgesi*[tiab])',
  "suggestion_titles": '(suggestion*[ti] OR "verbal suggestion*"[tiab] OR "verbal instruction*"[tiab]) AND (pain[tiab] OR symptom*[tiab] OR itch[tiab] OR nausea[tiab] OR treatment[tiab])',
  "sham_effects": '(sham[ti]) AND ("sham effect*"[tiab] OR "sham response*"[tiab] OR "placebo effect*"[tiab] OR "placebo response*"[tiab] OR "no treatment"[tiab] OR "waiting list"[tiab] OR expectan*[tiab])',
  "context_meaning": '"meaning response"[tiab] OR "contextual effect*"[tiab] OR "context effect*"[tiab] OR "contextual factor*"[ti] OR "therapeutic context"[tiab] OR "treatment context"[tiab] OR "healing context"[tiab] OR "placebo research"[tiab]',
  "open_hidden_balanced": '"open-hidden"[tiab] OR "open hidden"[tiab] OR "hidden administration"[tiab] OR "covert administration"[tiab] OR "balanced placebo"[tiab] OR "told drug"[tiab] OR "told placebo"[tiab]',
  "brain_placebo": '(placebo[ti] OR placebos[ti]) AND (fMRI[tiab] OR "functional magnetic resonance"[tiab] OR PET[tiab] OR "positron emission"[tiab] OR EEG[tiab] OR "brain imaging"[tiab] OR neuroimaging[tiab] OR dopamin*[tiab] OR opioid*[tiab] OR naloxone[tiab] OR spinal[tiab])',
  "placebo_mesh_all": '"Placebo Effect"[MeSH] OR "Nocebo Effect"[MeSH] OR "Placebos"[MeSH:NoExp]',
  "placebo_analgesia_hypoalgesia": 'placebo*[tiab] AND (analgesi*[tiab] OR hypoalgesi*[tiab] OR hyperalgesi*[tiab]) AND (expectan*[tiab] OR conditioning[tiab] OR suggestion[tiab] OR mechanism*[tiab])',
  "placebo_response_predictors": '("placebo response"[tiab] OR "placebo responder*"[tiab] OR "placebo effect*"[tiab]) AND (predict*[tiab] OR moderat*[tiab] OR mediat*[tiab] OR magnitude[tiab] OR trend*[tiab] OR "meta-analysis"[tiab] OR determinant*[tiab])',
}
BIG = {"placebo_vs_no_treatment", "expectancy_titles", "conditioning_titles", "suggestion_titles", "context_meaning", "brain_placebo", "placebo_mesh_all"}
PRESCREEN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["keep"], "properties": {"keep": {"type": "array", "items": {"type": "boolean"}}}}
PRESCREEN_SYS = ("You triage PubMed records for a bibliography of studies OF placebo and nocebo effects and responses (the causal effect of "
    "treatment context, expectation, suggestion or conditioning on health outcomes; the response in placebo/sham arms as an object of study; "
    "their mechanisms and moderators; reviews of these). From TITLE and JOURNAL only, answer true if the paper could plausibly be such a study "
    "and deserves a full-abstract screen; answer false for ordinary drug/device efficacy trials that merely use a placebo comparator, and for "
    "papers on unrelated topics. Return JSON {keep: [bool,...]} with exactly one boolean per numbered line, in order.")


def title_prescreen(recs):
    """Cheap LLM pass on titles, 40 per call, threaded. Returns the subset worth a full screen."""
    from concurrent.futures import ThreadPoolExecutor
    clf = classify.get_classifier(); keep = []
    def one(chunk):
        user = "\n".join(f"{i + 1}. {r['title']} ({r.get('journal_abbrev') or r.get('journal') or ''}, {r.get('year') or ''})" for i, r in enumerate(chunk))
        for attempt in range(6):
            try:
                if clf.provider == "anthropic":
                    resp = clf._client.messages.create(model=clf.model, max_tokens=300, system=PRESCREEN_SYS, messages=[{"role": "user", "content": user}], output_config={"effort": "low", "format": {"type": "json_schema", "schema": PRESCREEN_SCHEMA}})
                    ks = json.loads(next(b.text for b in resp.content if b.type == "text"))["keep"]
                else:
                    resp = clf._client.responses.create(model=clf.model, input=[{"role": "system", "content": PRESCREEN_SYS}, {"role": "user", "content": user}], text={"format": {"type": "json_schema", "name": "keep", "schema": PRESCREEN_SCHEMA, "strict": True}}, max_output_tokens=300, **({"reasoning": {"effort": "low"}} if clf.model.startswith("gpt-5") else {}))
                    ks = json.loads(resp.output_text)["keep"]
                if len(ks) == len(chunk):
                    return [r for r, k in zip(chunk, ks) if k]
                return chunk
            except Exception as e:  # noqa: BLE001
                time.sleep((20 if "429" in str(e) else 5) * (attempt + 1))
        return chunk
    chunks = [recs[i:i + 40] for i in range(0, len(recs), 40)]
    with ThreadPoolExecutor(12) as ex:
        for res in ex.map(one, chunks):
            keep.extend(res)
    return keep


args = sys.argv[1:]
MAX_LLM = int(args[args.index("--max-llm") + 1]) if "--max-llm" in args else 4000
papers = db.load_all(); screened = db.load_screened(); by_pmid, by_title = db.index_by_alt_ids(papers)
cands = json.load(open("work/candidates_pubmed.json"))
seen_pmids = set(cands) | {str(v.get("pmid")) for v in screened.values() if v.get("pmid")} | set(by_pmid)
new_ids, per_query, big_ids = set(), {}, set()
for name, q in QUERIES.items():
    ids = pubmed.search(q)
    fresh = [i for i in ids if i not in seen_pmids]
    per_query[name] = (len(ids), len(fresh)); new_ids |= set(fresh)
    if name in BIG:
        big_ids |= set(fresh)
    print(f"{name:32s} hits {len(ids):>6}  never seen {len(fresh):>5}", flush=True); time.sleep(0.4)
print("total never-seen candidates:", len(new_ids), flush=True)
if "--count-only" in args:
    sys.exit(0)
stats = {"fetched": 0, "prefiltered": 0, "classified": 0, "core": 0, "adjacent": 0, "review": 0, "exclude": 0, "errors": 0, "cost": 0.0}
todo = sorted(new_ids, key=int, reverse=True)
recs = list(pubmed.fetch(todo, progress=lambda i, n: print(f"fetched {i}/{n}", flush=True) if i % 2000 < 200 else None))
stats["fetched"] = len(recs)
json.dump({r["pmid"]: r for r in recs}, open("work/audit_pubmed_candidates.json", "w"))
small_only = {i for i in new_ids if i not in big_ids}
direct = [r for r in recs if r["pmid"] in small_only and not classify.prefilter(r)]
big = [r for r in recs if r["pmid"] not in small_only and not classify.prefilter(r)]
print(f"direct full screen: {len(direct)}; title pre-screen: {len(big)}", flush=True)
kept = title_prescreen(big)
print(f"title pre-screen kept {len(kept)} of {len(big)}", flush=True)
dropped = {r["pmid"] for r in big} - {r["pmid"] for r in kept}
for r in big:
    if r["pmid"] in dropped:
        screened[db.record_id(r)] = {"scope": "exclude", "pmid": r["pmid"], "date": time.strftime("%Y-%m-%d"), "reason": "title_prescreen", "via": "pubmed_audit"}
recs = direct + kept
for rec in recs:
    rid = db.record_id(rec)
    if rid in screened or db.find_existing(rec, papers, by_pmid, by_title):
        continue
    reason = classify.prefilter(rec)
    if reason:
        screened[rid] = {"scope": "exclude", "pmid": rec["pmid"], "date": time.strftime("%Y-%m-%d"), "reason": reason, "via": "pubmed_audit"}; stats["prefiltered"] += 1; continue
    if stats["classified"] >= MAX_LLM:
        break
    rec["sources"] = ["pubmed_audit"]
    try:
        cls, scope = classify.classify_record(rec)
    except Exception as e:  # noqa: BLE001
        stats["errors"] += 1; print("error", rid, str(e)[:100]); continue
    stats["classified"] += 1; stats[scope] += 1; stats["cost"] += cls.get("usage", {}).get("cost_usd", 0)
    screened[rid] = {"scope": scope, "pmid": rec["pmid"], "date": time.strftime("%Y-%m-%d"), "reason": cls["screening"].get("exclusion_reason"), "via": "pubmed_audit"}
    if scope in ("core", "adjacent", "review"):
        try: openalex.enrich(rec)
        except Exception: pass  # noqa: BLE001
        ingest.upsert(papers, ingest.make_record(rec, cls, scope, date_added=(rec.get("date") or time.strftime("%Y-%m-%d"))[:10]), by_pmid, by_title)
    if stats["classified"] % 200 == 0:
        db.save_all(papers); db.save_screened(screened); print(stats, flush=True)
db.save_all(papers); db.save_screened(screened)
print("PUBMED_AUDIT_DONE", stats, "per_query", per_query, flush=True)
