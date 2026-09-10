---
name: forget
description: Safely forget one exact local Mem0 record after the user asks to remove a remembered fact and approves the reviewed target.
---

# Forget

Use the repository's guarded `mem0-admin` workflow; never call an unguarded delete endpoint.

1. Run `mem0-admin forget "<query>" --app-id "<current-project>"`.
2. Show the matching IDs and text, and ask the user to approve one exact memory ID.
3. Only after that approval, run `mem0-admin forget --id "<id>" --app-id "<current-project>" --yes`.

The command rechecks scope and revision, captures a verified backup, and refuses pinned or concurrently changed records. Never perform bulk deletion from this skill.
