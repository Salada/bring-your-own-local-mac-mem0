"""Focused, dependency-free stdio MCP server for local memory search."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from local_memory import memory_text, search_memories, sensitive

TOOL = {
    "name": "search_memories",
    "description": "Search durable memories in the loopback-only local Mem0 service.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What durable context to recall.",
            },
            "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            "threshold": {"type": "number", "minimum": 0, "maximum": 1},
            "project": {
                "type": "string",
                "description": "Optional app_id; defaults to the current directory name.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


def response(
    request_id: Any, result: Any = None, error: dict[str, Any] | None = None
) -> dict[str, Any]:
    value = {"jsonrpc": "2.0", "id": request_id}
    value["error" if error else "result"] = error or result
    return value


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")
    if method == "initialize":
        version = (message.get("params") or {}).get("protocolVersion", "2024-11-05")
        return response(
            request_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mem0-local-search", "version": "0.1.0"},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return response(request_id, {})
    if method == "tools/list":
        return response(request_id, {"tools": [TOOL]})
    if method != "tools/call":
        return response(
            request_id, error={"code": -32601, "message": f"Method not found: {method}"}
        )
    params = message.get("params") or {}
    if params.get("name") != TOOL["name"]:
        return response(request_id, error={"code": -32602, "message": "Unknown tool"})
    arguments = params.get("arguments") or {}
    query = str(arguments.get("query") or "").strip()
    if not query:
        return response(
            request_id, error={"code": -32602, "message": "query is required"}
        )
    try:
        top_k = min(max(int(arguments.get("top_k", 5)), 1), 20)
        threshold = arguments.get("threshold")
        threshold = float(threshold) if threshold is not None else None
        app_id = str(arguments.get("project") or Path.cwd().name or "unknown")
        items = search_memories(query, app_id, limit=top_k, threshold=threshold)
        clean = []
        for item in items[:top_k]:
            text = memory_text(item)
            if text and not sensitive(text):
                clean.append(
                    {"id": item.get("id"), "memory": text, "score": item.get("score")}
                )
        text = json.dumps({"results": clean}, ensure_ascii=False)
        return response(request_id, {"content": [{"type": "text", "text": text}]})
    except Exception as exc:  # noqa: BLE001 - MCP returns a bounded tool error
        return response(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": f"Local Mem0 search unavailable: {type(exc).__name__}",
                    }
                ],
                "isError": True,
            },
        )


def main() -> int:
    for line in sys.stdin:
        try:
            message = json.loads(line)
            output = handle(message) if isinstance(message, dict) else None
            if output is not None:
                print(json.dumps(output, ensure_ascii=False), flush=True)
        except Exception as exc:  # noqa: BLE001 - keep the stdio server alive after bad input
            print(
                json.dumps(
                    response(
                        None,
                        error={
                            "code": -32700,
                            "message": f"Parse error: {type(exc).__name__}",
                        },
                    )
                ),
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
