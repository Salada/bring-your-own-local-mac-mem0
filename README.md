# Bring Your Own Local Mac Mem0

Run Mem0 locally on an Apple Silicon Mac, expose it to coding agents over MCP,
and maintain it through guarded administrative workflows.

The repository is intentionally split into two paths:

| Goal | Start here |
| --- | --- |
| Install or operate the local stack | [`runtime/README.md`](runtime/README.md) |
| Install the explicit Codex administration skill | [`skills/mem0-local-admin/README.md`](skills/mem0-local-admin/README.md) |

## Safety defaults

- Services bind to `127.0.0.1`; this project does not provide production authentication.
- The default memory namespace is `local-user` and can be changed with
  `MEM0_DEFAULT_USER_ID`.
- Telemetry is disabled for Mem0, Qdrant, and the dashboard.
- Administrative mutation uses revision, scope, backup, and action-count guards.

## Repository boundaries

- `runtime/` owns executable behavior, APIs, storage guards, deployment examples,
  and tests.
- `skills/mem0-local-admin/` owns Codex guidance only. It does not implement or
  bypass mutation logic.
- Machine-specific configuration, secrets, and personal backup destinations belong
  outside this repository.

## Requirements

- Apple Silicon Mac running macOS 15 or newer
- Homebrew, Docker or OrbStack, `uv`, `jq`, and `omlx`
- A Google AI Studio API key for fact extraction
- About 3 GB for the local embedding model, plus storage for containers and memories

This is a local-first project. It does not require Mem0 Cloud.

## License and upstream relationship

This project is licensed under the [Apache License 2.0](LICENSE). It is an
independent project built for interoperability with
[Mem0](https://github.com/mem0ai/mem0), whose upstream repository is also
licensed under Apache-2.0 at the time of this release. See [NOTICE](NOTICE) for
attribution and scope.
