"""Science of Placebo literature pipeline.

Modules:
  pubmed     - E-utilities search + fetch (primary discovery source)
  europepmc  - Europe PMC search (preprints + OA full text) and enrichment
  openalex   - OpenAlex / Unpaywall enrichment (OA PDF url, citation counts)
  jips       - JIPS (jips.online) seed scraper
  llm        - provider-agnostic LLM client (Anthropic preferred, OpenAI fallback)
  classify   - screening + tagging prompt and schema
  db         - JSON database read/write, dedup and merge
  run_daily  - entry point used by the GitHub Action
"""
