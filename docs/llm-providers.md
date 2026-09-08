# LLM provider configuration

The `llm` block controls fact extraction and memory update decisions. It is
independent of the local embedding model configured under `embedder`.

The examples below target the pinned `mem0ai==2.0.19`. Provider support alone does
not mean that this repository has tested the provider end to end.

| Provider | Status in this project | Credential or dependency | Notes |
| --- | --- | --- | --- |
| [Google Gemini](https://docs.mem0.ai/components/llms/models/google-ai) | **Verified** on the source Apple Silicon stack with Mem0 2.0.19 | `GOOGLE_API_KEY` | Default and currently maintained path |
| [OpenAI](https://docs.mem0.ai/components/llms/models/openai) | **Not tested** end to end | `OPENAI_API_KEY` | Config shape verified against installed Mem0 2.0.19 source |
| [Ollama](https://docs.mem0.ai/components/llms/models/ollama) | **Experimental / not tested** | Ollama server and Python `ollama` package | Optional client is not installed by the default dependency set |
| OpenAI-compatible local server | **Experimental / not tested** | Server-specific base URL and dummy/local key if required | Uses Mem0's `openai` provider; compatibility depends on tool calling and JSON output |

Mem0 exposes additional providers. They are intentionally not copied into this
guide until this stack has at least validated their configuration shape. Use the
[official LLM overview](https://docs.mem0.ai/components/llms/overview) as the
authoritative catalog.

## Gemini — verified default

`config.json`:

```json
{
  "llm": {
    "provider": "gemini",
    "config": {
      "model": "gemini-3.5-flash-lite",
      "temperature": 0.1,
      "max_tokens": 2000
    }
  }
}
```

Local `.env`:

```dotenv
GOOGLE_API_KEY=replace-locally
```

Do not add `api_key` to the committed JSON example. Mem0 2.0.19 uses
`llm.config.api_key` before `GOOGLE_API_KEY`, so a stale explicit value can mask a
correct environment value.

## OpenAI — not tested

```json
{
  "llm": {
    "provider": "openai",
    "config": {
      "model": "gpt-5-mini",
      "temperature": 0.1,
      "max_tokens": 2000
    }
  }
}
```

```dotenv
OPENAI_API_KEY=replace-locally
```

This matches the provider fields accepted by the pinned Mem0 source, but no paid
OpenAI request has been exercised as part of this repository validation.

## Ollama — experimental / not tested

```json
{
  "llm": {
    "provider": "ollama",
    "config": {
      "model": "llama3.1:8b",
      "ollama_base_url": "http://127.0.0.1:11434",
      "temperature": 0.1,
      "max_tokens": 2000
    }
  }
}
```

Install and test the Ollama Python client separately before selecting this profile.
This repository does not add that dependency to the default installation.

## OpenAI-compatible local server — experimental / not tested

```json
{
  "llm": {
    "provider": "openai",
    "config": {
      "model": "local-model-name",
      "openai_base_url": "http://127.0.0.1:1234/v1",
      "api_key": "local-only-placeholder",
      "temperature": 0.1,
      "max_tokens": 2000
    }
  }
}
```

This path requires an OpenAI-compatible chat-completions endpoint that correctly
supports Mem0's structured JSON and tool-call requests. Treat it as experimental
until an end-to-end add/search/update test passes for the selected server and model.
