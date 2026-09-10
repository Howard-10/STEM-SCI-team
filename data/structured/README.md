# Structured research-assistant knowledge assets

This directory adds a research-assistant layer above the shared Physics-STEM
retrieval corpus.

## Paper cards

`physics_stem_paper_cards.jsonl` contains one automatically assembled `PaperCard`
for each paper in `physics_stem_v1`. Facets are derived from the published sparse
graph and retain source chunk references. The cards are navigation and synthesis
inputs only; every card is `model_generated_unverified` until a source workflow
checks the corresponding PDF.

## Intended next sources

`research_assistant_knowledge_registry.json` records high-value research-method,
ethics, measurement, and reporting sources. These are operational references for
an assistant that plans, screens, analyzes, and writes research. They are not
substitutes for domain evidence.

## Discovery candidates

`data/catalogs/physics_stem/discovery_candidates.json` is a metadata-only list
from OpenAlex. It is deliberately excluded from the formal corpus until the
full text, license, hash, locator, and verification checks pass.

## Task bank

`research_assistant_task_bank.json` contains 30 deterministic task templates
across screening, evidence synthesis, study design, data audit, writing review,
and reproducibility. These are product workflow assets, not literature claims.

`knowledge_asset_summary.json` is the bounded summary for a demo/status panel.

The local-only `data/local/discovery_fulltext/` directory is populated by
`tools/download_discovery_fulltext.py`. It is discovery-only and does not alter
the formal `physics_stem_v1` manifest.

Use `tools/reconcile_discovery_manifest.py` after interrupted downloads to
rebuild the local PDF/hash/page-count manifest from files that actually exist.

Use `tools/build_discovery_chunks.py` to create page-aware chunks for the local
discovery PDFs. These chunks are explicitly not formal evidence.

Use `python tools/query_discovery_chunks.py "generative AI STEM misconceptions"`
for a local, API-key-free discovery query with page references.

Use `python tools/build_discovery_demo_report.py` to generate a 10-question
source-linked demonstration report for the research-assistant workflow.
