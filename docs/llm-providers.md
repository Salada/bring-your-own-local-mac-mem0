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
| [DeepSeek](https://api-docs.deepseek.com/quick_start/pricing/) | **Experimental / not tested** | `DEEPSEEK_API_KEY` or an OpenAI-compatible profile | Lowest paid price in the author's comparison, but intentionally not the default for US-facing use |
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

In the author's deployed Korean/English workload, the Flash-class Gemini path
normalized conversations into concise English memory facts while preserving
proper nouns. The local multilingual embedder then handled the cross-lingual
semantic part of Korean-to-English retrieval. Mem0's separate spaCy entity and
lexical preprocessing remains in the pipeline and has a narrower English-language
boundary described in the [design rationale](design-rationale.md#retrieval-layers-and-language-boundary).
This is a reported deployment observation, not a provider benchmark. This project
describes the behavior as normalization rather than translation.

As of 2026-09-09, Google documents Gemini 3.5 Flash-Lite as a cost-efficient
high-volume model for simple data processing, with structured output and function
calling. Standard input and output are listed as free on the Developer API Free
Tier. The author's five-to-six-agent monthly workload fit within the available
limits, but Google applies limits per project, says capacity can vary, and directs
users to AI Studio for their active quota. Recheck the
[pricing](https://ai.google.dev/gemini-api/docs/pricing) and
[rate-limit page](https://ai.google.dev/gemini-api/docs/rate-limits) rather than
treating that observation as a guarantee.

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

Use `reasoning_effort: "none"` for routine extraction and try `"low"` only when
an evaluation shows extraction errors. Higher reasoning tiers add latency and
output cost to a task that is intentionally narrow.

## DeepSeek V4 Flash — cheapest evaluated paid alternative

The author's price comparison found `DeepSeek-V4-Flash-0731`, accessed directly
through the DeepSeek platform, to be the least expensive capable paid option.
DeepSeek's official model table lists JSON output and tool calls. Its thinking
mode defaults on, so low effort is the practical minimum with Mem0's current
OpenAI-compatible adapter; fully disabling thinking requires DeepSeek's separate
`thinking` request field, which this repository does not yet expose.

This project does not make DeepSeek the default because US organizations may have
procurement, data-governance, regulatory, or geopolitical constraints around a
PRC-hosted service. That is a deployment-policy concern, not legal advice. Users
outside that constraint can evaluate it independently using the official
[pricing/model table](https://api-docs.deepseek.com/quick_start/pricing/) and
[thinking-mode documentation](https://api-docs.deepseek.com/guides/thinking_mode/).

Configuration shape for a direct DeepSeek request through Mem0's OpenAI-compatible
adapter:

```json
{
  "llm": {
    "provider": "openai",
    "config": {
      "model": "deepseek-v4-flash",
      "openai_base_url": "https://api.deepseek.com",
      "reasoning_effort": "low",
      "is_reasoning_model": true
    }
  }
}
```

Expose the DeepSeek key as `OPENAI_API_KEY` for this profile. `low` is used rather
than `none` because the pinned Mem0 adapter can forward `reasoning_effort`, but not
DeepSeek's separate `thinking: {"type": "disabled"}` request extension. This
profile is source-verified only and has not made a paid end-to-end request.

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
