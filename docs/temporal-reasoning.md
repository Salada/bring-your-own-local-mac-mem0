# Local temporal reasoning

## Verdict

A bounded local implementation is available, but it is not exact Mem0 Platform
parity. Mem0 documents Temporal Reasoning as an automatic Platform v3 ranking
feature and explicitly says it is unavailable in the OSS SDK. The local REST and
MCP adapters now implement the public `timestamp` and `reference_date` concepts at
their own boundary without forwarding unsupported parameters into Mem0 OSS.

Ordinary searches remain on the pre-existing semantic path. A Korean or English
temporal cue automatically opts into temporal parsing and reranking. An optional
timezone-aware `reference_date` replaces the current time as the query anchor.

## What the current stack can support

| Capability | Current state | Local feasibility |
| --- | --- | --- |
| Store event dates | `event_start`, `event_end`, and `temporal_kind` payloads | Implemented without re-embedding or a collection migration |
| Filter ISO date ranges | The pinned Qdrant adapter builds `DatetimeRange` filters | Feasible |
| Preserve import time | Adapter stores validated `created_at` and uses it to anchor extraction | Implemented for new writes |
| Resolve `reference_date` | OSS rejects the parameter and performs semantic search only | Implemented in the local adapter |
| Automatic event-date extraction | Shared category/temporal background enrichment | Implemented for new writes |
| Exact Platform ranking behavior | The extraction schema and boost formula are not public | Not verifiable |

The OSS extraction prompt already asks the LLM to turn relative phrases into
absolute dates, but its call site does not consistently anchor imported text to a
caller-supplied observation time. The adapter therefore performs structured
temporal extraction in its existing post-write worker and adds a timestamp anchor
to the normal OSS fact-extraction instructions. Existing configured extraction
instructions are preserved. Category and temporal fields share one post-write LLM
call when both are requested.

Sources:

- [Mem0 Temporal Reasoning](https://docs.mem0.ai/platform/features/temporal-reasoning)
- [Mem0 OSS `Memory` implementation](https://github.com/mem0ai/mem0/blob/v2.0.19/mem0/memory/main.py)
- [Mem0 OSS extraction prompts](https://github.com/mem0ai/mem0/blob/v2.0.19/mem0/configs/prompts.py)
- [Mem0 OSS Qdrant adapter](https://github.com/mem0ai/mem0/blob/v2.0.19/mem0/vector_stores/qdrant.py)

The parser-library comparison and deferral are recorded in
[Decision 0001](decisions/0001-temporal-parser.md).

## Behavior

1. Add accepts a timezone-aware `timestamp`, stores it as `created_at`, and uses
   it only to resolve clearly dated occurrences and future plans.
2. The worker validates and stores `event_start`, `event_end`, and
   `temporal_kind`. An invalid or unavailable LLM response never rolls back the
   successful memory write.
3. A cheap cue detector avoids the LLM for non-temporal text. Temporal text is
   resolved once against the current time, or an optional timezone-aware
   `reference_date`, into an interval and `occurrence`, `plan`, or `any` intent.
4. The adapter over-fetches semantic candidates, discards candidates below the
   semantic threshold, and adds a bounded `0.15` boost only to interval-and-intent
   matches. It then returns the requested number of items.
5. `explain=true` adds `temporal_explanation` with the base score, match, boost,
   and final score. Parser failure fails open to the original semantic search.

This path uses the existing LLM, worker, Qdrant payload updates, and OSS search
results. It needs no custom image, patched site-package, graph database, or vector
schema migration.

## Example

```json
POST /v1/memories
{
  "messages": "I attended the local AI conference yesterday.",
  "timestamp": "2026-09-11T09:00:00+09:00"
}
```

```json
POST /v1/memories/search
{
  "query": "What did I attend last week?",
  "reference_date": "2026-09-14T09:00:00+09:00",
  "explain": true
}
```

The same optional fields are available on MCP `add_memory`/`add_memories` and
`search_memories`.

## Known limits

- Search-time LLM parsing adds latency, may incur provider cost, and sends the
  temporal query to the configured model. It runs only when a temporal cue is
  present.
- Background enrichment is eventually consistent, so a new memory may briefly
  have no temporal fields.
- `currently`, `as of`, and duration questions require validity intervals rather
  than a single event date. Start with dated occurrences and future plans; add
  ongoing-state semantics only after dedicated evaluation.
- Exact SaaS scoring equivalence cannot be asserted without a public Platform
  extraction schema and ranking formula.
- Existing memories are not automatically enriched. Historical backfill remains
  a separate admin workflow and is not part of this feature.
