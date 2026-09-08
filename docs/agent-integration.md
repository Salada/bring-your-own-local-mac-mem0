# Connect coding agents

The supported default is Direct MCP. It gives Codex, OpenCode, and AGY the same
loopback-only Mem0 tools without installing a Mem0 Cloud plugin. The
`mem0-local-admin` skill and Codex lifecycle hooks are separate opt-ins.

## Configure installed agents

Install and start the [runtime](../runtime/README.md), then run:

```bash
$HOME/.config/mem0/bin/mem0-ctl health
$HOME/.config/mem0/bin/mem0-ctl agents configure
```

The second command detects installed copies of `codex`, `opencode`, and `agy`,
then adds or updates a server named `mem0` at
`http://127.0.0.1:11888/mcp`. Select clients explicitly when necessary:

```bash
$HOME/.config/mem0/bin/mem0-ctl agents configure codex agy
```

Set `MEM0_MCP_URL` only when the loopback port or path was deliberately changed.
Do not point this unauthenticated local deployment at a public interface.

The helper delegates configuration to each client's native command instead of
editing three evolving config formats. These equivalent commands were checked
with Codex CLI 0.153.4, OpenCode 1.18.29, and AGY 1.1.27:

```bash
codex mcp add mem0 --url http://127.0.0.1:11888/mcp
opencode mcp add mem0 --url http://127.0.0.1:11888/mcp
agy mcp add --type http mem0 http://127.0.0.1:11888/mcp
```

Codex stores the connection in `~/.codex/config.toml`; its desktop app, CLI,
and IDE extension share that configuration. OpenCode stores it under the `mcp`
object in its effective `opencode.json`/`opencode.jsonc`. AGY owns its own MCP
configuration; use `agy mcp` rather than editing that file directly. See the
[Codex MCP documentation](https://developers.openai.com/codex/mcp) and
[OpenCode MCP documentation](https://opencode.ai/docs/mcp-servers/).

## Restart and verify

Configuration proves only that an endpoint was saved. Start a new agent session
after adding the server. Restart the Codex desktop app or IDE extension when it
asks; in Codex CLI, start a new conversation.

```bash
$HOME/.config/mem0/bin/mem0-ctl agents status
```

Then inspect the active session:

- Codex: open `/mcp` (`/mcp verbose` when available) and confirm that `mem0` is
  connected and its tools are present.
- OpenCode: `opencode mcp list` must show `mem0` as connected.
- AGY: `agy mcp list` must show an enabled HTTP server named `mem0`.

Finally ask the agent to call `search_memories` for a real prior decision. Direct
MCP makes tools available; it does not guarantee that a model will call one on
every prompt. The server returns MCP `instructions` that tell compatible clients
to search at task start, but model-selected calls remain probabilistic.

When a regression test needs exact identity, store a unique value in
`metadata.marker` and retrieve it with a metadata filter. A marker-only
`search_memories` request is semantic vector search: it may rank the exact marker
first, but that ordering is not an exact-match contract. Use filtered
`get_memories` to test storage identity, and a natural-language
`search_memories` request separately to test semantic retrieval.

When server tool names or schemas change, restart the client session and inspect
the newly exposed tool list. Codex builds an initial MCP tool catalog and its
official clients expose explicit restart controls; an API event named
`mcp_list_tools.completed` confirms that tool discovery is a distinct operation,
but it does not by itself guarantee live refresh behavior in every Codex client.

## Optional: deterministic Codex recall and capture

Direct MCP calls are model-selected. The repository's Codex hooks instead perform
a bounded semantic lookup on `UserPromptSubmit` and capture substantive final
responses on `Stop`. They are optional because they add a request to ordinary
turns and currently target Codex only.

```bash
$HOME/.config/mem0/bin/mem0-ctl codex-hooks install
$HOME/.config/mem0/bin/mem0-ctl codex-hooks status
```

Installation preserves unrelated entries in `~/.codex/hooks.json`, writes the
file atomically, and keeps the original as `hooks.json.before-mem0`. Start a new
Codex session afterward, open `/hooks`, review the exact commands, and trust
them. Codex deliberately skips new or changed user hooks until their current
hash is trusted. `codex-hooks status` checks file configuration, not that trust
decision. See the [Codex hooks documentation](https://developers.openai.com/codex/hooks).

The installer owns `~/.codex/hooks.json`. If the same user config layer already
defines inline `[hooks]` tables in `~/.codex/config.toml`, integrate the entries
manually instead; Codex loads both representations but warns about the mixed
configuration. To remove only these two hooks:

```bash
$HOME/.config/mem0/bin/mem0-ctl codex-hooks uninstall
```

OpenCode and AGY receive Direct MCP only. A project may add a short instruction
such as “search Mem0 for relevant past decisions before changing code,” but an
instruction is still model-driven rather than deterministic lifecycle automation.

## Optional: administration skill

The skill is not required for ordinary recall, writes, or guarded single-record
operations. Install it only for explicit `review`, `forget`, or human-approved
Dream workflows. Pin the skill to the same release as the runtime; for the
currently tested release:

```bash
npx skills add \
  https://github.com/Salada/bring-your-own-local-mac-mem0/tree/v0.1.2 \
  --skill mem0-local-admin --full-depth -g -y --copy
```

The skill disables implicit invocation. Invoke `$mem0-local-admin` explicitly.

## Update

Check out a reviewed release, synchronize executable runtime files without
overwriting local secrets or data, and refresh dependencies:

```bash
rsync -a --exclude '.venv' --exclude '.env' --exclude 'config.json' \
  runtime/ "$HOME/.config/mem0/"
cd "$HOME/.config/mem0"
uv sync
./bin/mem0-ctl restart
./bin/mem0-ctl agents configure
./bin/mem0-ctl codex-hooks install  # only if previously enabled
```

Reinstall the optional skill from the matching new tag, then start new agent
sessions so they discover the current schemas.

## Disconnect or remove

Disconnecting an agent does not delete stored memories:

```bash
codex mcp remove mem0
agy mcp remove mem0
```

OpenCode 1.18.29 has no `mcp remove` command. Remove only the `mem0` entry from
the `mcp` object in the effective OpenCode config, then confirm with
`opencode mcp list`. Remove Codex hooks separately with the command above.

Stop the runtime with `mem0-ctl stop`. Keep `~/.local/share/mem0` unless the
stored database and backups have been reviewed and a separate destructive
deletion has been explicitly approved.
