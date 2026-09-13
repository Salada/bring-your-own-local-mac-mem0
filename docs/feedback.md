# Local memory feedback

The loopback REST server accepts a scoped label for one existing memory:

```http
POST /v1/feedback
Content-Type: application/json

{"memory_id":"example-uuid","feedback":"NEGATIVE","feedback_reason":"Outdated for this query"}
```

`feedback` is `POSITIVE`, `NEGATIVE`, or `VERY_NEGATIVE`. An explicit `null`
clears the existing label; omitting the field is an error. `feedback_reason`
is optional (up to 2,000 characters) and must be null when clearing. The
memory ID must be a UUID; malformed IDs return 400. A non-null response
includes the feedback ID, memory ID, user ID, label, reason, and timestamps.
A clear returns the previous feedback ID (if any) and null label/reason.
`GET /v1/feedback/{memory_id}` reads the current label or returns 404. Both
operations default to the configured local user; pass `user_id`
explicitly for another local user. A request for a missing or different-user
memory returns 404. No memory text is stored in the label table.

Labels live in the `local_feedback` table of the configured Mem0
`history_db_path`. The existing full-file SQLite backup and restore therefore
include them without a separate sidecar or format. Ensure the backup command's
`MEM0_HISTORY_DB` resolves to that same history file. A restore of an older
generation also restores its older feedback state. The table is created only
on the first non-null label write, not on reads.

Successful memory deletion clears its feedback through guarded REST, enabled
compatibility REST, and MCP. Cleanup runs before Mem0's deletion because Mem0
also writes to this SQLite file; the shared lock keeps backups from observing
the intermediate state. If Mem0 deletion then fails, the memory may remain
without its former feedback. Restore a verified pre-delete generation only if
that label must be recovered; do not assume cross-store atomicity.

This is **collection and retrieval**, not Platform feedback-learning parity.
Submitting a label does not change extraction, embeddings, search ranking, or
OpenMemory UI. A future offline retrieval evaluation would also need to capture
query context separately; this project does not yet ship that consumer or
automatically train from labels. The API does not label
a duplicate/contradiction *pair* for Dream M01a. Its reasons may themselves be
sensitive and must not be pasted into public issues, PRs, or CI logs.

The service defaults to loopback and has no production authentication. Do not
expose this endpoint to a LAN or team without the authentication and tenant
isolation work tracked as M09 in the [capability plan](platform-gap-plan.md).
