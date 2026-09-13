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

## Exploratory evaluation (2026-09-13)

This is a **candidate-generation** check, not a contradiction classifier or
permission to apply changes. A consented **private evaluation** scanned one
user scope without modifying memories. A model reviewer inspected 20 reported
pairs sampled with `random.Random(20260913).sample` and 20 unreported pairs
sampled the same way from the same-scope, same-type lexical-overlap slice
`[0.4, 0.6)`. Many reported pairs described different issues or successive
stages of one task. There was no independent adjudication or reliable label for
every ambiguous pair, so this does **not** establish precision or recall. The
unreported slice is deliberately near-threshold, not representative of every
unreported pair. Dataset ordering and private snapshots were not retained, so
the private sample is not externally reproducible. No private scope counts,
memory text, IDs, or individual labels are published here.

Two public out-of-domain checks used the Hugging Face dataset-server `rows` API,
100 rows at each listed offset, treating each labelled pair as an isolated
two-memory scope of the same type and running the unchanged `candidate_report`.
Run [`runtime/tests/eval_m01a_public.py`](../runtime/tests/eval_m01a_public.py)
to reproduce the counts while the dataset server still serves the stated
revisions. It checks response revision, full rows, and expected counts, then
prints counts only. It does not upload or write any memory or dataset text:

| Dataset and revision | Offsets | Flagged labelled pairs | Flagged other pairs |
| --- | --- | --- | --- |
| [Quora duplicate questions](https://huggingface.co/datasets/sentence-transformers/quora-duplicates) `pair-class`, `41f699770310302022a4dd75d4cf903bfef9ea46` | 0, 10000 | 57/71 duplicates | 57/129 different |
| [KLUE-NLI](https://huggingface.co/datasets/klue/klue) validation, `349481ec73fff722f88e0453ca05c77a447d967c` | 0, 1000 | 23/67 contradictions; 28/66 entailments | 14/67 neutral |

These fixed offsets were chosen for a quick diagnostic, not a random benchmark.
Question paraphrases and general NLI sentences are not stored, time-scoped
memories; entailment is not necessarily a duplicate, and neutral is not
necessarily unrelated. The counts show lexical leads can miss semantically
important pairs and also flag non-duplicates. They are **not** local-memory
accuracy estimates. Before M01b, independently label a scoped sample of actual
candidate and non-candidate memory pairs, record ambiguous cases, and measure
whether stale facts harm retrieval. Do not export private examples to a public
issue, PR, CI log, or external benchmark service.

## Private adjudication sample

Run `mem0-admin dream --eval-sample --private-output --sample-size 20 --seed
20260913` only in a private local terminal. The explicit flag is required
because the JSON printed to stdout includes **full memory text and IDs**. The
command reads one user scope and writes no file, label, backup, or memory. Do
not paste or redirect its output to a public repository, CI log, cloud service,
or shared agent session. If a local copy is necessary for human labeling,
protect it as private state outside the repository and delete it when no
longer needed.

The sample is uniform within four same-user/app/agent/run/type pair strata:
normalized exact pairs, related candidates (lexical overlap at least 0.6),
near misses (0.4–0.6), and all remaining background pairs. It records the
population size of each stratum, the random seed, source revisions, and a
scan fingerprint covering text, revision, scope, and type. Pair enumeration
uses quadratic CPU time but bounded sample storage. Two independent reviewers
should mark each pair
`duplicate`, `contradiction`, `related`, `unrelated`, or `uncertain` before
resolving disagreements. A contradiction requires incompatible claims about
the same subject and time; a changed preference or sequential task stage is
not automatically one. Do not silently discard uncertain pairs.

Report **pair-level** precision separately for exact and related candidates,
with each sample denominator and uncertainty. `candidate_report` counts exact
duplicate **groups**, whereas this sample counts exact **pairs**; do not call
the pooled raw sample fraction its row-level precision. Any combined pair-level
estimate must weight the strata by their pair-population sizes and state that
estimand. Report confirmed misses separately by sampled noncandidate stratum. A small
background sample cannot support a reliable global recall estimate when
positive pairs are rare. Retrieval harm needs a separate query-level review;
pair labels alone cannot establish it. The live store may change during a
paginated scan, so the printed sample is a scan-derived review packet, not an
atomic or externally reproducible memory snapshot.
