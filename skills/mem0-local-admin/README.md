# mem0-local-admin

Explicit-only Codex skill for the local `mem0-admin` CLI.

It covers deep context retrieval, full memory review, confirmation-based forgetting,
and bounded exact/temporary cleanup. Mutating operations require the deterministic
CLI's scope and revision guards plus a verified pre-mutation backup.

The skill intentionally does not schedule unattended cleanup or delete fuzzy,
contradictory, pinned, or merely low-confidence memories.

For the origin and safety model of the `dream` command, see
[`docs/dream.md`](../../docs/dream.md).
