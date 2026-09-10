---
name: mem0-local-admin
description: Review and safely maintain the user's localhost Mem0 store through the deterministic mem0-admin CLI. Use only when explicitly invoked for deep context, memory audits, category backfill, targeted forgetting, or bounded dream cleanup; do not use for ordinary automatic recall or Cloud Mem0.
---

# Mem0 Local Admin

Use the local `mem0-admin` CLI for deterministic analysis and guarded mutation. Keep the existing lightweight prompt hook as the ordinary recall path.

## Scope

Resolve the active project to the literal basename of the current working directory and pass it with `--app-id` unless the user explicitly requests a user-wide operation. Never send a request to `api.mem0.ai`.

## Category behavior

- New memories are categorized automatically by the runtime's background enrichment worker. Do not invoke this skill for ordinary new writes.
- `mem0-admin categorize` is only for an explicitly requested, user-wide backfill of existing records. Changing `custom_categories` does not by itself re-tag older memories.
- Dry-run still sends eligible memory text to the configured LLM and can incur provider cost, but it does not update Qdrant. State this before running it.
- Apply classifies again rather than replaying a frozen plan, so its LLM result can differ from the preview. Keep the same bound, require fresh approval, and report the resulting backup and counts.

## Modes

- Deep context: run `mem0-admin context "<task>" --app-id "<project>"` and present only relevant results.
- Review: run `mem0-admin review --app-id "<project>"`. This is read-only. Treat near-duplicate output as candidates, not facts; contradictions always require human judgment.
- Category preview: confirm the user-wide scope and LLM disclosure above, then run `mem0-admin categorize --dry-run --max-items <bound>`. Report `scanned`, `categorized`, `has_more`, and the proposed category counts before requesting approval.
- Category apply: only after the user reviews the preview and approves the user-wide mutation, run `mem0-admin categorize --apply --max-items <same-bound> --yes`. Do not add `--overwrite` unless the user explicitly requests recategorizing records that already have categories.
- Forget: first run `mem0-admin forget "<query>" --app-id "<project>"`. Show the candidates and ask the user to approve one exact memory ID. Only then run `mem0-admin forget --id "<id>" --yes`.
- Dream preview: run `mem0-admin dream --dry-run --app-id "<project>"`. Show the plan path, action count, reasons, backup/recovery implications, and ask for approval.
- Dream apply: only after approval of that exact plan, run `mem0-admin dream --apply "<plan>" --yes`.
- Bounded auto mode is for a human-operated interactive terminal only. Never pass `--yes`; the command prints its exact plan and requires the human to type confirmation before applying at most ten eligible actions.

## Safety boundary

- Do not use MCP `delete_memory` for Dream or multi-item cleanup; those workflows belong to `mem0-admin`. MCP single-item deletion is acceptable only after the user reviews the exact memory and explicitly approves its guarded hash/revision/scope call. The server deterministically enforces those preconditions and a verified backup; it cannot independently prove conversational approval. `delete_all_memories` is not exposed.
- Never delete fuzzy duplicates, contradictions, pinned memories, merely low-confidence memories, or items whose hash/revision changed after review.
- Never schedule auto mode. A future unattended schedule requires a separately reviewed restore command and recovery drill.
- Category apply must remain bounded and use the CLI so a verified backup is captured before the first payload-only update. Never call the raw backfill endpoint to bypass this guard.
- Stop on incomplete pagination, failed backup, changed memory revision, partial result, or missing confirmation. Report the plan, result, and backup paths verbatim.
