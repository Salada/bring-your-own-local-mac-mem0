---
name: remember
description: Capture a durable fact, preference, decision, convention, or reusable outcome in the local Mem0 store when the user explicitly asks Codex to remember it.
---

# Remember

Confirm the exact durable fact in one concise sentence. Do not include secrets, credentials, transient logs, raw tool output, or guesses.

The lifecycle hooks detect the explicit remember request and batch the user request with the completed response. Do not call a separate write API or duplicate the fact. Tell the user that capture is local and will finish in the background.
