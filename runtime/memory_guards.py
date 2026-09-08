"""Pure validation helpers for guarded Mem0 maintenance."""

from __future__ import annotations

import re
from typing import Any, Optional

WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def metadata(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("metadata")
    return value if isinstance(value, dict) else {}


def field(item: dict[str, Any], key: str) -> Any:
    return item.get(key) or metadata(item).get(key)


def revision(item: dict[str, Any]) -> str:
    return str(item.get("updated_at") or item.get("created_at") or "")


def normalized_text(item: dict[str, Any]) -> str:
    return " ".join(WORD_RE.findall(str(item.get("memory") or "").casefold()))


def memory_type(item: dict[str, Any]) -> str:
    return str(item.get("type") or metadata(item).get("type") or "unknown")


def validate_current(
    item: Any,
    *,
    expected_hash: str,
    expected_revision: str,
    expected_user_id: str,
    expected_app_id: Optional[str],
) -> None:
    if not isinstance(item, dict):
        raise ValueError("memory no longer exists")
    if item.get("hash") != expected_hash or revision(item) != expected_revision:
        raise ValueError("memory changed after review")
    if field(item, "user_id") != expected_user_id or (expected_app_id and field(item, "app_id") != expected_app_id):
        raise ValueError("memory scope changed after review")


def validate_exact_keeper(
    target: dict[str, Any],
    keeper: Any,
    *,
    expected_hash: str,
    expected_revision: str,
    expected_user_id: str,
    expected_app_id: Optional[str],
) -> None:
    validate_current(
        keeper,
        expected_hash=expected_hash,
        expected_revision=expected_revision,
        expected_user_id=expected_user_id,
        expected_app_id=expected_app_id,
    )
    if keeper.get("id") == target.get("id"):
        raise ValueError("keeper must be a different memory")
    if memory_type(keeper) != memory_type(target) or normalized_text(keeper) != normalized_text(target):
        raise ValueError("memory is no longer an exact duplicate of its keeper")
