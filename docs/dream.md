# Dream memory maintenance

`dream` is a Mem0 administration command, not a general reference to sleep. The
name follows [Mem0 Platform Dream](https://docs.mem0.ai/platform/features/dream),
which consolidates accumulated memory over time.

The local implementation deliberately has a narrower safety boundary than the
upstream workflow. It can plan deletion of exact duplicates and expired temporary
`session_state` or `compact_summary` records. It does not automatically resolve
contradictions, merge fuzzy matches, or delete pinned or merely low-confidence
memories.

## Modes

```bash
mem0-admin dream --dry-run --app-id PROJECT
mem0-admin dream --candidates --app-id PROJECT
mem0-admin dream --apply PLAN.json --yes
mem0-admin dream --auto --app-id PROJECT
```

- `--dry-run` scans the complete scope and writes a plan without changing memory.
- `--candidates` prints a read-only JSON report to stdout. It writes no plan,
  performs no backup, calls no LLM, and never applies an action. It includes
  source memory IDs and short previews for exact-duplicate groups and related
  pairs. Use `--max-candidates` to bound reported details; total candidate
  counts still describe the scanned scope. A large exact group shows at most
  20 source IDs/previews and reports the omitted source count. The scan still
  computes all candidate counts and may take quadratic CPU time on dense scopes.
- `--apply` revalidates the exact plan, creates and verifies a backup, and applies
  at most ten eligible actions.
- `--auto` combines deterministic plan generation with an interactive approval
  prompt. It prints the exact plan and deliberately rejects `--yes`, so it cannot
  serve as a non-interactive authorization path.

## Approval boundary

Every mutating Dream run requires explicit human approval of the exact scope and
plan. Dream is never scheduled. `mem0-backup restore` provides an operator-driven
rollback path, but the project does not ship a recovery drill or a separately
reviewed policy for unattended cleanup. The restore command therefore does not
change Dream's approval boundary.

The command stops on incomplete pagination, backup failure, revision changes,
scope changes, partial results, or missing confirmation. Use `review` for broader
diagnosis; contradictions and near-duplicates remain human decisions.

## Candidate evaluation boundary

The candidate report groups records by user, app, agent, and run before
comparison. `related_pair_review` means lexical overlap only: a pair might be
a duplicate, contradiction, merely related, or unrelated. The report does not
classify contradictions or suggest a replacement memory. Its previews can be
insufficient to judge a pair; use the source IDs for a private, authorized
review. Detection is whitespace-token based; Korean sentences with spaces can
be found, but unsegmented Chinese or Japanese sentences may be missed. Do not
commit the JSON or memory text to this public repository.

For a consented, scoped evaluation, label each reported pair as duplicate,
contradiction, related, or unrelated. Record the number reviewed, confirmed
duplicates and contradictions, and false positives. Divide confirmed
duplicates or contradictions by reviewed candidates for sample precision;
report confirmed candidates per scanned memory separately as *observed yield*,
not the true frequency of all contradictions. Inspect a sample of unflagged
memories for misses before making recall claims. If `omitted` is nonzero,
increase `--max-candidates` or label a stated sample. No private-memory
evaluation was performed as part of this implementation.

This is not Platform Dream parity. Platform Supersede and Merge keep linked
records and run with new additions; Synthesis is opt-in and scheduled.
The local candidate report does none of those actions and is not an apply
input. The existing local delete-only Dream plan remains separately guarded.
