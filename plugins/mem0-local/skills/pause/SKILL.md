---
name: pause
description: Pause automatic local Mem0 recall and lifecycle capture when the user asks Codex to stop using memory temporarily.
---

# Pause

Run:

```bash
python3 "${PLUGIN_ROOT}/core/memory_cli.py" pause --plugin-data-dir "${PLUGIN_DATA}"
```

Report that automatic recall and capture are paused. Existing memories and queued evidence are not deleted.
