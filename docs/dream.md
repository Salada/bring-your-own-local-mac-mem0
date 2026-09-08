# Dream memory maintenance

`dream` is a Mem0 administration command, not a general reference to sleep. The
name comes from Mem0's
[`mem0-dream` workflow](https://github.com/mem0ai/mem0/blob/main/integrations/mem0-plugin/.opencode-plugin/opencode-skills/mem0-dream/SKILL.md),
which treats memory maintenance as a consolidation pass over accumulated memory.

The local implementation deliberately has a narrower safety boundary than the
upstream workflow. It can plan deletion of exact duplicates and expired temporary
`session_state` or `compact_summary` records. It does not automatically resolve
contradictions, merge fuzzy matches, or delete pinned or merely low-confidence
memories.

## Modes

```bash
mem0-admin dream --dry-run --app-id PROJECT
mem0-admin dream --apply PLAN.json --yes
mem0-admin dream --auto --app-id PROJECT
```

- `--dry-run` scans the complete scope and writes a plan without changing memory.
- `--apply` revalidates the exact plan, creates and verifies a backup, and applies
  at most ten eligible actions.
- `--auto` combines deterministic plan generation with an interactive approval
  prompt. It prints the exact plan and deliberately rejects `--yes`, so it cannot
  serve as a non-interactive authorization path.

## Approval boundary

Every mutating Dream run requires explicit human approval of the exact scope and
plan. Dream is never scheduled. Unattended execution remains prohibited unless a
separate future safety decision introduces and validates an adequate recovery
mechanism.

The command stops on incomplete pagination, backup failure, revision changes,
scope changes, partial results, or missing confirmation. Use `review` for broader
diagnosis; contradictions and near-duplicates remain human decisions.
