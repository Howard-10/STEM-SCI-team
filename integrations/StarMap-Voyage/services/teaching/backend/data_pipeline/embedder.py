"""
Embedding & vector store: embed chunks and store in FAISS for retrieval.
Uses SiliconFlow embedding API (BAAI/bge-large-zh-v1.5).
"""
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests


# ---- Config ----
EMBEDDING_API_URL = "https://api.siliconflow.cn/v1/embeddings"
EMBEDDING_MODEL = "BAAI/bge-large-zh-v1.5"
API_KEY = os.environ.get("SILICONFLOW_API_KEY", "").strip()
BATCH_SIZE = 4
VECTOR_DIM = 1024


def embed_texts(texts: List[str], api_key: str = None) -> List[List[float]]:
    """Embed a list of texts using SiliconFlow API."""
    key = api_key or API_KEY
    all_embeddings = []

    # Truncate texts to 500 chars (bge-large-zh-v1.5 max is 512 tokens)
    texts = [t[:500] for t in texts]

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        resp = requests.post(
            EMBEDDING_API_URL,
            json={
                "model": EMBEDDING_MODEL,
                "input": batch,
                "encoding_format": "float"
            },
            headers={"Authorization": f"Bearer {key}"}
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Embedding API error: {resp.status_code} {resp.text}")

        data = resp.json()
        batch_embeddings = [item["embedding"] for item in data["data"]]
        all_embeddings.extend(batch_embeddings)

        if i + BATCH_SIZE < len(texts):
            time.sleep(0.1)

    return all_embeddings


class VectorStore:
    """Simple FAISS-like vector store using numpy (no FAISS dependency)."""

    def __init__(self, dim: int = VECTOR_DIM):
        self.dim = dim
        self.vectors: np.ndarray = None
        self.metadata: List[Dict] = []

    def add(self, embeddings: List[List[float]], metadata: List[Dict]):
        vecs = np.array(embeddings, dtype=np.float32)
        # Normalize for cosine similarity
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs = vecs / norms

        if self.vectors is None:
            self.vectors = vecs
        else:
            self.vectors = np.vstack([self.vectors, vecs])
        self.metadata.extend(metadata)

    def search(self, query_embedding: List[float], top_k: int = 5) -> List[Tuple[Dict, float]]:
        """Cosine similarity search."""
        if self.vectors is None:
            return []

        query = np.array(query_embedding, dtype=np.float32)
        query = query / (np.linalg.norm(query) or 1.0)

        scores = np.dot(self.vectors, query)
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] > 0.3:  # minimum similarity threshold
                results.append((self.metadata[idx], float(scores[idx])))
        return results

    def save(self, path: str):
        np.save(f"{path}_vectors.npy", self.vectors)
        with open(f"{path}_meta.json", "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "VectorStore":
        store = cls()
        vectors_path = f"{path}_vectors.npy"
        meta_path = f"{path}_meta.json"
        if os.path.exists(vectors_path) and os.path.exists(meta_path):
            store.vectors = np.load(vectors_path)
            with open(meta_path, "r", encoding="utf-8") as f:
                store.metadata = json.load(f)
            store.dim = store.vectors.shape[1]
        return store

    def __len__(self):
        return len(self.metadata) if self.metadata else 0


def build_index(chunks: List[Dict], store_path: str, api_key: str = None) -> VectorStore:
    """Build vector store from chunks."""
    texts = [c["content"] for c in chunks]
    print(f"Embedding {len(texts)} chunks using {EMBEDDING_MODEL}...")

    embeddings = embed_texts(texts, api_key)
    print(f"Got {len(embeddings)} embeddings")

    store = VectorStore()
    store.add(embeddings, chunks)
    store.save(store_path)
    print(f"Vector store saved to {store_path} ({len(store)} vectors)")

    return store


if __name__ == "__main__":
    # Build both section-level and full-manual indexes
    data_dir = os.environ.get(
        "STARMAP_TEACHING_DATA_DIR",
        str(Path(__file__).resolve().parents[2] / "data" / "processed"),
    )

    # Build section chunks index (for RAG)
    section_path = f"{data_dir}/section_chunks.json"
    if os.path.exists(section_path):
        with open(section_path, "r", encoding="utf-8") as f:
            section_chunks = json.load(f)
        build_index(section_chunks, f"{data_dir}/section_index")

    # Build full manual index (for Few-shot retrieval)
    full_path = f"{data_dir}/full_manual_chunks.json"
    if os.path.exists(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            full_chunks = json.load(f)
        build_index(full_chunks, f"{data_dir}/full_manual_index")
