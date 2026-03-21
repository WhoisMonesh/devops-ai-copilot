# agent/tools/knowledge_base_tool.py - Knowledge Base RAG tools
# Exposes semantic search and KB CRUD to the DevOps AI agent via LangChain tools.
from __future__ import annotations

import logging
import uuid
from typing import Optional

from langchain_core.tools import tool

from agent.knowledge_base import (
    add_entry,
    build_rag_context,
    delete_entry,
    get_entry,
    get_stats,
    list_entries,
    search_entries,
    update_entry,
    KnowledgeEntry,
    ALL_COLLECTIONS,
    COLLECTION_INCIDENTS,
    COLLECTION_RUNBOOKS,
    COLLECTION_CONFIGS,
    COLLECTION_SOPS,
)

logger = logging.getLogger(__name__)


@tool
def kb_search(query: str, collection: Optional[str] = None, top_k: int = 5) -> str:
    """
    Search the enterprise knowledge base using natural language.

    Args:
        query - Natural language search query (e.g. 'how to restart nginx', 'DB failover runbook')
        collection - Optional: scope to one collection: runbooks, incidents, configs, sops, kb
        top_k - Maximum number of results to return (default: 5)
    """
    try:
        results = search_entries(query=query, collection=collection, n_results=top_k)
        if not results:
            return f"No knowledge base entries found for: '{query}'"

        lines = [f"Knowledge Base Search: '{query}' ({len(results)} results)"]
        for r in results:
            preview = r["content"][:200].replace("\n", " ")
            lines.append(
                f"\n  [{r['collection']}] {r['title']} "
                f"(similarity={r['similarity']}, tags={r.get('tags', [])})"
            )
            lines.append(f"  {preview}...")

        return "\n".join(lines)
    except Exception as exc:
        logger.exception("kb_search failed")
        return f"Error searching knowledge base: {exc}"


@tool
def kb_get_rag_context(query: str, collection: Optional[str] = None, top_k: int = 5) -> str:
    """
    Retrieve formatted RAG context from the knowledge base.
    Use this to augment LLM responses with enterprise-specific runbooks, SOPs, or configs.

    Args:
        query - Search query
        collection - Optional collection filter
        top_k - Number of entries to include (default: 5)
    """
    try:
        context = build_rag_context(query=query, collection=collection, top_k=top_k)
        if not context:
            return "No relevant knowledge base entries found."
        return f"KNOWLEDGE BASE CONTEXT:\n{context}"
    except Exception as exc:
        logger.exception("kb_get_rag_context failed")
        return f"Error retrieving RAG context: {exc}"


@tool
def kb_add_runbook(title: str, content: str, tags: str = "", author: str = "") -> str:
    """
    Add a new runbook to the knowledge base.

    Args:
        title - Runbook title (e.g. 'Nginx Restart Procedure')
        content - Full runbook content (markdown supported)
        tags - Comma-separated tags (e.g. 'nginx,kubernetes,restart')
        author - Author name (defaults to KB_DEFAULT_AUTHOR env var)
    """
    try:
        entry = KnowledgeEntry(
            id=str(uuid.uuid4()),
            title=title,
            content=content,
            collection=COLLECTION_RUNBOOKS,
            tags=[t.strip() for t in tags.split(",") if t.strip()],
            author=author or "devops-ai",
        )
        add_entry(entry)
        return f"Runbook added: id={entry.id} title='{title}'"
    except Exception as exc:
        logger.exception("kb_add_runbook failed")
        return f"Error adding runbook: {exc}"


@tool
def kb_add_incident_doc(title: str, content: str, tags: str = "", author: str = "") -> str:
    """
    Add an incident postmortem or RCA document.

    Args:
        title - Document title
        content - Full incident document content
        tags - Comma-separated tags
        author - Author name
    """
    try:
        entry = KnowledgeEntry(
            id=str(uuid.uuid4()),
            title=title,
            content=content,
            collection=COLLECTION_INCIDENTS,
            tags=[t.strip() for t in tags.split(",") if t.strip()],
            author=author or "devops-ai",
        )
        add_entry(entry)
        return f"Incident document added: id={entry.id} title='{title}'"
    except Exception as exc:
        logger.exception("kb_add_incident_doc failed")
        return f"Error adding incident doc: {exc}"


@tool
def kb_add_config_snippet(title: str, content: str, tags: str = "") -> str:
    """
    Store a configuration snippet or manifest.

    Args:
        title - Config name (e.g. 'nginx.conf baseline')
        content - Config file content
        tags - Comma-separated tags (e.g. 'nginx,config,production')
    """
    try:
        entry = KnowledgeEntry(
            id=str(uuid.uuid4()),
            title=title,
            content=content,
            collection=COLLECTION_CONFIGS,
            tags=[t.strip() for t in tags.split(",") if t.strip()],
        )
        add_entry(entry)
        return f"Config snippet added: id={entry.id} title='{title}'"
    except Exception as exc:
        logger.exception("kb_add_config_snippet failed")
        return f"Error adding config snippet: {exc}"


@tool
def kb_add_sop(title: str, content: str, tags: str = "", author: str = "") -> str:
    """
    Add a Standard Operating Procedure.

    Args:
        title - SOP title
        content - Full SOP content
        tags - Comma-separated tags
        author - Author name
    """
    try:
        entry = KnowledgeEntry(
            id=str(uuid.uuid4()),
            title=title,
            content=content,
            collection=COLLECTION_SOPS,
            tags=[t.strip() for t in tags.split(",") if t.strip()],
            author=author or "devops-ai",
        )
        add_entry(entry)
        return f"SOP added: id={entry.id} title='{title}'"
    except Exception as exc:
        logger.exception("kb_add_sop failed")
        return f"Error adding SOP: {exc}"


@tool
def kb_list_entries(collection: str, limit: int = 20) -> str:
    """
    List all entries in a knowledge base collection.

    Args:
        collection - Collection name: runbooks, incidents, configs, sops, kb
        limit - Max entries to return (default: 20)
    """
    try:
        if collection not in ALL_COLLECTIONS:
            return f"Unknown collection: '{collection}'. Valid: {ALL_COLLECTIONS}"
        entries = list_entries(collection=collection, limit=limit)
        if not entries:
            return f"No entries in collection: {collection}"
        lines = [f"Knowledge Base: {collection} ({len(entries)} entries)"]
        for e in entries:
            lines.append(f"  [{e['id'][:8]}] {e['title']} | updated={e['updated_at'][:10]} | tags={e.get('tags', [])}")
        return "\n".join(lines)
    except Exception as exc:
        logger.exception("kb_list_entries failed")
        return f"Error listing entries: {exc}"


@tool
def kb_get_entry(entry_id: str, collection: str) -> str:
    """
    Get the full content of a specific knowledge base entry.

    Args:
        entry_id - Entry UUID
        collection - Collection name
    """
    try:
        entry = get_entry(entry_id=entry_id, collection=collection)
        if not entry:
            return f"Entry not found: {entry_id} in {collection}"
        return (
            f"# {entry['title']}\n"
            f"Collection: {entry['collection']} | Author: {entry.get('author', '')}\n"
            f"Tags: {entry.get('tags', [])}\n"
            f"Created: {entry['created_at'][:10]} | Updated: {entry['updated_at'][:10]}\n\n"
            f"---\n{entry['content']}"
        )
    except Exception as exc:
        logger.exception("kb_get_entry failed")
        return f"Error retrieving entry: {exc}"


@tool
def kb_update_entry(entry_id: str, collection: str, content: str = "", title: str = "", tags: str = "") -> str:
    """
    Update an existing knowledge base entry.

    Args:
        entry_id - Entry UUID
        collection - Collection name
        content - New content (leave empty to skip)
        title - New title (leave empty to skip)
        tags - Comma-separated tags (leave empty to skip)
    """
    try:
        kwargs = {}
        if content:
            kwargs["content"] = content
        if title:
            kwargs["title"] = title
        if tags:
            kwargs["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

        if not kwargs:
            return "Nothing to update. Provide at least content, title, or tags."

        success = update_entry(entry_id=entry_id, collection=collection, **kwargs)
        return f"Entry {entry_id} updated successfully." if success else f"Failed to update {entry_id}"
    except Exception as exc:
        logger.exception("kb_update_entry failed")
        return f"Error updating entry: {exc}"


@tool
def kb_delete_entry(entry_id: str, collection: str) -> str:
    """
    Delete a knowledge base entry permanently.

    Args:
        entry_id - Entry UUID
        collection - Collection name
    """
    try:
        success = delete_entry(entry_id=entry_id, collection=collection)
        return f"Entry {entry_id} deleted." if success else f"Failed to delete {entry_id}"
    except Exception as exc:
        logger.exception("kb_delete_entry failed")
        return f"Error deleting entry: {exc}"


@tool
def kb_stats() -> str:
    """Return entry counts per knowledge base collection."""
    try:
        stats = get_stats()
        lines = ["Knowledge Base Stats:"]
        total = 0
        for coll, count in stats.items():
            display = count if count >= 0 else "unavailable"
            lines.append(f"  {coll}: {display}")
            if count >= 0:
                total += count
        lines.append(f"  TOTAL: {total}")
        return "\n".join(lines)
    except Exception as exc:
        logger.exception("kb_stats failed")
        return f"Error getting KB stats: {exc}"


KB_TOOLS = [
    kb_search,
    kb_get_rag_context,
    kb_add_runbook,
    kb_add_incident_doc,
    kb_add_config_snippet,
    kb_add_sop,
    kb_list_entries,
    kb_get_entry,
    kb_update_entry,
    kb_delete_entry,
    kb_stats,
]
