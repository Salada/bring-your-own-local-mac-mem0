"""Stable cursor pagination for the local Mem0 Qdrant store."""

from __future__ import annotations

from typing import Any, Optional

PROMOTED_KEYS = (
    "user_id",
    "agent_id",
    "run_id",
    "actor_id",
    "role",
    "attributed_to",
    "expiration_date",
)
CORE_KEYS = {
    "data",
    "hash",
    "created_at",
    "updated_at",
    "id",
    "metadata",
    "text_lemmatized",
    *PROMOTED_KEYS,
}


def _coerce_cursor(cursor: Optional[str]) -> Any:
    if cursor is None:
        return None
    return int(cursor) if cursor.isdigit() else cursor


def _format_point(point: Any) -> dict[str, Any]:
    payload = point.payload or {}
    item = {
        "id": str(point.id),
        "memory": payload.get("data", ""),
        "hash": payload.get("hash"),
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
    }
    for key in PROMOTED_KEYS:
        if key in payload:
            item[key] = payload[key]
    nested_metadata = payload.get("metadata")
    metadata = dict(nested_metadata) if isinstance(nested_metadata, dict) else {}
    for key, value in payload.items():
        if key not in CORE_KEYS:
            metadata.setdefault(key, value)
    if metadata:
        item["metadata"] = metadata
    return item


def list_memory_page(
    memory: Any,
    *,
    filters: Optional[dict[str, Any]],
    page_size: int,
    cursor: Optional[str] = None,
    page: int = 1,
) -> dict[str, Any]:
    """Return one stable Qdrant page and its opaque continuation cursor."""
    if not 1 <= page_size <= 500:
        raise ValueError("page_size must be between 1 and 500")
    if page < 1:
        raise ValueError("page must be at least 1")
    if cursor is not None and page != 1:
        raise ValueError("cursor and page>1 cannot be combined")

    store = memory.vector_store
    query_filter = store._create_filter(filters) if filters else None
    offset = _coerce_cursor(cursor)
    points = []
    next_offset = None
    # page=N is compatibility-only. Cursor callers avoid this O(N) walk.
    for index in range(page):
        points, next_offset = store.client.scroll(
            collection_name=store.collection_name,
            scroll_filter=query_filter,
            limit=page_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            next_offset = None
            break
        if next_offset is None and index < page - 1:
            points = []
            break
        offset = next_offset

    return {
        "results": [_format_point(point) for point in points],
        "page": page,
        "page_size": page_size,
        "next_cursor": str(next_offset) if next_offset is not None else None,
        "has_more": next_offset is not None,
    }
