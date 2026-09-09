# Restore a backup generation

`mem0-backup restore` is a destructive operator command that replaces the live
Qdrant collection and SQLite history database with one exact verified backup
generation. It is not scheduled and does not select a generation automatically.

## Preconditions

- Start from a healthy local installation. The command requires the current
  Qdrant collection and history database so it can capture the exact pre-restore
  state as a rollback generation.
- Run the installed command from `MEM0_HOME` with its launchd API job configured.
  Running `runtime/bin/mem0-backup` directly from a repository checkout is
  rejected because its Compose project and service controller may differ.
- Keep the configured backup remote reachable when the target generation is not
  already in local staging.
- Use a Qdrant version supported by its snapshot compatibility policy. The
  restore target must use the same major and minor at an equal or newer patch, or
  the immediately following minor release. See Qdrant's
  [snapshot documentation](https://qdrant.tech/documentation/operations/snapshots/).
- Expect downtime. The command stops Mem0, OpenMemory, and Qdrant before changing
  data, then starts only Qdrant while the stores are restored.
- Stop any separately launched foreground Mem0 server. Restore refuses to proceed
  if the API still answers after `mem0-ctl stop`.

List the remote generations and inspect the exact name first:

```bash
mem0-backup status
```

## Restore

Pass the complete RFC 3339 generation name and explicit confirmation:

```bash
mem0-backup restore 'mem0-2026-09-07T03:00:00+00:00' --yes
```

The command performs these guarded steps:

1. Resolve only that generation, preferring a private rollback copy, then local
   staging, then the configured rclone remote.
2. Verify its manifest, SHA-256 hashes, SQLite integrity, collection name, and
   Qdrant snapshot version compatibility.
3. Stop the full stack, start Qdrant alone, and capture a fresh rollback
   generation under `MEM0_RESTORE_STATE_DIR/rollback`.
4. Write `MEM0_RESTORE_STATE_DIR/in-progress.json`, restore Qdrant through its
   snapshot upload API, atomically replace SQLite, and remove stale SQLite
   sidecars.
5. Compare the live collection's point count and vector shape (size and distance)
   plus the live SQLite table counts with the backup manifest.
6. Clear the marker and restart the full stack only after both stores pass.

The rollback generation is deliberately outside normal backup staging, so the
due-aware publisher cannot upload or rotate it accidentally.

## Failure and rollback

If failure occurs before either store is changed, the command attempts to restart
the unchanged stack. If failure occurs after the in-progress marker is written,
the marker remains and the API refuses to initialize. Do not delete the marker or
manually start the API.

Read the recorded rollback generation without editing the file:

```bash
marker="${MEM0_RESTORE_STATE_DIR:-$HOME/.local/state/mem0-backup/restore}/in-progress.json"
jq . "$marker"
rollback_generation="$(jq -r .rollback_generation "$marker")"
mem0-backup restore "$rollback_generation" --yes
```

While a marker exists, every other restore target is rejected. A successful
rollback verifies both stores, removes the marker, and restarts the stack.

This repository tests command ordering, marker retention, exact rollback gating,
version checks, and SQLite replacement without mutating a live user database. It
does not currently ship an isolated end-to-end recovery drill. Restore support
therefore does not make Dream eligible for unattended scheduling.
