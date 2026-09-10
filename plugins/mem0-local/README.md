# Local Mem0 Codex plugin

This repository-local plugin follows the current Mem0 Codex integration shape:
one focused `search_memories` MCP tool, six user-facing skills, and all eight
documented lifecycle hooks. It talks only to the existing loopback service at
`http://127.0.0.1:11888` by default and sends no telemetry.

## Lifecycle

`SessionStart`, `UserPromptSubmit`, `PostToolUse`, `SubagentStart`,
`SubagentStop`, `Stop`, `PreCompact`, and `SessionEnd` are declared in
`hooks/hooks.json`. Hooks return quickly: they write bounded evidence to a
private SQLite queue, and a detached worker performs extraction at a batch
boundary. A failed local service never blocks the Codex turn.

The plugin data directory contains short-lived prompt, response, tool, and
subagent evidence until a successful flush. It is created with mode `0700`; the
database and error log use mode `0600`. Pause prevents new recall and capture but
does not delete queued evidence or durable memories.

## Profiles

Set the shared profile or override either axis:

```text
MEM0_CODEX_MEMORY_PROFILE=conservative|balanced|aggressive
MEM0_CODEX_RECALL_LEVEL=conservative|balanced|aggressive
MEM0_CODEX_CAPTURE_LEVEL=conservative|balanced|aggressive
```

`balanced` is the default. Conservative recall searches only the first
substantive prompt and injects at most two high-confidence results; conservative
capture records only explicit remember requests. Balanced recall searches the
first substantive prompt and injects at most five results; capture flushes at 10
events, 40,000 source characters, compaction, or session end. Aggressive recall
also bootstraps a session and searches every substantive prompt, while capture
flushes after every completed turn. Explicit MCP search remains available in
all profiles.

## Install

Do not run the legacy global hooks and this plugin together, because both would
recall and capture the same turn. Remove only this repository's legacy hook
entries, register the repository marketplace, and install the plugin:

```bash
mem0-ctl codex-hooks uninstall
codex plugin marketplace add /absolute/path/to/bring-your-own-local-mac-mem0
codex plugin add mem0-local@byolm-mem0
```

Start a new Codex thread after installation so the skills, hooks, and MCP server
are loaded together. The legacy installer remains available for clients that do
not support plugins.

All profiles keep project and user scope, secret rejection, bounded context, and
fail-open hooks. None performs deletion, category backfill, Dream, or telemetry.

## Validation

```bash
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/mem0-local
for skill in plugins/mem0-local/skills/*; do
  python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py "$skill"
done
python3 -m unittest discover -s plugins/mem0-local/tests
```
