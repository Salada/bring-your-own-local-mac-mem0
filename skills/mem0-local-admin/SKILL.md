---
name: mem0-local-admin
description: Review and safely maintain the user's localhost Mem0 store through the deterministic mem0-admin CLI. Use only when explicitly invoked for deep context, memory audits, targeted forgetting, or bounded dream cleanup; do not use for ordinary automatic recall or Cloud Mem0.
---

# Mem0 Local Admin

Use the local `mem0-admin` CLI for deterministic analysis and guarded mutation. Keep the existing lightweight prompt hook as the ordinary recall path.

## Scope

Resolve the active project to the literal basename of the current working directory and pass it with `--app-id` unless the user explicitly requests a user-wide operation. Never send a request to `api.mem0.ai`.

## Modes

- Deep context: run `mem0-admin context "<task>" --app-id "<project>"` and present only relevant results.
- Review: run `mem0-admin review --app-id "<project>"`. This is read-only. Treat near-duplicate output as candidates, not facts; contradictions always require human judgment.
- Forget: first run `mem0-admin forget "<query>" --app-id "<project>"`. Show the candidates and ask the user to approve one exact memory ID. Only then run `mem0-admin forget --id "<id>" --yes`.
- Dream preview: run `mem0-admin dream --dry-run --app-id "<project>"`. Show the plan path, action count, reasons, backup/recovery implications, and ask for approval.
- Dream apply: only after approval of that exact plan, run `mem0-admin dream --apply "<plan>" --yes`.
- Bounded auto mode is for a human-operated interactive terminal only. Never pass `--yes`; the command prints its exact plan and requires the human to type confirmation before applying at most ten eligible actions.

## Safety boundary

- Never call MCP `delete_memory` or `delete_all_memories` for these workflows; guarded deletion belongs to `mem0-admin`.
- Never delete fuzzy duplicates, contradictions, pinned memories, merely low-confidence memories, or items whose hash/revision changed after review.
- Never schedule auto mode. A future unattended schedule requires a separately reviewed restore command and recovery drill.
- Stop on incomplete pagination, failed backup, changed memory revision, partial result, or missing confirmation. Report the plan, result, and backup paths verbatim.
