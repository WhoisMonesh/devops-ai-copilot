# agent/knowledge_base.py - ChromaDB-backed Knowledge Base
# Stores runbooks, SOPs, incident postmortems, config snippets as vector embeddings
# for semantic search via LLM.
#
# Architecture:
#   ChromaDB (persistent, local filesystem) -> collection per category
#   Ollama (nomic-embed-text) for embedding generation
#   TF-IDF fallback when Ollama is unreachable
#
# Collections:
#   runbooks     - Step-by-step operational procedures
#   incidents    - Postmortems, RCA documents, alert runbooks
#   configs     - Config snippets, manifest files, schema docs
#   sops        - Standard Operating Procedures
#   kb          - General knowledge base articles
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# ChromaDB is optional — KB degrades gracefully if not installed
_CHROMA_AVAILABLE = False
_chroma_client: Optional[Any] = None
_chroma_lock = threading.Lock()

# Embedding config
_EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
_EMBED_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")


def _get_chroma_client() -> Any:
    """Lazily initialise ChromaDB persistent client."""
    global _chroma_client, _CHROMA_AVAILABLE
    if _chroma_client is None:
        with _chroma_lock:
            if _chroma_client is None:
                try:
                    import chromadb
                    db_path = os.getenv("CHROMA_DB_PATH", "/var/lib/devops-ai/chroma")
                    os.makedirs(db_path, exist_ok=True)
                    _chroma_client = chromadb.PersistentClient(path=db_path)
                    _CHROMA_AVAILABLE = True
                    logger.info("ChromaDB client initialised at %s", db_path)
                except ImportError:
                    logger.warning("ChromaDB not installed. KB search will use TF-IDF fallback.")
                    _chroma_client = None
                except Exception as exc:
                    logger.error("Failed to init ChromaDB: %s", exc)
                    _chroma_client = None
    return _chroma_client


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings via Ollama nomic-embed-text.
    Falls back to local TF-IDF if Ollama is unreachable.
    """
    try:
        url = f"{_EMBED_URL}/api/embeddings"
        embeddings = []
        for text in texts:
            resp = requests.post(url, json={"model": _EMBED_MODEL, "prompt": text}, timeout=30)
            resp.raise_for_status()
            embeddings.append(resp.json().get("embedding", []))
        return embeddings
    except Exception as exc:
        logger.warning("Ollama embedding failed, using TF-IDF fallback: %s", exc)
        return _local_embed_fallback(texts)


def _local_embed_fallback(texts: list[str]) -> list[list[float]]:
    """Local TF-IDF-style embedding for offline use."""
    import hashlib
    vectors = []
    for text in texts:
        tokens = text.lower().split()
        vec = [0.0] * 256
        for i, tok in enumerate(tokens[:256]):
            h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
            vec[i % 256] += (h % 1000) / 1000.0
        norm = (sum(v * v for v in vec) ** 0.5) or 1.0
        vectors.append([v / norm for v in vec])
    return vectors


# Collection name constants
COLLECTION_RUNBOOKS  = "runbooks"
COLLECTION_INCIDENTS = "incidents"
COLLECTION_CONFIGS   = "configs"
COLLECTION_SOPS      = "sops"
COLLECTION_KB        = "kb"

ALL_COLLECTIONS = [
    COLLECTION_RUNBOOKS,
    COLLECTION_INCIDENTS,
    COLLECTION_CONFIGS,
    COLLECTION_SOPS,
    COLLECTION_KB,
]


def _utc_now() -> str:
    """Return UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class KnowledgeEntry:
    """Represents a single entry in the knowledge base."""
    id: str
    content: str
    title: str
    collection: str
    metadata: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    tags: list[str] = field(default_factory=list)
    author: str = field(default_factory=lambda: os.getenv("KB_DEFAULT_AUTHOR", "devops-ai"))


def _get_or_create_collection(name: str) -> Any:
    """Get or create a ChromaDB collection."""
    client = _get_chroma_client()
    if client is None:
        raise RuntimeError("ChromaDB not available")
    return client.get_or_create_collection(
        name=name,
        metadata={"description": f"DevOps AI knowledge base – {name}"},
    )


def add_entry(entry: KnowledgeEntry) -> str:
    """Add a KB entry with embedding. Returns entry ID."""
    collection = _get_or_create_collection(entry.collection)
    embedding = _embed_texts([entry.content])[0]

    doc_metadata = {
        "title": entry.title,
        "collection": entry.collection,
        "author": entry.author,
        "tags": json.dumps(entry.tags),
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        **entry.metadata,
    }

    collection.add(
        ids=[entry.id],
        documents=[entry.content],
        embeddings=[embedding],
        metadatas=[doc_metadata],
    )
    logger.info("Added KB entry id=%s collection=%s title=%s", entry.id, entry.collection, entry.title)
    return entry.id


def search_entries(
    query: str,
    collection: Optional[str] = None,
    n_results: int = 5,
    filters: Optional[dict] = None,
) -> list[dict]:
    """Semantic search across KB entries. Returns list of matched entries."""
    query_embedding = _embed_texts([query])[0]
    collections_to_search = [collection] if collection else list(ALL_COLLECTIONS)
    all_results = []

    for coll_name in collections_to_search:
        try:
            coll = _get_or_create_collection(coll_name)
        except Exception:
            continue

        results = coll.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=filters,
            include=["documents", "metadatas", "distances"],
        )

        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]

        for i, entry_id in enumerate(ids):
            if not docs or i >= len(docs):
                continue
            similarity = max(0.0, 1.0 - (dists[i] / 2.0)) if i < len(dists) else 0.0
            meta = metas[i] if i < len(metas) else {}
            all_results.append({
                "id": entry_id,
                "title": meta.get("title", entry_id),
                "content": docs[i],
                "collection": meta.get("collection", coll_name),
                "author": meta.get("author", "unknown"),
                "tags": json.loads(meta.get("tags", "[]")),
                "similarity": round(similarity, 4),
                "created_at": meta.get("created_at", ""),
                "updated_at": meta.get("updated_at", ""),
            })

    all_results.sort(key=lambda x: x["similarity"], reverse=True)
    return all_results[: n_results * len(collections_to_search)]


def get_entry(entry_id: str, collection: str) -> Optional[dict]:
    """Retrieve a single entry by ID."""
    try:
        coll = _get_or_create_collection(collection)
        results = coll.get(ids=[entry_id], include=["documents", "metadatas"])
        if not results or not results.get("ids"):
            return None
        meta = results["metadatas"][0] if results.get("metadatas") else {}
        return {
            "id": entry_id,
            "content": results["documents"][0] if results.get("documents") else "",
            "title": meta.get("title", entry_id),
            "collection": collection,
            "author": meta.get("author", ""),
            "tags": json.loads(meta.get("tags", "[]")),
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at", ""),
        }
    except Exception as exc:
        logger.error("get_entry(%s, %s) failed: %s", entry_id, collection, exc)
        return None


def update_entry(
    entry_id: str,
    collection: str,
    content: str = "",
    title: str = "",
    tags: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> bool:
    """Update an existing entry. Re-embeds automatically."""
    try:
        coll = _get_or_create_collection(collection)
        new_embedding = _embed_texts([content])[0]
        updates: dict[str, Any] = {
            "documents": [content],
            "embeddings": [new_embedding],
            "metadatas": [{"title": title, "updated_at": _utc_now()}],
        }
        if tags is not None:
            updates["metadatas"][0]["tags"] = json.dumps(tags)
        if metadata:
            updates["metadatas"][0].update(metadata)
        coll.update(ids=[entry_id], **updates)
        logger.info("Updated KB entry %s in %s", entry_id, collection)
        return True
    except Exception as exc:
        logger.error("update_entry(%s) failed: %s", entry_id, exc)
        return False


def delete_entry(entry_id: str, collection: str) -> bool:
    """Delete an entry from the knowledge base."""
    try:
        coll = _get_or_create_collection(collection)
        coll.delete(ids=[entry_id])
        logger.info("Deleted KB entry %s from %s", entry_id, collection)
        return True
    except Exception as exc:
        logger.error("delete_entry(%s) failed: %s", exc)
        return False


def list_entries(collection: str, limit: int = 50) -> list[dict]:
    """List entries in a collection, sorted by updated_at descending."""
    try:
        coll = _get_or_create_collection(collection)
        results = coll.get(include=["metadatas"])
        if not results or not results.get("ids"):
            return []
        entries = []
        for i, eid in enumerate(results["ids"]):
            meta = results["metadatas"][i] if results.get("metadatas") else {}
            entries.append({
                "id": eid,
                "title": meta.get("title", eid),
                "collection": collection,
                "author": meta.get("author", ""),
                "tags": json.loads(meta.get("tags", "[]")),
                "created_at": meta.get("created_at", ""),
                "updated_at": meta.get("updated_at", ""),
            })
        entries.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return entries[:limit]
    except Exception as exc:
        logger.error("list_entries(%s) failed: %s", collection, exc)
        return []


def get_stats() -> dict:
    """Return per-collection entry counts."""
    stats = {}
    for coll_name in ALL_COLLECTIONS:
        try:
            coll = _get_or_create_collection(coll_name)
            stats[coll_name] = coll.count()
        except Exception:
            stats[coll_name] = -1
    return stats


def build_rag_context(query: str, collection: Optional[str] = None, top_k: int = 5) -> str:
    """
    Retrieve top-K entries and format as a context string for LLM injection.
    """
    results = search_entries(query=query, collection=collection, n_results=top_k)
    if not results:
        return ""

    chunks = []
    for r in results:
        chunks.append(
            f"## [{r['collection']}] {r['title']} (similarity={r['similarity']})\n"
            f"{r['content'][:1000]}"
        )
    return "\n\n---\n\n".join(chunks)
