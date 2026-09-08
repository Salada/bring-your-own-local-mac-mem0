# Configuration

The project ships usable local defaults but keeps machine identity, credentials,
model choice, and storage paths configurable.

## Precedence and ownership

| Surface | Use it for | Examples |
| --- | --- | --- |
| Request argument | Per-operation scope | `user_id`, `app_id`, `agent_id`, `run_id` |
| Process environment or local `.env` | Secrets and machine defaults | `GOOGLE_API_KEY`, `MEM0_DEFAULT_USER_ID`, ports |
| Local `config.json` | Mem0 component selection | LLM, embedder, Qdrant, history path |
| Repository fallback | Safe first-run behavior | loopback addresses, `local-user` |

An explicit request scope wins for that operation. Environment values customize
the server default. Repository fallbacks apply only when neither was supplied.

## Runtime environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEM0_DEFAULT_USER_ID` | `local-user` | Logical memory namespace when a request omits one |
| `MEM0_CORS_ORIGINS` | local dashboard origins on port `11889` | Comma-separated browser origins allowed to call the API |
| `MEM0_SERVER_URL` | `http://127.0.0.1:11888` | URL used by local administration and hooks |
| `MEM0_SERVER_PORT` | `11888` | REST and MCP port |
| `MEM0_DASHBOARD_PORT` | `11889` | OpenMemory UI port |
| `MEM0_DATA_DIR` | `$HOME/.local/share/mem0` | Qdrant and history storage root |
| `MEM0_BACKUP_REMOTE` | unset | Optional rclone destination; backup publishing stays disabled when unset |
| `MEM0_BACKUP_STAGING_DIR` | `$HOME/.local/state/mem0-backup/staging` | Verified local backup staging |

The runtime reads only simple `KEY=VALUE` records from `.env`; it never executes
the file as shell code. Values already exported by the parent process take
precedence over `.env`.

## `config.json`

`config.example.json` is the default Qwen3/Gemini profile.
`config.bge-m3.example.json` changes both the embedding model and Qdrant dimension.
Copy one to `config.json`, make the history path absolute, and keep the rendered
file outside version control.

Changing an embedding model is not a live configuration toggle. A collection
created at 2560 dimensions cannot accept 1024-dimensional BGE-M3 vectors. Use a
new collection and re-embed memories when changing profiles.
