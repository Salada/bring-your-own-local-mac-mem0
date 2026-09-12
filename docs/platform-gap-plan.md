# Mem0 Platform-to-local capability plan

This is the **single living plan** for deciding which documented Mem0 Platform capabilities this project should adopt, evaluate, or intentionally omit. It is not a promise of SaaS parity. Research is a dated observation; a change to this plan is a project decision reviewed with the code that it affects.

Initial evidence baseline: [Mem0 Platform documentation](https://docs.mem0.ai/platform/platform-vs-oss) checked on 2026-09-13, [Mem0 OSS v2.0.20](https://github.com/mem0ai/mem0/tree/v2.0.20), and this repository at [`1aea322`](https://github.com/Salada/bring-your-own-local-mac-mem0/tree/1aea3223922f8f3e038ece28813105c82a497da7). Recheck affected claims before acting; the table is not a statement about later upstream releases or an uninspected live deployment.

## Scope and decision rules

The repository defaults to a loopback API, local Qdrant and embeddings, and a configured cloud LLM for fact extraction. It does **not** provide production authentication or claim to be fully offline. Private configuration, actual exposure, user count, and real memory quality were not inspected for the initial baseline. The non-adoption decisions below assume a single-operator loopback use case; network or team exposure changes the security requirements.

- **Short term**: a small, testable improvement or read-only evaluation worth a scoped PR.
- **Long term**: a possible improvement that first needs a measured failure, design, or concrete user demand.
- **Intentionally not adopted**: a real Platform difference that is not a defect within the stated operating boundary. Every such choice has a reopening trigger.
- **Done**: implemented and verified; retain its ID and link the merged PR and tested release.

These are maintainer proposals, not authorization for memory mutation. In particular, [Dream](dream.md) mutation still requires explicit human approval, verified backup, and revision checks. No plan item schedules Dream or automatically backfills existing memories.

## Short term

| ID | Gap and proposed next step | Completion gate | Evidence |
| --- | --- | --- | --- |
| M02 | OSS already supports memory `expiration_date` and `show_expired`, but the inspected local REST/MCP surface does not expose them. Pass through validated arguments. | Round-trip tests for add/update/search/list; expired records remain recoverable; no automatic backfill. | [Platform expiration](https://docs.mem0.ai/platform/features/memory-expiration), [local server](../runtime/server.py) |
| M01a | Local `mem0-admin dream` plans exact duplicate and expired-summary cleanup, not fuzzy merge, contradiction resolution, or synthesis. Add **read-only** candidate reporting with source memory IDs first. | Evaluate candidate precision and actual duplicate/contradiction frequency before proposing any new apply path. | [Platform Dream](https://docs.mem0.ai/platform/features/dream), [local Dream](dream.md) |

## Long term

| ID | Gap and proposed next step | Promotion trigger | Evidence |
| --- | --- | --- | --- |
| M01b | Platform Dream automatically supersedes/merges and optionally synthesizes linked patterns; local Dream is not equivalent. Design a reversible, auditable state model only after M01a. | Measured harmful stale/contradictory retrieval plus a safe rollback design. | [Platform Dream](https://docs.mem0.ai/platform/features/dream), [local Dream](dream.md) |
| M03 | Platform opt-in memory decay has no local access-history/reinforcement equivalent; temporal ranking and reranking are different. | A retrieval evaluation shows a decay-specific failure and justifies extra writes/scoring. | [Platform decay](https://docs.mem0.ai/platform/features/memory-decay), [local temporal](temporal-reasoning.md) |
| M04 | Platform queryable graph is absent, although OSS/local already have entity extraction and shared-entity ranking. Do not add a graph database for parity alone. | A bilingual multi-hop corpus demonstrates a failure of the existing entity path. | [Platform graph](https://docs.mem0.ai/platform/features/graph-memory), [local design](design-rationale.md) |
| M05 | Project/agent/request custom-instruction control is not exposed locally, although static OSS configuration exists. Define administrator versus user authority and precedence first. | A concrete multi-agent instruction conflict or required per-agent extraction policy. | [Platform instructions](https://docs.mem0.ai/platform/features/custom-instructions), [local configuration](configuration.md) |
| M06 | Local memory has no Platform-style feedback loop. Start with labelled feedback for offline retrieval evaluation; do not assume SaaS feedback trains ranking. | A representative evaluation set and a consumer of feedback labels exist. | [Platform feedback](https://docs.mem0.ai/platform/features/feedback-mechanism) |
| M07 | Schema-driven Platform export/summary is different from local pagination and backup. Begin with scoped raw export and checksums only when needed. | A concrete portability/reporting use case and privacy policy. | [Platform export](https://docs.mem0.ai/platform/features/memory-export), [local restore](restore.md) |
| M08a | Platform project-wide events are absent. OSS per-memory history is **not** exposed as a local REST/MCP history route at the inspected revision. | An audit or async-ingest consumer needs cross-memory ordering; then consider a local journal/read API. | [Platform webhooks/events](https://docs.mem0.ai/platform/features/webhooks), [local server](../runtime/server.py) |

## Intentionally not adopted under the current boundary

| ID | Decision | Reopen when | Evidence |
| --- | --- | --- | --- |
| M08b | Do not add outbound webhook delivery, retries, and signing to a loopback service just for parity. | An external subscriber and explicit egress/security policy are approved. | [Platform webhooks](https://docs.mem0.ai/platform/features/webhooks) |
| M09 | Do not imitate Platform org/project/role/tenant control planes for the proposed single-operator deployment. Metadata `app_id` is not tenant isolation. | Any LAN/team exposure; authentication, authorization, and tenant isolation then become blocking security work. | [Platform vs OSS](https://docs.mem0.ai/platform/platform-vs-oss), [project safety defaults](../README.md#safety-defaults) |
| M10 | Do not offer unguarded batch update/delete. Preserve the existing scope, revision, backup, lock, and action-limit safeguards. | Measured operations volume justifies a bounded, reviewed-plan batch with the same safeguards. | [Platform vs OSS](https://docs.mem0.ai/platform/platform-vs-oss), [local Dream safeguards](dream.md) |

## Already present, but not assumed equivalent

The project already has [custom categories](category-management.md), a [temporal approximation](temporal-reasoning.md), [Codex lifecycle hooks](../plugins/mem0-local/README.md), an [opt-in reranker](decisions/0004-opt-in-reranker.md), cursor pagination, and guarded deletion. Their presence is not proof of identical Platform behavior. Private ranking weights, classifier prompts, and feedback effects cannot be inferred from public documentation; use a synthetic comparison corpus if those details become decision-critical.

## How to keep this plan current

1. Start from this page, then check the linked official documentation, the relevant versioned OSS code, and current `main`. Record the evidence date and distinguish repository defaults from verified live behavior.
2. Discuss a concrete change in a GitHub issue or PR. An implementation PR updates the affected ID here with its result, test/acceptance evidence, and merged PR link. Do not maintain a second live status table elsewhere.
3. Revisit the plan monthly (next check: 2026-10-13), and sooner for an upstream/local release, user-reported failure, or operating-boundary change. If nothing changed, record a brief issue comment rather than a no-op documentation commit. No automated reminder is configured.
4. Keep dated research evidence and historical decisions immutable; never copy private configuration, host paths, credentials, or user memories into this public repository.
