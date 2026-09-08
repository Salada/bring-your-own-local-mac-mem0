"""Mem0 FastMCP Server Module.

Provides Model Context Protocol (MCP) tools for local AI agents (Antigravity,
OpenCode, Hermes, Claude, Codex) connecting via SSE at /mcp/sse.

Compatible with official Mem0 Platform MCP specification (mcp.mem0.ai) and
Antigravity agent memory skills.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from env_loader import load_runtime_env

load_runtime_env()

# This self-hosted server is intentionally local-only.
os.environ["MEM0_TELEMETRY"] = "False"

from mem0 import (  # noqa: E402 - telemetry and local env must be set before import
    Memory,
)

from backup_lock import maintenance_lock, mutation_lock  # noqa: E402
from memory_guards import validate_current  # noqa: E402
from memory_listing import list_memory_page  # noqa: E402

logger = logging.getLogger("mem0-server.mcp")
DEFAULT_USER_ID = os.environ.get("MEM0_DEFAULT_USER_ID", "local-user")

MCP_INSTRUCTIONS = (
    "Use memories as durable local context. At task start, search_memories for relevant prior decisions, "
    "preferences, conventions, failures, and environment facts before acting. After significant work, call "
    "add_memory only for durable decisions, preferences, conventions, reusable fixes, and outcomes not already "
    "captured; use concise text and metadata.type. Never store secrets, credentials, transient logs, or raw tool "
    "output. Confirm IDs before updates. Before calling delete_memory, show the exact memory to the user and obtain "
    "approval. The server then requires the reviewed hash/revision/scope and a verified backup. Bulk deletion is "
    "intentionally unavailable over MCP."
)


def _capture_backup_generation() -> str:
    """Capture a verified local generation before a guarded MCP deletion."""
    sibling = Path(__file__).parent / "bin" / "mem0-backup"
    executable = str(sibling) if sibling.is_file() and os.access(sibling, os.X_OK) else shutil.which("mem0-backup")
    if not executable:
        raise RuntimeError("mem0-backup was not found beside the runtime or on PATH")
    try:
        result = subprocess.run([executable, "capture"], check=True, text=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise RuntimeError(f"backup failed; no deletion applied: {detail.strip()}") from exc
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("backup produced no generation path")
    return lines[-1]


def _normalize_metadata_keys(value: Any) -> Any:
    """Match Mem0 OSS's flattened metadata payload keys."""
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            item = _normalize_metadata_keys(item)
            if key == "metadata" and isinstance(item, dict):
                normalized.update(item)
            else:
                normalized[key.removeprefix("metadata.")] = item
        return normalized
    if isinstance(value, list):
        return [_normalize_metadata_keys(item) for item in value]
    return value


def normalize_filters(
    filters: Optional[dict] = None,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> dict:
    """Normalize filters for Mem0 OSS vector_store.

    Promotes identity filters from nested AND/OR structures because Mem0
    requires them at the top level, while preserving metadata filters.
    """
    normalized = _normalize_metadata_keys(filters) if isinstance(filters, dict) else {}
    extracted: Dict[str, Any] = {}
    if user_id:
        extracted["user_id"] = user_id
    if agent_id:
        extracted["agent_id"] = agent_id
    if run_id:
        extracted["run_id"] = run_id

    for key in ("user_id", "agent_id", "run_id"):
        value = normalized.pop(key, None)
        if value and value != "*":
            extracted[key] = value

    for operator in ("AND", "OR"):
        clauses = normalized.get(operator)
        if not isinstance(clauses, list):
            continue
        preserved = []
        for clause in clauses:
            if not isinstance(clause, dict):
                preserved.append(clause)
                continue
            clause = dict(clause)
            for key in ("user_id", "agent_id", "run_id"):
                value = clause.pop(key, None)
                if value and value != "*":
                    extracted[key] = value
            if clause:
                preserved.append(clause)
        if preserved:
            normalized[operator] = preserved
        else:
            normalized.pop(operator)

    # Mem0 requires at least one logical scope for ordinary memory operations.
    if not any(k in extracted for k in ("user_id", "agent_id", "run_id")):
        extracted["user_id"] = DEFAULT_USER_ID

    normalized.update(extracted)
    return normalized


def create_mcp_server(memory: Memory) -> FastMCP:
    """Initialize FastMCP server with comprehensive Mem0 toolset."""
    mcp = FastMCP("mem0", instructions=MCP_INSTRUCTIONS)
    mcp.settings.streamable_http_path = "/"

    @mcp.tool()
    def search_memories(
        query: str,
        filters: Optional[dict] = None,
        user_id: Optional[str] = DEFAULT_USER_ID,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        top_k: int = 3,
        limit: Optional[int] = None,
        rerank: bool = False,
        threshold: float = 0.5,
    ) -> str:
        """Semantic search across stored memories with filters.

        Compatible with official Mem0 MCP search_memories.

        Defaults were tuned against positive and negative-control local queries;
        callers can override them for broad recall or stricter retrieval.
        """
        max_items = limit or top_k or 10
        norm_filters = normalize_filters(filters, user_id=user_id, agent_id=agent_id, run_id=run_id)
        try:
            res = memory.search(
                query=query,
                filters=norm_filters,
                top_k=max_items,
                threshold=threshold,
                rerank=rerank,
            )
            items = res.get("results", []) if isinstance(res, dict) else res if isinstance(res, list) else []
            filtered = []
            for item in items:
                score = item.get("score")
                try:
                    if score is not None and float(score) < threshold:
                        continue
                except (TypeError, ValueError):
                    pass
                filtered.append(item)
            payload = (
                {**res, "results": filtered[:max_items]} if isinstance(res, dict) else {"results": filtered[:max_items]}
            )
            return json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            logger.exception("Error in search_memories: %s", e)
            return json.dumps({"error": str(e), "results": []}, ensure_ascii=False)

    @mcp.tool()
    def get_memories(
        filters: Optional[dict] = None,
        user_id: Optional[str] = DEFAULT_USER_ID,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        limit: Optional[int] = 100,
        page_size: Optional[int] = None,
        page: int = 1,
        cursor: Optional[str] = None,
    ) -> str:
        """List stored memories with filters and pagination.

        Compatible with official Mem0 MCP get_memories.
        """
        max_items = page_size or limit or 100
        norm_filters = normalize_filters(filters, user_id=user_id, agent_id=agent_id, run_id=run_id)
        try:
            payload = list_memory_page(
                memory,
                filters=norm_filters,
                page_size=max_items,
                page=page,
                cursor=cursor,
            )
            return json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            logger.exception("Error in get_memories: %s", e)
            return json.dumps({"error": str(e), "results": []}, ensure_ascii=False)

    @mcp.tool()
    def get_all_memories(user_id: str = DEFAULT_USER_ID, limit: int = 100) -> str:
        """Retrieve all stored memories for the specified user (alias for get_memories)."""
        return get_memories(user_id=user_id, limit=limit)

    @mcp.tool()
    def get_all(user_id: str = DEFAULT_USER_ID, limit: int = 100) -> str:
        """Retrieve all stored memories for the specified user (legacy alias)."""
        return get_memories(user_id=user_id, limit=limit)

    @mcp.tool()
    def get_memory(memory_id: str) -> str:
        """Retrieve a specific stored memory by its unique ID.

        Compatible with official Mem0 MCP get_memory.
        """
        try:
            res = memory.get(memory_id)
            return json.dumps(res, ensure_ascii=False)
        except Exception as e:
            logger.exception("Error in get_memory: %s", e)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    def add_memory(
        text: str,
        user_id: Optional[str] = DEFAULT_USER_ID,
        agent_id: Optional[str] = None,
        app_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        infer: bool = True,
    ) -> str:
        """Save text, conversation history, or facts into Mem0 memory.

        Compatible with official Mem0 MCP add_memory.
        """
        meta = dict(metadata) if metadata else {}
        if app_id and "app_id" not in meta:
            meta["app_id"] = app_id
        try:
            with mutation_lock():
                res = memory.add(
                    text,
                    user_id=user_id or DEFAULT_USER_ID,
                    agent_id=agent_id,
                    metadata=meta or None,
                    infer=infer,
                )
            return json.dumps(res, ensure_ascii=False)
        except Exception as e:
            logger.exception("Error in add_memory: %s", e)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    def add_memories(
        text: str,
        user_id: Optional[str] = DEFAULT_USER_ID,
        agent_id: Optional[str] = None,
        app_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        infer: bool = True,
    ) -> str:
        """Save knowledge or facts into Mem0 (alias for add_memory)."""
        return add_memory(text, user_id=user_id, agent_id=agent_id, app_id=app_id, metadata=metadata, infer=infer)

    @mcp.tool()
    def update_memory(
        memory_id: str,
        text: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """Update or overwrite an existing memory item by ID.

        Compatible with official Mem0 MCP update_memory.
        """
        try:
            with mutation_lock():
                res = memory.update(memory_id, text=text, metadata=metadata)
            return json.dumps({"result": "Memory updated.", "memory_id": memory_id, "details": res}, ensure_ascii=False)
        except Exception as e:
            logger.exception("Error in update_memory: %s", e)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    def delete_memory(
        memory_id: str,
        expected_hash: str,
        expected_revision: str,
        expected_user_id: str = DEFAULT_USER_ID,
        expected_app_id: Optional[str] = None,
    ) -> str:
        """Delete one reviewed memory after deterministic checks and a verified backup.

        First retrieve the memory and present it to the user. Copy its hash,
        revision, and scope into this call only after the user approves deletion.
        Bulk deletion is not available over MCP.
        """
        try:
            current = memory.get(memory_id)
            validate_current(
                current,
                expected_hash=expected_hash,
                expected_revision=expected_revision,
                expected_user_id=expected_user_id,
                expected_app_id=expected_app_id,
            )
            backup = _capture_backup_generation()
            with maintenance_lock():
                current = memory.get(memory_id)
                validate_current(
                    current,
                    expected_hash=expected_hash,
                    expected_revision=expected_revision,
                    expected_user_id=expected_user_id,
                    expected_app_id=expected_app_id,
                )
                memory.delete(memory_id)
            return json.dumps({"ok": True, "deleted": memory_id, "backup": backup}, ensure_ascii=False)
        except Exception as e:
            logger.exception("Error in guarded delete_memory: %s", e)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    def list_entities(
        user_id: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """List extracted entity nodes (people, concepts, technologies, systems) from knowledge graph.

        Compatible with official Mem0 MCP list_entities.
        """
        try:
            if hasattr(memory, "entity_store") and memory.entity_store and hasattr(memory.entity_store, "client"):
                points, _ = memory.entity_store.client.scroll(
                    collection_name="mem0_entities",
                    limit=limit,
                    with_payload=True,
                )
                results = []
                for p in points:
                    payload = p.payload or {}
                    if user_id and payload.get("user_id") != user_id:
                        continue
                    results.append(
                        {
                            "id": str(p.id),
                            "entity": payload.get("data", ""),
                            "type": payload.get("entity_type", "CONCEPT"),
                            "user_id": payload.get("user_id"),
                            "linked_memory_count": len(payload.get("linked_memory_ids") or []),
                        }
                    )
                return json.dumps({"total_entities": len(results), "results": results}, ensure_ascii=False)
            return json.dumps({"total_entities": 0, "results": []}, ensure_ascii=False)
        except Exception as e:
            logger.exception("Error in list_entities: %s", e)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    def get_memory_stats(
        user_id: Optional[str] = None,
    ) -> str:
        """Return comprehensive memory aggregation statistics in <50ms.

        Provides total memory count, category breakdown, age distribution,
        and entity graph metrics in a single 1-turn call without client-side loops.
        """
        try:
            points, _ = memory.vector_store.list(filters=None, top_k=10000)
            total = len(points)
            cat_counts: Counter = Counter()
            dates: List[str] = []

            for p in points:
                payload = p.payload or {}
                if user_id and payload.get("user_id") != user_id:
                    continue
                cats = payload.get("categories") or ["uncategorized"]
                if isinstance(cats, list):
                    for c in cats:
                        cat_counts[c] += 1
                elif isinstance(cats, str):
                    cat_counts[cats] += 1
                ca = payload.get("created_at")
                if ca:
                    dates.append(str(ca))

            now = datetime.now(timezone.utc)
            age_buckets = {"<7d": 0, "7-30d": 0, "30-90d": 0, ">90d": 0}
            for d in dates:
                try:
                    dt = datetime.fromisoformat(d)
                    diff_days = (now - dt).days
                    if diff_days < 7:
                        age_buckets["<7d"] += 1
                    elif diff_days <= 30:
                        age_buckets["7-30d"] += 1
                    elif diff_days <= 90:
                        age_buckets["30-90d"] += 1
                    else:
                        age_buckets[">90d"] += 1
                except Exception:
                    pass

            stats = {
                "total_memories": total,
                "user_scoped_total": sum(cat_counts.values()) if user_id else total,
                "scoped_user": user_id or "all",
                "categories": dict(cat_counts.most_common()),
                "age_distribution": age_buckets,
                "oldest": min(dates) if dates else None,
                "newest": max(dates) if dates else None,
            }
            return json.dumps(stats, ensure_ascii=False)
        except Exception as e:
            logger.exception("Error in get_memory_stats: %s", e)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    return mcp


if __name__ == "__main__":
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from server import memory

    mcp_app = create_mcp_server(memory)
    mcp_app.run(transport="stdio")
