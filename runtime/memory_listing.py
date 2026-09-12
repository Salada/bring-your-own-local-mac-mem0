"""Stable cursor pagination for the local Mem0 Qdrant store."""

from __future__ import annotations

from datetime import date, datetime, timezone
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


def _is_expired(point: Any) -> bool:
    """Mirror pinned Mem0's UTC date boundary for Qdrant-backed listings."""
    value = (point.payload or {}).get("expiration_date")
    if not value:
        return False
    try:
        return date.fromisoformat(str(value)) < datetime.now(timezone.utc).date()
    except ValueError:
        return False


def _visible_page(store: Any, query_filter: Any, page_size: int, offset: Any) -> tuple[list[Any], Any]:
    """Fill a visible page without letting expired raw points create holes."""
    visible = []
    while True:
        points, next_offset = store.client.scroll(
            collection_name=store.collection_name,
            scroll_filter=query_filter,
            limit=page_size - len(visible),
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            if _is_expired(point):
                continue
            if len(visible) == page_size:
                return visible, point.id
            visible.append(point)
        if len(visible) == page_size:
            return visible, _next_visible_cursor(store, query_filter, next_offset)
        if next_offset is None:
            return visible, None
        if next_offset == offset:
            raise ValueError("Qdrant pagination cursor did not advance")
        offset = _coerce_cursor(str(next_offset)) if next_offset is not None else None


def _next_visible_cursor(store: Any, query_filter: Any, offset: Any) -> Any:
    """Look ahead so has_more means another visible record, not a raw point."""
    while offset is not None:
        points, next_offset = store.client.scroll(
            collection_name=store.collection_name,
            scroll_filter=query_filter,
            limit=500,
            offset=offset,
            with_payload=["expiration_date"],
            with_vectors=False,
        )
        for point in points:
            if not _is_expired(point):
                return point.id
        if next_offset == offset:
            raise ValueError("Qdrant pagination cursor did not advance")
        offset = _coerce_cursor(str(next_offset)) if next_offset is not None else None
    return None


def list_memory_page(
    memory: Any,
    *,
    filters: Optional[dict[str, Any]],
    page_size: int,
    cursor: Optional[str] = None,
    page: int = 1,
    show_expired: bool = False,
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
        if show_expired:
            points, next_offset = store.client.scroll(
                collection_name=store.collection_name,
                scroll_filter=query_filter,
                limit=page_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
        else:
            points, next_offset = _visible_page(store, query_filter, page_size, offset)
        if not points:
            next_offset = None
            break
        if next_offset is None and index < page - 1:
            points = []
            break
        offset = _coerce_cursor(str(next_offset)) if next_offset is not None else None

    return {
        "results": [_format_point(point) for point in points],
        "page": page,
        "page_size": page_size,
        "next_cursor": str(next_offset) if next_offset is not None else None,
        "has_more": next_offset is not None,
    }


def count_memories(memory: Any, filters: Optional[dict[str, Any]], *, show_expired: bool = False) -> int:
    """Count Qdrant points using the same filters as ``list_memory_page``."""
    store = memory.vector_store
    query_filter = store._create_filter(filters) if filters else None
    if show_expired:
        result = store.client.count(
            collection_name=store.collection_name,
            count_filter=query_filter,
            exact=True,
        )
        return int(result.count)
    total = 0
    offset = None
    while True:
        points, next_offset = store.client.scroll(
            collection_name=store.collection_name,
            scroll_filter=query_filter,
            limit=500,
            offset=offset,
            with_payload=["expiration_date"],
            with_vectors=False,
        )
        total += sum(not _is_expired(point) for point in points)
        if next_offset is None:
            return total
        if next_offset == offset:
            raise ValueError("Qdrant pagination cursor did not advance")
        offset = next_offset


def to_openmemory_item(item: dict[str, Any]) -> dict[str, Any]:
    """Translate a Mem0 result into the shape consumed by OpenMemory UI."""
    metadata = dict(item.get("metadata") or {})
    if item.get("expiration_date") is not None:
        metadata.setdefault("expiration_date", item["expiration_date"])
    categories = metadata.get("categories") or []
    if isinstance(categories, str):
        categories = [categories]
    return {
        "id": item["id"],
        "content": item.get("memory", ""),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "state": metadata.get("state", "active"),
        "metadata_": metadata,
        "categories": categories,
        "app_name": item.get("agent_id") or metadata.get("app_id") or metadata.get("source") or "default",
    }
