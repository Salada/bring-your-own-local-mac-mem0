# LLM provider configuration

The `llm` block controls fact extraction and memory update decisions. It is
independent of the local embedding model configured under `embedder`.

The examples below target the pinned `mem0ai==2.0.19`. Provider support alone does
not mean that this repository has tested the provider end to end.

| Provider | Status in this project | Credential or dependency | Notes |
| --- | --- | --- | --- |
| [Google Gemini](https://docs.mem0.ai/components/llms/models/google-ai) | **Verified** on the source Apple Silicon stack with Mem0 2.0.19 | `GOOGLE_API_KEY` | Default and currently maintained path |
| Gemini on Vertex AI with custom HTTP options | **Configuration plumbing tested; custom gateway not tested end to end** | Application Default Credentials or gateway-specific auth | This runtime extends the pinned Mem0 adapter with `base_url` and `http_headers` |
| [OpenAI](https://docs.mem0.ai/components/llms/models/openai) | **Configuration source-verified; not tested end to end** | `OPENAI_API_KEY` | `gpt-5.6-luna` is the current project recommendation; Mem0 2.0.19 itself defaults to `gpt-5-mini` |
| [Ollama](https://docs.mem0.ai/components/llms/models/ollama) | **Experimental / not tested** | Ollama server and Python `ollama` package | Optional client is not installed by the default dependency set |
| OpenAI-compatible local server | **Experimental / not tested** | Server-specific base URL and dummy/local key if required | Uses Mem0's `openai` provider; compatibility depends on tool calling and JSON output |

Mem0 exposes additional providers. They are intentionally not copied into this
guide until this stack has at least validated their configuration shape. Use the
[official LLM overview](https://docs.mem0.ai/components/llms/overview) as the
authoritative catalog.

## Why Gemini is the default

Mem0 uses this LLM for bounded fact extraction, deduplication, and memory-update
decisions—not as the interactive coding model. That workload favors reliable
structured output, multilingual normalization, low latency, and low per-call cost
over maximum agentic reasoning.

The private operational LLM Wiki records that the deployed Flash-class Gemini
path successfully canonicalized Korean and English conversations into concise
English memory facts while preserving proper nouns. The local multilingual
embedder then handled Korean-to-English retrieval. This is deployment evidence,
not a provider benchmark, but it supports keeping Gemini as the tested default.

Embeddings and the resulting memory store remain local, but the conversation
content needed for fact extraction is sent to the configured cloud LLM. Choose a
fully local provider instead if that boundary is unacceptable.

## Gemini Developer API — verified default

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

`google-genai` is a direct runtime dependency because Mem0's Gemini provider
imports it. It is not an unused convenience dependency.

## Gemini on Vertex AI with a custom endpoint — plumbing tested

The pinned Mem0 2.0.19 adapter supports `vertexai`, `project`, and `location`, but
does not forward the Google Gen AI SDK's HTTP options. This repository registers
a narrow compatibility adapter under the same `gemini` provider name. `base_url`
is the Gemini equivalent of `openai_base_url`; `http_headers` accepts arbitrary
string header names and values.

```json
{
  "llm": {
    "provider": "gemini",
    "config": {
      "model": "gemini-3.5-flash-lite",
      "temperature": 0.1,
      "vertexai": true,
      "project": "your-gcp-project",
      "location": "us-central1",
      "base_url": "https://your-vertex-gateway.example.com",
      "http_headers": {
        "X-Tenant": "your-team",
        "X-Custom-Routing": "memory-extraction"
      }
    }
  }
}
```

Use Application Default Credentials for a normal Vertex AI endpoint. If a custom
gateway requires an authorization header, put it only in the untracked,
mode-`0600` local `config.json`; never commit it. The loopback `/configure`
compatibility route masks all `http_headers` values.

Unit tests verify that the adapter constructs `google.genai.Client(vertexai=True,
http_options=HttpOptions(...))` with the configured base URL and headers. No live
request to an arbitrary Vertex gateway has been exercised, so gateway-specific
URL rewriting and authentication remain the operator's responsibility. The
underlying fields are documented by the
[Google Gen AI Python SDK](https://googleapis.github.io/python-genai/).

## OpenAI — recommended model, not tested end to end

For this workload, use `gpt-5.6-luna` first. OpenAI describes Luna as the
cost-sensitive, high-volume GPT-5.6 tier, and its API supports Chat Completions,
function calling, and structured outputs—the three properties relevant to Mem0's
current OpenAI adapter. A larger Terra or Sol model is hard to justify for routine
fact extraction unless an evaluation shows materially better memory precision.

Set `is_reasoning_model` so pinned Mem0 forwards `reasoning_effort` and omits
sampling fields that are not needed here:

```json
{
  "llm": {
    "provider": "openai",
    "config": {
      "model": "gpt-5.6-luna",
      "reasoning_effort": "none",
      "is_reasoning_model": true
    }
  }
}
```

```dotenv
OPENAI_API_KEY=replace-locally
```

This shape matches the pinned Mem0 source, but no paid OpenAI request has been
exercised as part of this repository validation. Mem0 2.0.19 falls back to
`gpt-5-mini` when `model` is omitted; that remains a compatibility fallback, not
this project's current recommendation. See the official
[GPT-5.6 Luna model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

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
