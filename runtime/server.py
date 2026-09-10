"""Loopback-only Mem0 REST and MCP compatibility server."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import sys
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.applications import Starlette

from env_loader import load_runtime_env

load_runtime_env()

# Keep the self-hosted stack local-only, including Mem0 OSS analytics.
os.environ["MEM0_TELEMETRY"] = "False"

from mem0 import (  # noqa: E402 - telemetry and local env must be set before import
    Memory,
)

from backup_lock import maintenance_lock, mutation_lock, restore_marker  # noqa: E402
from categories import MemoryCategorizer, category_catalog, pop_project_categories  # noqa: E402
from gemini_http import register_gemini_http_compat  # noqa: E402
from http_errors import to_http_exception  # noqa: E402
from mcp_server import create_mcp_server, normalize_filters  # noqa: E402
from memory_guards import validate_current, validate_exact_keeper  # noqa: E402
from memory_listing import count_memories, list_memory_page, to_openmemory_item  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [mem0-server] %(message)s",
)
logger = logging.getLogger("mem0-server")

DEFAULT_USER_ID = os.environ.get("MEM0_DEFAULT_USER_ID", "local-user")
DEFAULT_CORS_ORIGINS = "http://127.0.0.1:11889,http://localhost:11889"
CORS_ORIGINS = [
    origin.strip() for origin in os.environ.get("MEM0_CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if origin.strip()
]
ALLOW_UNGUARDED_DELETE = os.environ.get("MEM0_ALLOW_UNGUARDED_DELETE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}
ERROR_LOG = pathlib.Path.home() / ".local" / "state" / "mem0" / "server.error.log"
ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
error_log_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
ERROR_LOG.chmod(0o600)
error_log_handler.setLevel(logging.ERROR)
error_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s"))
logger.addHandler(error_log_handler)


def raise_api_error(operation: str, exc: Exception) -> None:
    """Log and raise an HTTP error without misclassifying client failures."""
    http_error = to_http_exception(exc)
    if http_error.status_code < 500:
        logger.warning("%s failed [%s]: %s", operation, http_error.status_code, exc)
    else:
        logger.exception("%s failed [%s]: %s", operation, http_error.status_code, exc)
    raise http_error from exc


# ---------------------------------------------------------------------------
# Configuration Resolution
# ---------------------------------------------------------------------------
def resolve_config_path() -> pathlib.Path:
    """Resolve config.json path with fallback to script directory or standard path."""
    env_path = os.environ.get("MEM0_CONFIG_PATH")
    if env_path and os.path.exists(env_path):
        return pathlib.Path(env_path)

    local_path = pathlib.Path(__file__).parent / "config.json"
    if local_path.exists():
        return local_path

    home_config = pathlib.Path.home() / ".config" / "mem0" / "config.json"
    if home_config.exists():
        return home_config

    logger.error("Configuration file not found. Checked: %s, %s, %s", env_path, local_path, home_config)
    sys.exit(1)


CONFIG_FILE = resolve_config_path()


def load_memory() -> tuple[Memory, list[dict[str, str]]]:
    """Initialize Mem0 instance from JSON configuration."""
    logger.info("Loading Mem0 configuration from: %s", CONFIG_FILE)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    project_categories = pop_project_categories(config)
    logger.info("Initializing Mem0 Memory instance (Qdrant + oMLX + SQLite)...")
    register_gemini_http_compat()
    return Memory.from_config(config), project_categories


incomplete_restore = restore_marker()
if incomplete_restore.exists():
    raise RuntimeError(
        f"incomplete restore marker exists: {incomplete_restore}; complete the rollback restore before starting Mem0"
    )

memory, project_categories = load_memory()
categorizer = MemoryCategorizer(memory, project_categories)
mcp = create_mcp_server(memory, categorizer)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage lifecycle of background services including Streamable HTTP session manager."""
    logger.info("Starting FastMCP Streamable HTTP session manager...")
    async with mcp.session_manager.run():
        yield
    logger.info("Stopped FastMCP Streamable HTTP session manager.")


# ---------------------------------------------------------------------------
# FastAPI Application & CORS
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Mem0 Local Unified Server",
    description="Host-Native Mem0 REST API, FastMCP SSE & Streamable HTTP, and OpenMemory UI Backend",
    version="2.0.19",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic Request Models
# ---------------------------------------------------------------------------
class AddMemoryRequest(BaseModel):
    messages: Any = Field(..., description="String message or list of message dicts")
    user_id: Optional[str] = DEFAULT_USER_ID
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    infer: bool = True
    custom_categories: Optional[list[dict[str, str]]] = None


class CategoryBackfillRequest(BaseModel):
    user_id: Optional[str] = DEFAULT_USER_ID
    page_size: int = Field(default=25, ge=1, le=50)
    cursor: Optional[str] = None
    apply: bool = False
    overwrite: bool = False
    custom_categories: Optional[list[dict[str, str]]] = None


class SearchMemoryRequest(BaseModel):
    query: str
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    limit: Optional[int] = 10
    top_k: Optional[int] = None
    filters: Optional[Dict[str, Any]] = None


class UpdateMemoryRequest(BaseModel):
    text: Optional[str] = None
    data: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class OpenMemoryFilterRequest(BaseModel):
    user_id: Optional[str] = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=10, ge=1, le=500)
    search_query: Optional[str] = None
    app_ids: Optional[list[str]] = None
    category_ids: Optional[list[str]] = None
    sort_column: Optional[str] = None
    sort_direction: Optional[str] = None
    show_archived: bool = False


def openmemory_user_id(user_id: Optional[str]) -> str:
    """Resolve the placeholder embedded in the official prebuilt UI image."""
    if not user_id or user_id == "NEXT_PUBLIC_USER_ID":
        return DEFAULT_USER_ID
    return user_id


# ---------------------------------------------------------------------------
# Health & Status Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "mem0-server",
        "baseline": "mem0ai==2.0.19",
        "config": str(CONFIG_FILE),
    }


# ---------------------------------------------------------------------------
# Core Memory Endpoints (REST API)
# ---------------------------------------------------------------------------
@app.post("/v1/memories")
@app.post("/v1/memories/")
@app.post("/memories")
@app.post("/memories/")
@app.post("/v3/memories/add")
@app.post("/v3/memories/add/")
def add_memory(req: AddMemoryRequest):
    """Add new memory item or extract facts from messages."""
    try:
        with mutation_lock():
            res = memory.add(
                messages=req.messages,
                user_id=req.user_id,
                agent_id=req.agent_id,
                run_id=req.run_id,
                metadata=req.metadata,
                infer=req.infer,
            )
        explicit_categories = (req.metadata or {}).get("categories")
        assignments = [] if explicit_categories else categorizer.safely_classify_add_result(res, req.custom_categories)
        if assignments:
            with mutation_lock():
                categorizer.apply(assignments)
            categorizer.annotate_result(res, assignments)
        if isinstance(res, dict) and "results" in res:
            return res
        return {"results": res if isinstance(res, list) else []}
    except Exception as e:
        raise_api_error("Adding memory", e)


@app.post("/v1/memories/search")
@app.post("/v1/memories/search/")
@app.post("/memories/search")
@app.post("/memories/search/")
@app.post("/search")
@app.post("/search/")
@app.post("/v3/memories/search")
@app.post("/v3/memories/search/")
def search_memory(req: SearchMemoryRequest):
    """Perform semantic vector search against Qdrant."""
    try:
        filters = normalize_filters(
            req.filters,
            user_id=req.user_id,
            agent_id=req.agent_id,
            run_id=req.run_id,
        )

        max_items = req.top_k or req.limit or 10
        res = memory.search(query=req.query, filters=filters, top_k=max_items)
        if isinstance(res, dict) and "results" in res:
            return res
        return {"results": res if isinstance(res, list) else []}
    except Exception as e:
        raise_api_error("Searching memory", e)


@app.get("/v1/memories")
@app.get("/v1/memories/")
@app.get("/memories")
@app.get("/memories/")
@app.get("/v3/memories")
@app.get("/v3/memories/")
def get_all_memories(
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    app_id: Optional[str] = None,
    limit: Optional[int] = Query(default=100, alias="limit"),
    top_k: Optional[int] = Query(default=None, alias="top_k"),
    page_size: Optional[int] = Query(default=None, ge=1, le=500),
    page: int = Query(default=1, ge=1),
    cursor: Optional[str] = None,
):
    """
    Retrieve stored memories.

    CRITICAL MAINTAINER NOTE:
    In mem0ai==2.0.19, `memory.get_all()` enforces that `filters` must contain
    at least one of (user_id, agent_id, run_id). If none is provided (e.g. when
    OpenMemory UI loads the initial overview page), calling `memory.get_all()`
    would raise a ValueError.
    To provide a seamless UI experience, when no user/agent/run filter is specified,
    we scroll points directly from the Qdrant vector store and format them to
    match the identical response schema.
    """
    max_items = page_size or top_k or limit or 100
    try:
        filters = {}
        if user_id:
            filters["user_id"] = user_id
        if agent_id:
            filters["agent_id"] = agent_id
        if run_id:
            filters["run_id"] = run_id
        if app_id:
            filters["app_id"] = app_id
        return list_memory_page(
            memory,
            filters=filters or None,
            page_size=max_items,
            page=page,
            cursor=cursor,
        )
    except Exception as e:
        raise_api_error("Getting all memories", e)


@app.get("/v1/memories/{memory_id}")
@app.get("/v1/memories/{memory_id}/")
def get_memory(memory_id: str):
    """Retrieve one memory for guarded administration."""
    try:
        return memory.get(memory_id)
    except Exception as e:
        raise_api_error("Getting memory", e)


@app.delete("/v1/admin/memories/{memory_id}")
def guarded_delete_memory(
    memory_id: str,
    expected_hash: str = Query(min_length=1),
    expected_revision: str = Query(min_length=1),
    expected_user_id: str = Query(min_length=1),
    expected_app_id: Optional[str] = None,
    expected_keeper_id: Optional[str] = None,
    expected_keeper_hash: Optional[str] = None,
    expected_keeper_revision: Optional[str] = None,
):
    """Delete only if memory content and revision still match the review."""
    try:
        with maintenance_lock():
            current = memory.get(memory_id)
            validate_current(
                current,
                expected_hash=expected_hash,
                expected_revision=expected_revision,
                expected_user_id=expected_user_id,
                expected_app_id=expected_app_id,
            )
            keeper_values = (expected_keeper_id, expected_keeper_hash, expected_keeper_revision)
            if any(keeper_values):
                if not all(keeper_values):
                    raise ValueError("incomplete keeper expectation")
                validate_exact_keeper(
                    current,
                    memory.get(expected_keeper_id),
                    expected_hash=expected_keeper_hash,
                    expected_revision=expected_keeper_revision,
                    expected_user_id=expected_user_id,
                    expected_app_id=expected_app_id,
                )
            memory.delete(memory_id)
        return {"ok": True, "deleted": memory_id}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise_api_error("Guarded memory deletion", e)


@app.put("/v1/memories/{memory_id}")
@app.put("/v1/memories/{memory_id}/")
@app.put("/memories/{memory_id}")
@app.put("/memories/{memory_id}/")
def update_memory(memory_id: str, req: UpdateMemoryRequest):
    """Update an existing memory item by ID."""
    try:
        new_text = req.text or req.data
        if not new_text:
            raise HTTPException(status_code=400, detail="Missing 'text' or 'data'")
        with mutation_lock():
            res = memory.update(memory_id, text=new_text, metadata=req.metadata)
        return {"result": "Memory updated.", "memory_id": memory_id, "details": res}
    except Exception as e:
        raise_api_error("Updating memory", e)


@app.delete("/v1/memories/{memory_id}")
@app.delete("/v1/memories/{memory_id}/")
@app.delete("/memories/{memory_id}")
@app.delete("/memories/{memory_id}/")
def delete_memory(memory_id: str):
    """Compatibility deletion endpoint, disabled unless explicitly enabled."""
    if not ALLOW_UNGUARDED_DELETE:
        raise HTTPException(
            status_code=403,
            detail="Unguarded deletion is disabled; use mem0-admin for reviewed, backed-up deletion",
        )
    try:
        with mutation_lock():
            memory.delete(memory_id)
        return {"ok": True, "deleted": memory_id}
    except Exception as e:
        raise_api_error("Deleting memory", e)


# ---------------------------------------------------------------------------
# OpenMemory UI Compatibility & Auxiliary Routes
# ---------------------------------------------------------------------------
@app.post("/api/v1/memories/filter")
def openmemory_filter_memories(req: OpenMemoryFilterRequest):
    """Serve the read-only memory list contract used by OpenMemory UI."""
    # Native Mem0 records have no OpenMemory archive state. The UI's sort/state
    # fields are accepted for wire compatibility while Qdrant supplies the page.
    filters: dict[str, Any] = {"user_id": openmemory_user_id(req.user_id)}
    if req.app_ids:
        filters["agent_id"] = {"in": req.app_ids}
    if req.category_ids:
        filters["categories"] = {"in": req.category_ids}
    if req.search_query:
        filters["data"] = {"icontains": req.search_query}
    try:
        result = list_memory_page(memory, filters=filters, page_size=req.size, page=req.page)
        items = [to_openmemory_item(item) for item in result["results"]]
        total = count_memories(memory, filters)
        return {
            "items": items,
            "total": total,
            "pages": (total + req.size - 1) // req.size,
            "page": req.page,
            "size": req.size,
        }
    except Exception as e:
        raise_api_error("Filtering memories for OpenMemory", e)


@app.get("/api/v1/memories/categories")
def openmemory_categories(user_id: Optional[str] = None):
    """Return the configured category catalog in OpenMemory's filter shape."""
    categories = category_catalog(project_categories)
    return {"categories": categories, "total": len(categories)}


@app.post("/v1/admin/categories/backfill")
def backfill_categories(req: CategoryBackfillRequest):
    """Preview or apply one cursor page of category backfill."""
    try:
        page = list_memory_page(
            memory,
            filters={"user_id": req.user_id} if req.user_id else None,
            page_size=req.page_size,
            cursor=req.cursor,
        )
        candidates = [
            item
            for item in page["results"]
            if req.overwrite or not (item.get("metadata") or {}).get("categories")
        ]
        assignments = categorizer.classify(candidates, req.custom_categories)
        applied = 0
        if req.apply and assignments:
            with mutation_lock():
                applied = categorizer.apply(assignments)
        return {
            "scanned": len(page["results"]),
            "eligible": len(candidates),
            "categorized": len(assignments),
            "applied": applied,
            "items": [
                {"id": assignment.memory_id, "categories": assignment.categories} for assignment in assignments
            ],
            "next_cursor": page["next_cursor"],
            "has_more": page["has_more"],
        }
    except Exception as e:
        raise_api_error("Backfilling memory categories", e)


@app.get("/auth/setup-status")
def setup_status():
    """Tells dashboard that initial admin setup is already complete."""
    return {"needsSetup": False}


@app.post("/auth/login")
def login(req: LoginRequest):
    """Allow immediate local login without cloud authentication hurdles."""
    return {
        "access_token": "local-mem0-token",
        "refresh_token": "local-mem0-token",
        "token_type": "bearer",
    }


@app.post("/auth/refresh")
def refresh():
    return {
        "access_token": "local-mem0-token",
        "refresh_token": "local-mem0-token",
        "token_type": "bearer",
    }


@app.get("/auth/me")
def get_me():
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "Local Admin",
        "email": "admin@localhost",
        "role": "admin",
        "created_at": "2026-09-06T00:00:00Z",
    }


@app.get("/v1/users")
@app.get("/users")
def get_users():
    """Return known user profiles for dashboard filtering."""
    return [{"id": DEFAULT_USER_ID, "name": DEFAULT_USER_ID}]


@app.get("/v1/apps")
@app.get("/apps")
def get_apps():
    return []


@app.get("/api/v1/apps")
@app.get("/api/v1/apps/")
def openmemory_apps():
    return {"apps": [], "total": 0, "page": 1, "pages": 0}


@app.get("/v1/stats")
@app.get("/stats")
@app.get("/api/v1/stats")
@app.get("/api/v1/stats/")
def get_stats():
    """Return memory statistics for dashboard counters."""
    try:
        if hasattr(memory.vector_store, "client") and hasattr(memory.vector_store.client, "get_collection"):
            coll = memory.vector_store.client.get_collection(memory.collection_name)
            return {"total_memories": coll.points_count, "total_apps": 0, "apps": []}
        points, _ = memory.vector_store.list(filters=None, top_k=10000)
        return {"total_memories": len(points), "total_apps": 0, "apps": []}
    except Exception:
        return {"total_memories": 0, "total_apps": 0, "apps": []}


@app.get("/api-keys")
@app.get("/v1/api-keys")
def get_api_keys():
    return []


@app.get("/requests")
@app.get("/v1/requests")
def get_requests():
    return []


@app.get("/entities")
@app.get("/v1/entities")
def get_entities():
    return []


@app.get("/configure")
def get_configure():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        for section in ("llm", "embedder"):
            values = config.get(section, {}).get("config", {})
            if "api_key" in values:
                values["api_key"] = "***"
            headers = values.get("http_headers")
            if isinstance(headers, dict):
                values["http_headers"] = {name: "***" for name in headers}
        return config
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# FastMCP Integration (SSE + Streamable HTTP Combined at /mcp)
# ---------------------------------------------------------------------------
sse_app = mcp.sse_app()
stream_app = mcp.streamable_http_app()
combined_mcp_app = Starlette(routes=list(sse_app.routes) + list(stream_app.routes))
app.mount("/mcp", combined_mcp_app)

if __name__ == "__main__":
    port = int(os.environ.get("MEM0_SERVER_PORT", "11888"))
    uvicorn.run(app, host="127.0.0.1", port=port)
