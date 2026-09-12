# Project boundaries

- This GitHub repository is the source of truth for the portable local Mem0 runtime
  and its Codex administration skill.
- `docs/platform-gap-plan.md` is the sole living plan for Platform-to-local
  capability decisions; update affected IDs in implementation PRs.
- Put executable behavior, REST or MCP endpoints, database operations, backups,
  maintenance commands, and tests under `runtime/`.
- Put Codex instructions and invocation metadata under
  `skills/mem0-local-admin/`. Skills must call guarded runtime commands rather than
  reimplement mutations or invoke raw MCP deletion tools.
- Keep machine-specific service rendering, secrets, personal identities, private
  hostnames, and private backup destinations outside the repository.
- Default all services to loopback. Do not add public network exposure or telemetry.
- Memory mutations require scope and revision validation. Cleanup also requires a
  verified backup, an exclusive lock, and a hard action limit.
- Dream mutation requires explicit human approval. `--auto` is a bounded selection
  mode, not unattended authorization. Do not schedule Dream.
- Release runtime and skill compatibility together. Consumers must pin a tag or
  commit rather than track an unreviewed moving branch.
- Prefer upstream packages and official container images. Test compatibility before
  changing pinned versions.
