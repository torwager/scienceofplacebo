"""Screen + tag a candidate record with the LLM and derive site-facing fields.

scope:  core      -> shown in feed and database (empirical/review study of placebo or nocebo effects/responses)
        adjacent  -> in database, filterable, off the default feed (attitudes, ethics, methodology, protocols, letters)
        exclude   -> not on the site (placebo as control only, off-topic, not scientific)
        review    -> model was uncertain; kept in a review queue, not on the site
"""
import os
from .llm_client import Classifier, PROMPT_VERSION, load_taxonomy

SKIP_PUB_TYPES = {"Comment", "Editorial", "Letter", "News", "Published Erratum", "Retracted Publication",
                  "Retraction of Publication", "Newspaper Article", "Interview", "Biography", "Portrait",
                  "Autobiography", "Bibliography", "Directory", "Legal Case", "Patient Education Handout"}
ADJACENT_TYPES = {"editorial_letter", "protocol"}

_clf = None


def get_classifier():
    global _clf
    if _clf is None:
        provider = os.environ.get("SOP_LLM_PROVIDER") or (
            "anthropic" if (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")) else "openai")
        model = os.environ.get("SOP_LLM_MODEL") or {"anthropic": "claude-sonnet-5", "openai": "gpt-5-mini"}[provider]
        _clf = Classifier(provider=provider, model=model, effort=os.environ.get("SOP_LLM_EFFORT", "low"))
    return _clf


def prefilter(rec):
    """Cheap rule prefilter. Returns None if the record should go to the LLM, else an exclusion reason."""
    if set(rec.get("pub_types") or []) & SKIP_PUB_TYPES and "Journal Article" not in (rec.get("pub_types") or []):
        return "pub_type"
    if rec.get("language") and rec["language"] not in ("eng", "en", ""):
        return "language"
    if not rec.get("title"):
        return "no_title"
    return None


def to_llm_paper(rec):
    return {
        **rec,
        "authors": [{"family": a.split()[0] if isinstance(a, str) else a.get("family", "")} for a in rec.get("authors") or []],
        "publication_types": rec.get("pub_types") or rec.get("publication_types") or [],
        "mesh_terms": rec.get("mesh") or rec.get("mesh_terms") or [],
    }


def derive_scope(data):
    s = data["screening"]
    if s["decision"] == "exclude":
        return "exclude"
    if s["decision"] == "uncertain" or s["confidence"] < 0.5:
        return "review"
    tags = data["tags"]
    focus = [f for f in tags.get("study_focus") or [] if f != "placebo_science_other"]
    if tags.get("article_type") in ADJACENT_TYPES or not focus:
        return "adjacent"
    return "core"


def classify_record(rec, full_text=None):
    """Returns (classification dict for storage, scope)."""
    res = get_classifier().classify(to_llm_paper(rec), full_text=full_text)
    cls = res.as_classification(load_taxonomy()["taxonomy_version"])
    scope = derive_scope(res.data)
    return cls, scope
