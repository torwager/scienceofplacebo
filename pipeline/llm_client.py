"""Provider-agnostic screening + tagging client for Science of Placebo.

    from pipeline.llm_client import Classifier
    clf = Classifier(provider="openai", model="gpt-5-mini")          # OPENAI_API_KEY
    clf = Classifier(provider="anthropic", model="claude-sonnet-5")   # ANTHROPIC_API_KEY (or `ant auth login`)
    result = clf.classify(paper)   # paper: dict with title/abstract/... -> dict validated against llm_output.schema.json

Both providers get the *same* system prompt, user message, and JSON schema (structured outputs), so results
are comparable and the provider can be swapped by config. Batch helpers submit the same requests through each
provider's Batch API for the 50% discount on backfills.

Dependencies: `openai` (installed), `anthropic` (pip install anthropic — not yet installed on this machine).
"""
from __future__ import annotations

import copy
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

PIPELINE_DIR = Path(__file__).resolve().parent
TAXONOMY_PATH = PIPELINE_DIR / "taxonomy.json"
PROMPT_PATH = PIPELINE_DIR / "prompts" / "classify_v1.md"
OUTPUT_SCHEMA_PATH = PIPELINE_DIR / "schemas" / "llm_output.schema.json"

PROMPT_VERSION = "1.0.0"

# Verified 2026-09-02 (platform.claude.com/docs/en/about-claude/pricing; developers.openai.com/api/docs/pricing).
# USD per 1M tokens: (input, cached_input, output). Batch = 50% of these on both providers.
PRICES = {
    "claude-haiku-4-5": (1.00, 0.10, 5.00),
    "claude-sonnet-5": (2.00, 0.20, 10.00),
    "claude-opus-5": (5.00, 0.50, 25.00),
    "claude-fable-5-1": (10.00, 0.25, 50.00),
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "gpt-5.6-luna": (0.20, 0.02, 1.20),
}


# ----------------------------------------------------------------------------- prompt + schema assembly
def load_taxonomy() -> dict:
    return json.loads(TAXONOMY_PATH.read_text())


def taxonomy_block(tax: dict) -> str:
    lines = []
    for ax in tax["axes"]:
        if ax.get("derived_from"):
            continue  # derived axes (e.g. kind) are computed from other tags, never asked of the model
        kind = "multi" if ax["multi"] else "single"
        lines.append(f"\n[{ax['id']}] ({ax['label']}; {kind})")
        for v in ax["values"]:
            lines.append(f"  {v['id']} — {v['def']}")
    return "\n".join(lines).strip()


def load_prompt_parts() -> tuple[str, str]:
    """Return (system_prompt, user_template) from classify_v1.md."""
    md = PROMPT_PATH.read_text()
    system = md.split("## SYSTEM", 1)[1].split("---\n\n## USER", 1)[0].strip()
    user = md.split("## USER (template)", 1)[1].split("```", 2)[1].strip()
    system = system.replace("{{TAXONOMY_BLOCK}}", taxonomy_block(load_taxonomy()))
    return system, user


def build_output_schema(tax: dict) -> dict:
    """Expand __ENUM:<axis>__ placeholders so enums always match taxonomy.json."""
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    schema.pop("x-note", None)
    enums = {ax["id"]: [v["id"] for v in ax["values"]] for ax in tax["axes"]}

    def walk(node):
        if isinstance(node, dict):
            if "enum" in node and node["enum"] and isinstance(node["enum"][0], str):
                m = re.fullmatch(r"__ENUM:(\w+)__", node["enum"][0])
                if m:
                    node["enum"] = enums[m.group(1)]
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    schema.pop("$schema", None)
    return schema


def render_user_message(paper: dict, full_text: Optional[str] = None, max_fulltext_chars: int = 150_000) -> str:
    authors = ", ".join(a.get("family", "") for a in paper.get("authors", [])[:3]) or "unknown"
    ptypes = ", ".join(paper.get("publication_types", [])) or "unknown"
    mesh = ", ".join(paper.get("mesh_terms", [])[:25]) or "none"
    abstract = paper.get("abstract") or "NO ABSTRACT AVAILABLE"
    parts = [
        "<paper>",
        f"<title>{paper.get('title','')}</title>",
        f"<authors>{authors} et al.</authors>",
        f"<journal>{paper.get('journal','')}</journal>",
        f"<year>{paper.get('year','')}</year>",
        f"<publication_types>{ptypes}</publication_types>",
        f"<mesh_terms>{mesh}</mesh_terms>",
        "<abstract>", abstract, "</abstract>",
    ]
    if full_text:
        ft = full_text[:max_fulltext_chars]
        parts += [f'<full_text truncated_to="{len(ft)} chars">', ft, "</full_text>"]
    parts += ["</paper>", "", "Screen and tag this paper."]
    return "\n".join(parts)


# ----------------------------------------------------------------------------- client
@dataclass
class ClassifyResult:
    data: dict
    provider: str
    model: str
    input_mode: str
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0

    def as_classification(self, taxonomy_version: str) -> dict:
        return {
            "taxonomy_version": taxonomy_version,
            "prompt_version": PROMPT_VERSION,
            "provider": self.provider,
            "model": self.model,
            "input_mode": self.input_mode,
            "classified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **self.data,
            "usage": {**self.usage, "cost_usd": round(self.cost_usd, 5)},
        }


class Classifier:
    def __init__(self, provider: str, model: str, effort: str = "low", max_tokens: int = 2048):
        assert provider in ("anthropic", "openai")
        self.provider, self.model, self.effort, self.max_tokens = provider, model, effort, max_tokens
        self.tax = load_taxonomy()
        self.system, _ = load_prompt_parts()
        self.schema = build_output_schema(self.tax)
        if provider == "anthropic":
            import anthropic  # pip install anthropic
            self._client = anthropic.Anthropic()
        else:
            import openai
            self._client = openai.OpenAI()

    # ---- single call ---------------------------------------------------------------------------
    def classify(self, paper: dict, full_text: Optional[str] = None) -> ClassifyResult:
        user = render_user_message(paper, full_text)
        mode = "full_text" if full_text else ("title_abstract" if paper.get("abstract") else "title_only")
        if self.provider == "anthropic":
            return self._anthropic(user, mode)
        return self._openai(user, mode)

    def _anthropic(self, user: str, mode: str) -> ClassifyResult:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": self.schema}, "effort": self.effort},
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"refusal: {getattr(resp, 'stop_details', None)}")
        text = next(b.text for b in resp.content if b.type == "text")
        u = resp.usage
        usage = {
            "input_tokens": u.input_tokens,
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "output_tokens": u.output_tokens,
        }
        return ClassifyResult(json.loads(text), "anthropic", self.model, mode, usage, self._cost(usage))

    def _openai(self, user: str, mode: str) -> ClassifyResult:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            input=[{"role": "system", "content": self.system}, {"role": "user", "content": user}],
            text={"format": {"type": "json_schema", "name": "placebo_classification", "schema": self.schema, "strict": True}},
            max_output_tokens=self.max_tokens,
        )
        if self.model.startswith("gpt-5"):
            kwargs["reasoning"] = {"effort": {"low": "low", "medium": "medium", "high": "high"}.get(self.effort, "low")}
        else:
            kwargs["temperature"] = 0
        resp = self._client.responses.create(**kwargs)
        u = resp.usage
        cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
        usage = {
            "input_tokens": u.input_tokens - cached,
            "cache_read_input_tokens": cached,
            "cache_creation_input_tokens": 0,
            "output_tokens": u.output_tokens,
        }
        return ClassifyResult(json.loads(resp.output_text), "openai", self.model, mode, usage, self._cost(usage))

    def _cost(self, usage: dict) -> float:
        p = PRICES.get(self.model)
        if not p:
            return 0.0
        inp, cached, out = p
        return (usage["input_tokens"] * inp + usage["cache_read_input_tokens"] * cached
                + usage["cache_creation_input_tokens"] * inp * 1.25 + usage["output_tokens"] * out) / 1e6

    # ---- batch (50% off on both providers) ----------------------------------------------------
    def batch_requests(self, papers: list[dict]) -> list[dict]:
        """Build provider-specific batch request objects keyed by paper id."""
        reqs = []
        for p in papers:
            user = render_user_message(p)
            if self.provider == "anthropic":
                reqs.append({"custom_id": p["id"], "params": {
                    "model": self.model, "max_tokens": self.max_tokens,
                    "system": [{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
                    "messages": [{"role": "user", "content": user}],
                    "output_config": {"format": {"type": "json_schema", "schema": self.schema}, "effort": self.effort},
                }})
            else:
                reqs.append({"custom_id": p["id"], "method": "POST", "url": "/v1/responses", "body": {
                    "model": self.model,
                    "input": [{"role": "system", "content": self.system}, {"role": "user", "content": user}],
                    "text": {"format": {"type": "json_schema", "name": "placebo_classification", "schema": self.schema, "strict": True}},
                    "max_output_tokens": self.max_tokens,
                    **({"reasoning": {"effort": "low"}} if self.model.startswith("gpt-5") else {"temperature": 0}),
                }})
        return reqs


def estimate_cost_per_1000(model: str, in_tokens: int = 3000, cached_frac: float = 0.8, out_tokens: int = 450,
                           batch: bool = False) -> float:
    inp, cached, out = PRICES[model]
    per = (in_tokens * (1 - cached_frac) * inp + in_tokens * cached_frac * cached + out_tokens * out) / 1e6
    return round(per * 1000 * (0.5 if batch else 1.0), 2)


if __name__ == "__main__":
    system, _ = load_prompt_parts()
    schema = build_output_schema(load_taxonomy())
    print(f"system prompt chars={len(system)} (~{len(system)//4} tokens)")
    print("enum sizes:", {k: len(v["items"]["enum"]) if "items" in v else len(v["enum"])
                          for k, v in schema["properties"]["tags"]["properties"].items()})
    for m in PRICES:
        print(f"{m:18s} per-1000 (title+abstract, 80% cache hit) ${estimate_cost_per_1000(m):6.2f}   batch ${estimate_cost_per_1000(m, batch=True):6.2f}   full-text(12k in) ${estimate_cost_per_1000(m, in_tokens=12000, cached_frac=0.2):6.2f}")
