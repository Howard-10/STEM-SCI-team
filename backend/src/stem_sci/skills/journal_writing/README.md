# Journal writing runtime skill

This package applies YAML-defined target-journal rules and general STEM writing
patterns to the existing claim-safe manuscript pipeline. It does not retrieve
literature, parse PDFs, create PaperCards, or perform evidence retrieval.

`patterns/STEM_empirical_research_framework.yaml` is the default empirical
research writing skill distilled from the local Word guide. It is injected into
paper-writing prompts even when no target journal is selected, and it remains
writing guidance only: it cannot authorize new facts, citations, methods,
statistics, or causal claims.

Add a journal by placing a schema-compatible YAML file in `profiles/`. Canonical
names, aliases, article types, sections, style emphasis, format rules, and asset
paths must remain in YAML rather than Python code.
