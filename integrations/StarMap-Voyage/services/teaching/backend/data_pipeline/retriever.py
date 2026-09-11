"""
Retriever: Few-shot example selection + RAG section retrieval.
Orchestrates the full retrieval pipeline for教案 generation.
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Tuple

from .embedder import VectorStore, embed_texts


DATA_DIR = os.environ.get(
    "STARMAP_TEACHING_DATA_DIR",
    str(Path(__file__).resolve().parents[2] / "data" / "processed"),
)

# Lazy-loaded stores
_section_store: VectorStore = None
_full_manual_store: VectorStore = None
_fewshot_examples: List[str] = None


def _get_section_store() -> VectorStore:
    global _section_store
    if _section_store is None:
        _section_store = VectorStore.load(f"{DATA_DIR}/section_index")
    return _section_store


def _get_full_manual_store() -> VectorStore:
    global _full_manual_store
    if _full_manual_store is None:
        _full_manual_store = VectorStore.load(f"{DATA_DIR}/full_manual_index")
    return _full_manual_store


def _get_fewshot_examples() -> List[str]:
    global _fewshot_examples
    if _fewshot_examples is None:
        path = f"{DATA_DIR}/fewshot_chunks.json"
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                _fewshot_examples = json.load(f)
        else:
            _fewshot_examples = []
    return _fewshot_examples


def retrieve_fewshot_examples(query: str, top_k: int = 2) -> List[str]:
    """
    Retrieve the most relevant teacher manuals as Few-shot examples.
    Returns list of compact example texts.
    """
    fewshot_chunks = _get_fewshot_examples()
    if not fewshot_chunks:
        return []

    store = _get_full_manual_store()
    if store is None or len(store) == 0:
        # Fallback: return all fewshot examples (limited)
        return fewshot_chunks[:top_k]

    query_emb = embed_texts([query])[0]
    results = store.search(query_emb, top_k=top_k)

    examples = []
    for meta, score in results:
        # Find matching fewshot chunk by title
        title = meta.get("doc_title", "")
        for fc in fewshot_chunks:
            if title in fc:
                examples.append(fc)
                break

    if len(examples) < top_k:
        # Fill with remaining fewshot examples
        for fc in fewshot_chunks:
            if fc not in examples:
                examples.append(fc)
            if len(examples) >= top_k:
                break

    return examples[:top_k]


def retrieve_relevant_sections(query: str, top_k: int = 5) -> List[Tuple[Dict, float]]:
    """
    Retrieve relevant sections from teaching plans for RAG context.
    Useful for finding specific activity designs, assessment methods, etc.
    """
    store = _get_section_store()
    if store is None or len(store) == 0:
        return []

    query_emb = embed_texts([query])[0]
    return store.search(query_emb, top_k=top_k)


def retrieve_best_student_manual(teacher_doc_title: str) -> Dict:
    """Find the matching student manual for a teacher manual."""
    section_store = _get_section_store()
    if section_store is None:
        return None

    # Search for student manual with similar title
    clean_title = teacher_doc_title.replace("教师手册", "").replace("教学手册", "").strip()

    for meta in section_store.metadata:
        if meta["doc_type"] == "student" and clean_title in meta.get("doc_title", ""):
            return meta

    return None


def get_all_project_titles() -> List[str]:
    """Get all available project titles for the bubble UI."""
    store = _get_full_manual_store()
    if store is None:
        return []
    titles = list(set(m.get("doc_title", "") for m in store.metadata if m.get("doc_title")))
    return sorted(titles)
