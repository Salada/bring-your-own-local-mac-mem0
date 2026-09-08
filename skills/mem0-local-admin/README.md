# mem0-local-admin

Explicit-only Codex skill for the local `mem0-admin` CLI.

It covers deep context retrieval, full memory review, confirmation-based forgetting,
and bounded exact/temporary cleanup. Mutating operations require the deterministic
CLI's scope and revision guards plus a verified pre-mutation backup.

Install the skill only after the local runtime and MCP connection work. Pin it to
the runtime release; for the currently tested release:

```bash
npx skills add \
  https://github.com/Salada/bring-your-own-local-mac-mem0/tree/v0.1.2 \
  --skill mem0-local-admin --full-depth -g -y --copy
```

Start a new Codex session, then invoke `$mem0-local-admin` explicitly. The skill
does not enable automatic recall and is not part of the default agent setup. See
the [agent integration guide](../../docs/agent-integration.md) for MCP and hook
configuration.

The skill intentionally does not schedule unattended cleanup or delete fuzzy,
contradictory, pinned, or merely low-confidence memories.

For the origin and safety model of the `dream` command, see
[`docs/dream.md`](../../docs/dream.md).
