---
name: resume
description: Resume automatic local Mem0 recall and lifecycle capture after the user previously paused this plugin.
---

# Resume

Run:

```bash
python3 "${PLUGIN_ROOT}/core/memory_cli.py" resume --plugin-data-dir "${PLUGIN_DATA}"
```

Report that future eligible lifecycle events will use local memory again. Do not claim that events skipped while paused were recovered.
