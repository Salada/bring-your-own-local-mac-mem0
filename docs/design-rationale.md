# Design rationale

This project offers one low-cost default for ARM64 Apple Silicon Macs. It is not
trying to expose every possible database, model, transport, or deployment shape.
Use the pieces independently if the full opinionated stack does not fit.

## The cost problem

The author previously used Mem0 SaaS with Hermes and AGY, then added Codex. When
the official Codex plugin lifecycle hooks were enabled, retrieval happened before
each prompt, additional lookups could occur around tools, and a summary was stored
at every assistant `Stop` event. With five or six active agents, that Cloud request
pattern exhausted the useful free allowance.

The official plugin remains the easiest hosted integration and is appropriate for
users who value managed operation. This project targets the different constraint:
retain automatic memory with fewer paid calls and no Mem0 SaaS bill. See Mem0's
[Codex integration](https://docs.mem0.ai/integrations/codex#option-a-plugin-marketplace-recommended)
for the hosted plugin's current components and lifecycle behavior.

## Opinionated component choices

| Component | Default | Reason |
| --- | --- | --- |
| Memory runtime | Mem0 OSS on host Python | Keeps upstream Python packages and avoids a custom API container |
| Vector database | Qdrant container | Lowest observed RAM use among the vector stores evaluated on the author's Mac; this is a local observation, not a universal benchmark |
| Embeddings | Qwen3 Embedding through oMLX | Removes a paid embedding API and runs directly on Apple Silicon; BGE-M3 remains a smaller documented alternative |
| Fact extraction | Gemini 3.5 Flash-Lite | Free-tier availability, low latency, structured output, and enough capability for concise normalization |
| Agent integration | Direct local MCP plus two narrow Codex hooks | Keeps bounded prompt recall and turn capture without the plugin's wider pre/post-tool lifecycle surface |

The LLM provider is not the interactive coding agent. Mem0 asks it to produce
compact structured facts and update decisions. In the author's Korean/English
workload, Gemini normalized most facts into concise English while retaining proper
nouns in their original form. This is called normalization here, not translation.

As checked on 2026-09-09, Google's Gemini 3.5 Flash-Lite documentation lists
structured output and function calling, and the Gemini Developer API pricing page
lists standard input and output as free on the Free Tier. Google's limits are
project-specific, can change, and must be checked in AI Studio. The claim that one
project can sustain five or six personal coding agents for a month is the author's
observed workload, not a quota guarantee. See the
[model page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite),
[Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing), and
[rate-limit policy](https://ai.google.dev/gemini-api/docs/rate-limits).

## oMLX cache boundary

Paged SSD cache should not be credited for the current embedding latency. oMLX
0.6.4 describes `--paged-ssd-cache-dir` as an LLM prefix-cache feature. Its
embedding engine computes vectors in a single forward pass and does not reuse the
causal LLM KV cache. The embedding-only launchd template therefore intentionally
uses `--no-cache`.

Paged SSD cache can materially help repeated-prefix TTFT when the same oMLX server
also hosts a compatible local generation model. That is a separate workload and
is not enabled by this minimal stack. The current embedding benefit comes from
local MLX execution and avoiding network/API cost.

## Deletion boundary

Mem0 treats deletion by exact `memory_id` as a normal single-record operation and
documents MCP agents deleting irrelevant memories or acting on a user request.
This project therefore keeps the familiar `delete_memory` MCP tool instead of
forcing every correction through a separate command. See Mem0's
[deletion guide](https://docs.mem0.ai/core-concepts/memory-operations/delete).

The local tool is intentionally stricter than the hosted signature. A caller must
supply the hash, revision, and scope from the reviewed record. The server checks
them before and after capturing a verified local backup, then deletes at most that
one ID under the maintenance lock. This prevents a stale search result or a
concurrent update from being deleted silently. Asking the user first remains an
agent workflow rule; a boolean supplied by the same agent would not prove human
approval and is not presented as a security boundary.

`delete_all_memories` is not exposed because its blast radius is qualitatively
different. A backup generation contains a Qdrant snapshot and history database.
`mem0-backup restore` can replace both stores from one exact verified generation,
but only after capturing a private rollback generation and stopping the API. A
persistent marker prevents the API from starting if replacement fails between the
two stores. This recovery path does not reduce bulk deletion to a single-record
operation and does not authorize unattended Dream execution.

## Non-goals

- Maximum provider flexibility or a configuration option for every component.
- A fully offline or privacy-first pipeline. Conversation content is sent to the
  selected cloud fact-extraction model.
- A claim that these choices are universally cheapest. Hardware, quotas, model
  pricing, and organizational policy change.
- Unattended destructive memory cleanup. Dream remains human-approved even though
  the rest of the stack is optimized for low operating friction.
