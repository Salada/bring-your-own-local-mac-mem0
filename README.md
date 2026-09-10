# Bring Your Own Local Mac Mem0

Run Mem0 locally on an Apple Silicon Mac, expose it to coding agents over MCP,
and maintain it through guarded administrative workflows.

## Why this exists

This is an opinionated low-cost baseline, not a general-purpose Mem0 distribution.
It was created after the author enabled the official Mem0 Codex plugin lifecycle
hooks alongside several Hermes and AGY agents. Prompt retrieval, tool-related
lookups, turn summaries, and compaction capture made Mem0 Cloud's free allowance
impractical for that workload.

The replacement keeps Qdrant and embeddings on one Apple Silicon Mac, batches
the Codex lifecycle surface locally, and uses Gemini 3.5 Flash-Lite for the small structured
fact-extraction job. The goal is to give ARM64 Mac users one inexpensive default
they can run without designing a memory platform first. It is deliberately not a
maximally flexible provider framework.

Read [`docs/design-rationale.md`](docs/design-rationale.md) for the cost model,
tradeoffs, and the boundary between local embeddings and cloud fact extraction.

The repository is intentionally split into two paths:

| Goal | Start here |
| --- | --- |
| Install or operate the local stack | [`runtime/README.md`](runtime/README.md) |
| Connect Codex, Claude Code, OpenCode, AGY, or Hermes | [`docs/agent-integration.md`](docs/agent-integration.md) |
| Install the full local Codex lifecycle plugin | [`plugins/mem0-local/README.md`](plugins/mem0-local/README.md) |
| Restore one exact backup generation | [`docs/restore.md`](docs/restore.md) |
| Optionally install the Codex administration skill | [`skills/mem0-local-admin/README.md`](skills/mem0-local-admin/README.md) |

## Safety defaults

- Services bind to `127.0.0.1`; this project does not provide production authentication.
- The default memory namespace is `local-user` and can be changed with
  `MEM0_DEFAULT_USER_ID`.
- Telemetry is disabled for Mem0, Qdrant, and the dashboard.
- Administrative mutation uses revision, scope, backup, and action-count guards.

## Repository boundaries

- `runtime/` owns executable behavior, APIs, storage guards, deployment examples,
  and tests.
- `plugins/mem0-local/` owns the Codex lifecycle hooks, focused search tool, and
  user-facing memory controls.
- `skills/mem0-local-admin/` owns Codex guidance only. It does not implement or
  bypass mutation logic.
- Machine-specific configuration, secrets, and personal backup destinations belong
  outside this repository.

## Requirements

- Apple Silicon Mac running macOS 15 or newer
- Homebrew, Docker or OrbStack, `uv`, `jq`, and `omlx`
- A Google AI Studio API key for fact extraction
- About 3 GB for the local embedding model, plus storage for containers and memories

This does not require Mem0 Cloud. Data privacy is not the primary design goal:
the configured cloud LLM receives conversation content for fact extraction.
Loopback binding, secret handling, and guarded deletion are operational safety
defaults, not a claim that the full pipeline is offline.

## License and upstream relationship

This project is licensed under the [Apache License 2.0](LICENSE). It is an
independent project built for interoperability with
[Mem0](https://github.com/mem0ai/mem0), whose upstream repository is also
licensed under Apache-2.0 at the time of this release. See [NOTICE](NOTICE) for
attribution and scope.
