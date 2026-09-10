# Codex memory usage profiles

This note separates three different products that are easy to call “ChatGPT
memory”:

- ChatGPT web uses ChatGPT memory.
- Local Codex clients use OpenAI's separate local memory store and controls.
- This project connects Codex to local Mem0 through MCP and optional lifecycle
  hooks.

OpenAI documents an on/off choice for whether a chat may use local memories or
contribute future memories. It does not document a numeric aggressiveness weight.
Any conservative/aggressive control described here therefore belongs to this
project's Mem0 integration, not to ChatGPT's native memory setting.

## What the current integrations do

As checked on 2026-09-10, Mem0's current Codex plugin is version 0.3.1. It no
longer follows the high-request pattern used by earlier plugin releases. It:

- searches once, on the first prompt of at least 20 characters;
- records prompts, responses, tool outcomes, and subagent results locally for
  later extraction;
- flushes accumulated evidence in the background after 5 exchanges, 10 messages,
  or 40,000 source characters, after 300 seconds idle, before compaction, and at
  session end; and
- leaves later recall to the explicit `search_memories` tool.

The implementation caps explicit search at 20 results, defaults it to 3, disables
reranking, and limits injected context to 4,000 characters. The automatic
first-prompt search asks for 5 results directly, so changing the general `top_k`
option does not change that hook.

This project now ships a repository-local plugin with the same public lifecycle
shape: all eight documented hooks, one focused search tool, six skills, and a
private evidence queue. The older `mem0-ctl codex-hooks` integration remains as
a compatibility path for clients without plugin support:

- its `UserPromptSubmit` searches every prompt of at least 8 characters, requests 6
  candidates, keeps scores at or above 0.5, and injects at most 3 memories under
  an approximate 1,000-token hook limit; and
- its `Stop` sends every non-sensitive assistant response of at least 120 characters
  through Mem0 extraction.

Do not install both paths together. The plugin batches lifecycle evidence before
calling the configured extraction LLM, while recall continues to use local
embeddings and Qdrant. Recall intensity and capture intensity therefore have
different quality, latency, privacy, and cost effects.

Sources inspected:

- [OpenAI memory controls](https://learn.chatgpt.com/docs/customization/memories)
- [OpenAI Codex hook lifecycle](https://learn.chatgpt.com/docs/hooks)
- [Mem0 Codex integration](https://docs.mem0.ai/integrations/codex)
- [Mem0 0.3.1 Codex hooks](https://github.com/mem0ai/mem0/blob/02f7a9b2c4fe38dedb96631e48c85c74ad58b605/integrations/codex-plugin/hooks/hooks.json)
- [Mem0 0.3.1 shared hook runner](https://github.com/mem0ai/mem0/blob/02f7a9b2c4fe38dedb96631e48c85c74ad58b605/integrations/agent-plugin-core/python/hook_runner.py)
- [Mem0 0.3.1 shared memory core](https://github.com/mem0ai/mem0/blob/02f7a9b2c4fe38dedb96631e48c85c74ad58b605/integrations/agent-plugin-core/python/memory_core.py)

## Implemented policy: profiles, not one score

A single weight is misleading. Lowering a similarity threshold broadens recall,
but it should not silently make the agent write more memories. Expose one named
profile for the common case and two independent overrides:

```text
MEM0_CODEX_MEMORY_PROFILE=conservative|balanced|aggressive
MEM0_CODEX_RECALL_LEVEL=conservative|balanced|aggressive
MEM0_CODEX_CAPTURE_LEVEL=conservative|balanced|aggressive
```

The profile sets both levels. Either level override, when present, changes only
its own axis. `balanced` is the default.

| Level | Automatic recall | Automatic capture |
| --- | --- | --- |
| `conservative` | Search the first prompt of at least 20 characters; inject at most 2 results at score 0.65+ | Queue only explicit English or Korean remember requests and flush after the completed response |
| `balanced` | Search the first prompt of at least 20 characters; inject at most 5 results at score 0.5+ | Queue lifecycle evidence; flush at 10 events, 40,000 characters, pre-compaction, or session end |
| `aggressive` | Search at session bootstrap and every prompt of at least 20 characters; inject at most 8 results at score 0.35+ | Queue lifecycle evidence and flush after every completed turn, pre-compaction, or session end |

Candidate counts and thresholds remain profile constants rather than another
public configuration matrix. The MCP `search_memories` tool supports per-call
`top_k` and `threshold`, caps explicit search at 20, and remains available in all
profiles.

`aggressive` remains bounded. Tool events are queued locally and never cause an
individual extraction request. Secret-like events are rejected before they enter
the queue, and the extraction worker deduplicates identical evidence within a
session.

## Call budget

The `status` skill reports the resolved policy and redacted queue counters:

| Profile | Automatic searches | Automatic extraction writes |
| --- | --- | --- |
| `conservative` | At most 1 per session | Only after an explicit remember request |
| `balanced` | At most 1 per session | One per batch boundary; all remaining evidence at compaction/end |
| `aggressive` | 1 bootstrap plus 1 per eligible prompt | At most 1 per completed turn; all remaining evidence at compaction/end |

Status shows recall and capture levels, result/context bounds, pause state, active
session count, and pending event count. It never shows memory text, prompts, or
secrets.

## Invariants for every profile

- Direct MCP stays available even when automatic recall or capture is disabled.
- Injected memories remain labelled as historical notes, never instructions.
- Current system, developer, repository, and user instructions take precedence.
- Existing secret detection and fail-open hook behavior remain enabled.
- No profile performs deletion, backfill, Dream, or any other administrative
  mutation.
- No profile enables telemetry or changes the loopback-only service boundary.
- Aggressiveness never broadens user, project, agent, or run scope.
- Compaction fallback must deduplicate an already captured turn.

## Storage and lifecycle boundary

All eight hooks stay installed so pause/resume, compaction, and parent-to-subagent
handoff remain predictable. Profiles select behavior inside those hooks. Bounded
prompt, response, tool, and subagent evidence is stored under Codex's private
`${PLUGIN_DATA}` directory until a successful extraction flush. Failed or crashed
flushes leave recoverable pending evidence; `SessionStart` retries it.

`PreCompact` and `SessionEnd` start detached flushes because hook execution has a
three-second budget and local extraction may take longer. This makes durable
capture eventually consistent rather than a synchronous completion guarantee.
See [ADR 0002](decisions/0002-codex-plugin-lifecycle.md) for the decision and SaaS
parity boundary.
