# Connect coding agents

Agent-specific newcomer guides:

- [OpenCode](agents/opencode.md) — locally tested setup, recall check, versioned
  configuration, removal, and troubleshooting
- [Claude Code](agents/claude.md) — official configuration contract and a
  **NOT TESTED LOCALLY** smoke-test procedure
- [Antigravity CLI (AGY)](agents/agy.md) — locally tested HTTP registration,
  documented-but-untested recall check, removal, and troubleshooting
- [Hermes Agent](agents/hermes.md) — locally tested discovery and connectivity,
  interactive setup, removal, and native-memory distinction

Direct MCP is the supported transport. It gives Codex, Claude Code, OpenCode,
AGY, and Hermes the same loopback-only Mem0 tools without installing a Mem0 Cloud
plugin. For Codex, the recommended reliable-recall baseline also includes the
bounded lifecycle hooks below. The `mem0-local-admin` skill remains a separate
opt-in.

## Configure installed agents

Install and start the [runtime](../runtime/README.md), then run:

```bash
$HOME/.config/mem0/bin/mem0-ctl health
$HOME/.config/mem0/bin/mem0-ctl agents configure
$HOME/.config/mem0/bin/mem0-ctl codex-hooks install
```

The second command detects installed copies of `codex`, `claude`, `opencode`,
`agy`, and `hermes`, then adds or updates a server named `mem0` at
`http://127.0.0.1:11888/mcp`. The third command is recommended when Codex is
installed; review and trust the hooks after restart as described below. Select
clients explicitly when necessary. If Hermes is installed, its native setup is
interactive and pauses the all-agent command for authentication and tool
selection; answer as described in the [Hermes guide](agents/hermes.md).

```bash
$HOME/.config/mem0/bin/mem0-ctl agents configure codex agy
```

Set `MEM0_MCP_URL` only when the loopback port or path was deliberately changed.
Do not point this unauthenticated local deployment at a public interface.

The helper delegates configuration to each client's native command instead of
editing evolving config formats. Codex CLI 0.153.4, OpenCode 1.18.29, AGY
1.1.27, and Hermes 0.21.0 were checked locally. The Claude command follows its
official contract but is **NOT TESTED LOCALLY**. The helper removes an existing
user-scoped `mem0` entry before adding it because Claude Code rejects a
duplicate name:

```bash
codex mcp add mem0 --url http://127.0.0.1:11888/mcp
claude mcp remove mem0 --scope user  # ignored by the helper when absent
claude mcp add --transport http mem0 --scope user http://127.0.0.1:11888/mcp
opencode mcp add mem0 --url http://127.0.0.1:11888/mcp
agy mcp add --type http mem0 http://127.0.0.1:11888/mcp
hermes mcp add mem0 --url http://127.0.0.1:11888/mcp  # interactive
```

Codex stores the connection in `~/.codex/config.toml`; its desktop app, CLI,
and IDE extension share that configuration. Claude Code stores a user-scoped
server in `~/.claude.json`. OpenCode stores it under the `mcp` object in its
effective `opencode.json`/`opencode.jsonc`. AGY owns its own MCP configuration;
use `agy mcp` rather than editing that file directly. Hermes stores MCP entries
per profile; use `hermes mcp` rather than editing its config directly. See the
[Codex MCP documentation](https://developers.openai.com/codex/mcp),
[Claude Code MCP documentation](https://code.claude.com/docs/en/mcp), and
[OpenCode MCP documentation](https://opencode.ai/docs/mcp-servers/), and the
[Hermes MCP documentation](https://nousresearch.github.io/hermes-agent/docs/user-guide/features/mcp).

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
- Claude Code: `claude mcp get mem0`, `claude mcp list`, and the in-session
  `/mcp` view should report `Connected`; this path is **NOT TESTED LOCALLY**.
- OpenCode: `opencode mcp list` must show `mem0` as connected.
- AGY: `agy mcp list` must show an enabled HTTP server named `mem0`; this checks
  saved configuration, not live reachability or a model tool call.
- Hermes: `hermes mcp test mem0` must report `Auth: none`, the exact loopback
  URL, a successful connection, and the discovered tools.

Finally ask the agent to call `search_memories` for a real prior decision. Direct
MCP makes tools available; it does not guarantee that a model will call one on
every prompt. In this project's original Codex testing, MCP-only configuration
recalled memories too rarely to be a dependable default. The server returns MCP
`instructions` that tell compatible clients to search at task start, but those
calls remain model-selected and probabilistic. The lifecycle hooks close that
gap for Codex.

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

## Recommended for Codex: deterministic recall and capture

Direct MCP calls are model-selected. The repository's Codex hooks instead perform
a bounded semantic lookup on `UserPromptSubmit` and capture substantive final
responses on `Stop`. This is the recommended Codex baseline because it does not
depend on the model deciding to call the search tool. Omit it only when you want
MCP capability without automatic retrieval and capture.

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

Claude Code, OpenCode, AGY, and Hermes receive Direct MCP only. A project may add a
short instruction such as “search Mem0 for relevant past decisions before
changing code,” but an instruction is still model-driven rather than
deterministic lifecycle automation.

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
./bin/mem0-ctl codex-hooks install  # recommended for Codex
```

Reinstall the optional skill from the matching new tag, then start new agent
sessions so they discover the current schemas.

## Disconnect or remove

Disconnecting an agent does not delete stored memories:

```bash
codex mcp remove mem0
claude mcp remove mem0 --scope user
agy mcp remove mem0
hermes mcp remove mem0
```

OpenCode 1.18.29 has no `mcp remove` command. Remove only the `mem0` entry from
the `mcp` object in the effective OpenCode config, then confirm with
`opencode mcp list`. Remove Codex hooks separately with the command above.

Stop the runtime with `mem0-ctl stop`. Keep `~/.local/share/mem0` unless the
stored database and backups have been reviewed and a separate destructive
deletion has been explicitly approved.
