# Category management contract

Categories have two configuration scopes and one stored result:

- The project catalog is the default taxonomy when a write has no request override.
  It is a control-plane setting and is replaced as one complete list.
- A request catalog is a writer-supplied `custom_categories` override for one add
  operation. It does not change the project catalog.
- Assigned categories are LLM-inferred metadata. Callers that need a fixed label
  should use ordinary metadata instead of treating category inference as a manual
  tagging API.

This matches Mem0 Platform's documented precedence: request catalog, then project
catalog, then the built-in defaults. Catalog changes affect later ingestion and do
not retag existing memories. See Mem0's
[custom-categories reference](https://docs.mem0.ai/platform/features/custom-categories).

## Roles

| Role | Allowed category operations |
| --- | --- |
| Administrator | View and replace the project catalog; preview recommendations; explicitly request a separate backfill |
| Writer | View the active catalog and override it for only that writer's add request |
| Viewer | View and filter by categories |

Project catalog mutation remains an administrator operation because it changes the
project-wide default for future writes through `project.update`. Per-request
overrides remain a normal data-plane capability.

The current loopback runtime does not enforce these roles: `/auth/me` always
identifies the local caller as an administrator. Until real authorization exists,
the project catalog stays operator-managed in `config.json`; OpenMemory may display
and filter categories but must not expose catalog mutation.

## Recommendation behavior

A future admin recommendation command should be preview-only. It should:

1. Build a candidate catalog from operator-provided domain or use-case text.
2. Optionally use aggregate category statistics that do not contain memory text.
3. Show the complete replacement diff and disclose that the configured LLM is
   called and may incur cost.
4. Require a distinct, explicit apply action to persist the catalog.

Raw memory samples must not be used unless the operator explicitly opts in after
the disclosure. Recommendations must never apply automatically.

Applying a catalog should validate the complete list, replace it atomically, and
follow the deployment's configuration source of truth. On a Chezmoi-managed host,
that means changing the source template and applying it rather than writing the
rendered runtime file directly.

## Backfill boundary

Catalog replacement and historical backfill are separate operations. Replacing a
catalog never starts backfill automatically. Existing records remain unchanged
until an administrator previews and explicitly applies `mem0-admin categorize`.
`--overwrite` remains a separate opt-in for records that already have categories.

## Staged delivery

1. Keep this authorization and behavior contract as the implementation boundary.
2. Add read-only admin catalog inspection and recommendation preview.
3. Add explicit, validated catalog apply after a persistent authorization boundary
   and configuration ownership model exist.
4. Consider an OpenMemory admin UI only after the same authorization is enforced
   server-side.

Per-user persistent catalogs, automatic taxonomy mutation, catalog-change
backfill, and a manual force-category API are out of scope.
