# Temporal reasoning feasibility

## Verdict

A bounded local implementation is feasible, but Mem0 Platform parity is not a
configuration change. Mem0 documents Temporal Reasoning as an automatic Platform
v3 ranking feature and explicitly says it is unavailable in the OSS SDK. The
pinned `mem0ai==2.0.19` accepts `timestamp` and `reference_date` in its Python
signatures only to reject them as Platform-only parameters.

The local FastAPI request models do not currently declare either field. Pydantic's
default behavior therefore ignores these extra JSON keys rather than forwarding
them, while the MCP tool signatures omit them entirely. Tests for a future adapter
must prove the fields are honored so callers cannot mistake a successful baseline
request for temporal processing.

The recommended first implementation is therefore an opt-in local temporal boost,
not a claim that OSS Temporal Reasoning has been enabled.

## What the current stack can support

| Capability | Current state | Local feasibility |
| --- | --- | --- |
| Store event dates | Qdrant already stores arbitrary payload metadata | Feasible without re-embedding or a collection migration |
| Filter ISO date ranges | The pinned Qdrant adapter builds `DatetimeRange` filters | Feasible |
| Preserve import time | `metadata.created_at` can be stored, but top-level `timestamp` is rejected | Feasible at the wrapper boundary, with an extraction caveat below |
| Resolve `reference_date` | OSS rejects the parameter and performs semantic search only | Requires local query parsing and reranking |
| Automatic event-date extraction | No structured event interval is produced | Requires enrichment |
| Exact Platform ranking behavior | The extraction schema and boost formula are not public | Not verifiable |

The OSS extraction prompt already asks the LLM to turn relative phrases into
absolute dates. However, the pinned call site does not pass its supported prompt
`timestamp` argument, so imported conversations can be anchored to processing
time even when date-like metadata is present. A local implementation must test and
solve that observation-time boundary; merely copying `timestamp` into metadata is
not sufficient.

Sources:

- [Mem0 Temporal Reasoning](https://docs.mem0.ai/platform/features/temporal-reasoning)
- [Mem0 OSS `Memory` implementation](https://github.com/mem0ai/mem0/blob/v2.0.19/mem0/memory/main.py)
- [Mem0 OSS extraction prompts](https://github.com/mem0ai/mem0/blob/v2.0.19/mem0/configs/prompts.py)
- [Mem0 OSS Qdrant adapter](https://github.com/mem0ai/mem0/blob/v2.0.19/mem0/vector_stores/qdrant.py)

## Smallest useful architecture

1. Accept a timezone-aware `timestamp` on add and `reference_date` on search in
   the local REST and MCP adapters. Do not pass either unsupported parameter into
   `Memory`.
2. Store validated `event_start`, `event_end`, and `temporal_kind` payload fields.
   Extend the existing single background enrichment job so category and temporal
   extraction share one LLM call instead of adding another call to every write.
3. Leave non-temporal searches unchanged. When a cheap cue detector finds a
   temporal query, use the configured LLM once to turn the query and
   `reference_date` into a structured interval and intent. This gives the existing
   Korean/English workload better coverage without a second date-parser package.
4. Over-fetch semantically relevant candidates, then boost interval and intent
   matches locally. Keep the semantic threshold as a gate so an unrelated memory
   cannot rank only because its date matches.
5. Return the normal search response shape. With `explain` enabled, include the
   base score, temporal match, boost, and final score for calibration.

This path uses the existing LLM, worker, Qdrant payload updates, and OSS search
results. It needs no custom image, patched site-package, graph database, or vector
schema migration.

## Delivery gates

Implement the feature in separately reviewed units:

1. Add deterministic interval and boost logic with fixed `reference_date` tests,
   using manually supplied event metadata only.
2. Add opt-in REST and MCP request fields while preserving the exact baseline path
   for non-temporal calls.
3. Add new-memory temporal enrichment to the existing background worker and verify
   that provider failure leaves the stored memory and baseline search usable.
4. Decide whether historical imports with relative language need an upstream Mem0
   fix or a clearly documented local prompt override.

The minimum acceptance fixtures should reproduce the Platform example in which
`last week` ranks the matching conference memory first, plus timezone-boundary,
future-plan, missing-metadata, irrelevant-same-date, provider-failure, and
non-temporal-order regression cases.

Do not enable the feature by default until those fixtures establish a useful boost
range. Do not backfill the current store as part of implementation. Backfill, if
ever requested, remains a separate bounded admin workflow with preview and backup.

## Known limits

- Search-time LLM parsing adds latency, may incur provider cost, and sends the
  temporal query to the configured model. An opt-in flag and disclosure are
  required because ordinary local search does not currently do this.
- Background enrichment is eventually consistent, so a new memory may briefly
  have no temporal fields.
- `currently`, `as of`, and duration questions require validity intervals rather
  than a single event date. Start with dated occurrences and future plans; add
  ongoing-state semantics only after dedicated evaluation.
- Exact SaaS scoring equivalence cannot be asserted without a public Platform
  extraction schema and ranking formula.
