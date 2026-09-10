---
name: status
description: Show the resolved local Mem0 recall and capture profile, pause state, and redacted queue counters when the user asks about memory status or aggressiveness.
---

# Status

Run:

```bash
python3 "${PLUGIN_ROOT}/core/memory_cli.py" status --plugin-data-dir "${PLUGIN_DATA}"
```

Explain the resolved recall/capture levels and counters. Never inspect or print stored event content, prompts, retrieved memories, database files, or secrets.
