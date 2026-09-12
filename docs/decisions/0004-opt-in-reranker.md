# ADR 0004: Opt-in local search reranking

- Status: Accepted
- Date: 2026-09-12

## Context

Mem0 OSS 2.0.20 already accepts a `reranker` provider in `MemoryConfig` and a
per-search `rerank` flag, defaulting to false. Its Hugging Face provider can run
a local cross-encoder, but loads the model at `Memory` construction. The runtime
exposed the flag in MCP, not REST, and shipped neither the optional dependencies
nor configuration guidance. Mem0 reranks only the vector candidates returned
by `top_k`, so the candidate set can be too narrow for a useful second stage.

[Honcho's message search](https://github.com/plastic-labs/honcho/blob/8e386180bd87b852e7934cfef53cba3d6bee1bb4/src/utils/search.py)
uses semantic and PostgreSQL full-text candidate lists, overfetches each, and
combines them with reciprocal rank fusion. That is hybrid retrieval rather than
a neural cross-encoder. This deployment has a dense Qdrant collection but no
equivalent full-text index, so copying its fusion algorithm would add another
retrieval subsystem rather than implement Mem0's documented reranker.

## Decision

Use Mem0's unmodified `huggingface` reranker provider and documented two-stage
configuration: an optional top-level `reranker` block in private `config.json`
and `rerank=true` on each opted-in search. Keep both REST and MCP defaults false,
and leave the committed example configurations without a provider. Install the
provider's `torch` and `transformers` dependencies only with the `rerank` extra.
Recommend multilingual `BAAI/bge-reranker-v2-m3` on `mps` only when PyTorch
reports MPS available; otherwise use CPU. Do not download weights or activate
it during deployment.

The locked Torch wheel currently makes this extra macOS 14+ only on Apple
Silicon; the base runtime is not subject to that extra's minimum OS version.

For non-temporal opted-in searches with a configured reranker, retrieve at most
twice the requested `top_k` (expansion capped at 60 candidates), ask upstream Mem0 to
rerank that set, then return the requested count. For temporal searches, retain
the existing three-times candidate pool and semantic threshold. Rank eligible
results by Mem0's `rerank_score` plus the bounded temporal boost, while keeping
the existing locally boosted vector-derived `score` and temporal explanation
semantics. When the provider is configured with `normalize=false`, sigmoid is
applied uniformly to its raw logits for temporal combination, preserving
their order. When the official Hugging Face provider returns zero scores for
all candidates after a scoring failure, temporal ranking falls back to the
vector-plus-date order.

If no provider is configured, the opt-in flag is an upstream no-op. Upstream
reranker failures fall back to vector results.

## Consequences and limits

The model adds a startup memory and latency cost when configured, and search
latency when explicitly enabled. MPS/model compatibility and retrieval quality
must be measured on the target Mac before recommending it as a default. This
change does not alter stored memories, vectors, categories, or write-time
enrichment; no backfill or re-embedding is needed. Candidate overfetch is a
small local adapter improvement, not exact Mem0 Cloud ranking parity. The
existing temporal rank boost remains a local approximation. Mem0 catches
reranking errors during search, but not model initialization errors at startup;
operators must validate the chosen model and device before enabling them in
the live config. A future hybrid
full-text/RRF design should be evaluated separately if a real lexical-recall
gap is demonstrated.
