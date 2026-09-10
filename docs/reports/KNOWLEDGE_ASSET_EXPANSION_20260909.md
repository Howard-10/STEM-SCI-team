# Knowledge asset expansion (2026-09-09)

## What was added

- `data/structured/physics_stem_paper_cards.jsonl`: 122 source-linked PaperCard
  candidates assembled from the existing sparse graph.
- `data/structured/research_assistant_knowledge_registry.json`: 16 research
  method, reporting, ethics, measurement, and workflow references suitable for
  a research-assistant product.
- `data/catalogs/physics_stem/discovery_candidates.json`: 111 OpenAlex discovery
  candidates across Physics-STEM, generative AI, learning analytics, and
  research-method queries.
- `data/structured/research_assistant_task_bank.json`: 30 reusable research
  assistant task templates across six workflow categories.
- `data/local/discovery_fulltext/` (local-only): 6 successfully parsed open-
  access PDFs and 469 page-aware chunks, with a SHA256 manifest.

## Verification boundary

The PaperCards and graph-derived fields are `model_generated_unverified`. The
OpenAlex records are `metadata_only` and cannot support formal claims. A future
ingestion must obtain the full text, check license, compute SHA256, build a page
locator, and then promote only exact source matches to `source_verified`.

## Demonstration value

The new assets make the knowledge layer visible as more than a vector index:
paper identity -> structured research facets -> evidence references -> method
and workflow sources -> discovery candidates. They also keep formal evidence
and exploratory discovery explicitly separate.

The generated 10-question demonstration is in
`docs/reports/DISCOVERY_FULLTEXT_DEMO_20260909.md`.

## Runtime presentation

The research workspace exposes the bounded asset counts and discovery-only
full-text manifest through `/api/v1/knowledge-assets/summary` and
`/api/v1/knowledge-assets/discovery`. The Knowledge Base pane renders the
method/workflow records, assistant task templates, OpenAlex candidates, and
the six downloaded full-text records as a separate discovery layer; it does
not add them to the formal corpus or bypass the evidence gate.

## Rebuild

```powershell
python tools/build_structured_knowledge_assets.py
```
