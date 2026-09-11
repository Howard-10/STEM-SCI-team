---
name: journal-writing
description: Analyze STEM-education journal exemplars and apply official journal rules, observed journal patterns, methodology patterns, and general article patterns when planning or reviewing research articles.
---

# STEM Journal Writing

Treat this directory as the skill root. Preserve the distinction between evidence types and resolve conflicts in this order:

1. Official journal rules in `journals/`.
2. The STEM empirical research framework in `patterns/general/STEM_empirical_research_framework.yaml`.
3. Observed exemplar patterns in `patterns/journals/`.
4. Methodology patterns in `patterns/methodology/`.
5. The general STEM research-article pattern in `patterns/general/`.

Observed exemplar patterns describe a sample; never present them as submission requirements. Use `null` when a paper does not provide enough evidence for a paper-card field.

The empirical framework is distilled from the local Word guide `STEM empirical research writing mode guide docx`. It is a default structural and quality skill for STEM empirical manuscript candidates, not a source of facts. Never add participants, sample sizes, findings, citations, or causal claims merely to satisfy the framework.

For exemplar analysis, run the scripts in `scripts/`. The scripts accept both the existing `examplars/` layout and the conventional `exemplars/` layout, including flat PDFs and `papers/` subdirectories. Validate generated YAML with `scripts/validate_patterns.py` before using it.
