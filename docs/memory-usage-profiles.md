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

This local project currently uses a different, simpler policy:

- `UserPromptSubmit` searches every prompt of at least 8 characters, requests 6
  candidates, keeps scores at or above 0.5, and injects at most 3 memories under
  an approximate 1,000-token hook limit; and
- `Stop` sends every non-sensitive assistant response of at least 120 characters
  through Mem0 extraction.

The local search path uses local embeddings and Qdrant, but each accepted capture
can invoke the configured extraction LLM. Recall intensity and capture intensity
therefore have different quality, latency, and cost effects.

Sources inspected:

- [OpenAI memory controls](https://learn.chatgpt.com/docs/customization/memories)
- [OpenAI Codex hook lifecycle](https://learn.chatgpt.com/docs/hooks)
- [Mem0 Codex integration](https://docs.mem0.ai/integrations/codex)
- [Mem0 0.3.1 Codex hooks](https://github.com/mem0ai/mem0/blob/02f7a9b2c4fe38dedb96631e48c85c74ad58b605/integrations/codex-plugin/hooks/hooks.json)
- [Mem0 0.3.1 shared hook runner](https://github.com/mem0ai/mem0/blob/02f7a9b2c4fe38dedb96631e48c85c74ad58b605/integrations/agent-plugin-core/python/hook_runner.py)
- [Mem0 0.3.1 shared memory core](https://github.com/mem0ai/mem0/blob/02f7a9b2c4fe38dedb96631e48c85c74ad58b605/integrations/agent-plugin-core/python/memory_core.py)

## Recommendation: profiles, not one score

A single weight is misleading. Lowering a similarity threshold broadens recall,
but it should not silently make the agent write more memories. Expose one named
profile for the common case and two independent overrides:

```text
MEM0_CODEX_MEMORY_PROFILE=conservative|balanced|aggressive
MEM0_CODEX_RECALL_LEVEL=conservative|balanced|aggressive
MEM0_CODEX_CAPTURE_LEVEL=conservative|balanced|aggressive
```

The profile sets both levels. Either level override, when present, changes only
its own axis. Keep `balanced` as the default so an upgrade preserves today's
behavior.

| Level | Automatic recall | Automatic capture |
| --- | --- | --- |
| `conservative` | Search only the first substantive prompt in a session; inject at most 2 strong matches | No automatic writes; explicit `add_memory` remains available |
| `balanced` | Preserve the current per-prompt lookup, 6-candidate search, 0.5 score gate, 3-result cap, and approximate 1,000-token hook limit | Preserve the current `Stop` capture with the 120-character and secret guards |
| `aggressive` | Add one session bootstrap, search every substantive prompt, allow up to 5 matches, and permit at most one cue-driven follow-up for resume/error prompts | Capture eligible `Stop` results and add a pre-compaction fallback |

Exact candidate counts and thresholds should remain profile constants initially,
not another public configuration matrix. The MCP `search_memories` tool already
supports per-call `top_k`, `threshold`, and `rerank` for exceptional searches.
After fixture-based evaluation, advanced overrides can be added only for values
users demonstrably need to tune.

`aggressive` should still be bounded. Do not issue memory API calls for every file
read or every tool result. Those events amplify with agent activity and were the
main source of surprising request volume in the older plugin design. Tool failures
can contribute a short cue to the next prompt lookup without creating an
additional per-tool search.

## Call budget

The resolved policy should make its upper bound observable through
`mem0-ctl codex-hooks status`:

| Profile | Automatic searches | Automatic extraction writes |
| --- | --- | --- |
| `conservative` | At most 1 per session | 0 |
| `balanced` | At most 1 per eligible prompt | At most 1 per eligible completed turn |
| `aggressive` | 1 bootstrap, 1 per eligible prompt, and at most 1 cue follow-up per turn | At most 1 per eligible completed turn, plus a deduplicated compaction fallback |

The status output should show the resolved profile, recall level, capture level,
hook events, result cap, context budget, and capture minimum. It must never show
memory text, prompts, or secrets.

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

## Staged implementation

1. Add strict profile parsing to `codex_hook.py`, with `balanced` reproducing the
   current output byte-for-byte for the same hook input.
2. Make hook installation select only the lifecycle events required by the
   resolved levels. Conservative capture should not install a write hook.
3. Add session-local counters and deduplication only for bootstrap, first-prompt,
   cue follow-up, and pre-compaction behavior; do not adopt the upstream event
   store until a real batching requirement justifies it. Store only counters and
   content digests under `$HOME/.local/state/mem0/codex-hooks/`, key them by a
   hashed session ID, remove them at session end, and expire stale entries. Never
   persist prompts or memory text in this control state.
4. Extend `codex-hooks status` to print the resolved, redacted call budget.
5. Test invalid configuration, every profile mapping, per-session/per-turn caps,
   compaction deduplication, secret rejection, and preservation of unrelated
   hooks.
6. Evaluate Korean and English positive/negative prompt fixtures for recall hit
   rate, irrelevant injection rate, injected characters, hook latency, extraction
   calls, and duplicate memories. Keep `balanced` as the release default unless
   those measurements justify a migration.

This iteration is a design only. It does not change installed hooks, stored
memories, the extraction provider, or the current runtime default.
