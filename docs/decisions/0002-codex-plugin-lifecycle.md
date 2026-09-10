# ADR 0002: Local Codex memory lifecycle and profiles

- Status: Accepted
- Date: 2026-09-11

## Context

The legacy integration installs only `UserPromptSubmit` and `Stop`, searches on
every short prompt, and sends each eligible final response directly to the
extraction API. Current Mem0 Codex integration guidance instead describes one
focused search tool, six skills, and eight lifecycle hooks backed by local
evidence batching. The local deployment also needs an understandable choice
between conservative and aggressive memory use without changing its
loopback-only trust boundary.

## Decision

Ship a repository-local `mem0-local` Codex plugin with:

- all eight documented hooks installed for every profile;
- a dependency-free private SQLite evidence queue and detached batch worker;
- one read-only `search_memories` MCP tool, capped at 20 explicit results;
- `remember`, `search`, `forget`, `pause`, `resume`, and `status` skills;
- `balanced` as the default, with independent recall and capture overrides; and
- the existing `mem0-admin` guarded backup-and-recheck workflow for forgetting.

The repository exposes the plugin through a repo-local marketplace. Installing
it requires removing the legacy two-hook integration first; both must never run
together because that would duplicate recall and capture.

Profiles change policy, not installed capabilities. Conservative capture still
accepts an explicit remember request, balanced batches evidence until a size or
lifecycle boundary, and aggressive flushes each completed turn. Pre-compaction
and session-end always start a flush for remaining evidence. No profile broadens
user/project scope or enables telemetry.

## Why

Keeping all hooks makes lifecycle behavior predictable and preserves parent to
subagent context. Batching avoids an extraction LLM request for every tool event.
Separate recall and capture levels express two different costs and privacy
choices that a single “aggressiveness” number would hide. Reusing guarded
forgetting avoids creating a second destructive path.

## SaaS parity boundary

This matches the public Codex integration's hook and skill surface, local event
batching, first-prompt recall, and explicit search shape. It does not claim
server-side SaaS parity: extraction quality depends on the configured local Mem0
stack and LLM, local process lifetime replaces managed workers, and Cloud-only
observability or undisclosed ranking behavior is unavailable. The local plugin
adds explicit profiles and guarded deletion as deployment-specific controls.

## Consequences

Short-lived transcript evidence is stored locally until successful extraction,
so plugin data must remain private and excluded from version control. A crashed
worker leaves evidence recoverable on the next session start. Detached flushes
are eventually consistent, and session-end cannot promise completion before the
Codex process exits. Delivery is at least once: if the service accepts a batch but
the worker cannot observe the response, retry may produce a near-duplicate fact.
When Mem0 is unavailable, session recovery can start one bounded worker per
pending session; every worker times out and returns its batch to pending. Invalid
profile values fail open in hooks and produce a concise configuration error in
the status CLI, without exposing queued content.

## Rejected alternatives

- Extending only the two legacy hooks: it cannot cover compaction, subagents, or
  reliable session-end handoff.
- Writing to Mem0 after every tool event: excessive extraction cost and latency.
- Adding write/delete MCP tools: lifecycle capture already owns writes, while
  deletion requires the existing review, backup, and revision guard.
- Copying upstream telemetry: incompatible with the local-first privacy goal.
