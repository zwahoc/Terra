# Matching and objective comparison API

## Current automatic matching

GET /api/matching returns material scopes with CURRENT/PENDING/FAILED state. A current generation exposes reuse, deadline and carbon alternatives calculated from identical source/recipient budgets, date and factor context. It includes run/proposal IDs, allocations, coverage, selected-pair forecasts and scoring completeness. Current reads validate dependency fingerprints/day; unavailable/stale scopes do not expose old executable recommendations.

Matching runs after matching-relevant commits, across all projects for affected materials. Draft analysis/review edits and history-only publication do not create new commitments or require matching. The Python worker coalesces unchanged scopes, persists complete alternatives under expected revision/scope checks and retains failed state for explicit retry. POST /api/matching/refresh retries deterministic matching, never calls an LLM or approves/reserves a transfer.

Future opportunities retain earliest dispatch/arrival and deadline. They cannot confirm before allowed. Existing transfer provenance is not expired when a newer recommendation is computed. Unwanted recommendations may simply remain unapproved; dismissal/snooze is not implemented.

## Explicit preview comparison

`POST /api/optimisation-comparisons/preview`

Body: planning_date, factor_dataset_version, optional destination_project_id. It uses one consistent read, immutable detached processing and three objective results. No database write, transfer, stock hold or actual-use claim occurs.

An alternative contains plan allocations/remaining budgets, demand coverage, forecast_previews and forecast_summary. Selected forecast completeness differs from candidate-scoring completeness: the carbon solver may exclude unknown-score candidates even when all selected allocations have known forecasts. An empty carbon result with unavailable scoring is not fabricated zero benefit. Equal objective plans are valid.

`POST /api/optimisation-runs/preview` uses the same context fields plus objective to compute one alternative. [Allocator](OPTIMISATION_ALLOCATOR.md) defines objective/tie policies; [Impact API](IMPACT_API.md) defines factor/component authority.

## Persist explicit results

| Route | Input/effect |
|---|---|
| POST /api/optimisation-runs | Preview fields plus idempotency_key and actor_label; recalculates and atomically saves a run, selected eligible proposals and initial forecast/head records, no transfers |
| POST /api/optimisation-comparisons | Comparison fields plus idempotency_key and actor_label; saves linked same-input objective results and assessments without operational holds |
| GET /api/optimisation-runs/{run_id} | Saved run, proposals and retained linked assessment context |

The complete stored inputs_snapshot_hash includes material, route, factor and commitment context. The mapped allocation_snapshot_hash and full carbon_context_id are distinct and cannot substitute for one another. Key replay requires the same fingerprint; stale changed source state cannot produce an inconsistent saved plan. Caller-provided summaries are not persisted as authoritative calculations.

Automatic matching uses its own current scope/generation persistence rather than asking the operator to save a run before every action. Current proposals proceed through [combined confirmation/reservation](TRANSFER_WORKFLOW_API.md), not the legacy request-only approve endpoint.

## Explicit input corrections

GET /api/matching/inputs returns a guarded operational revision and available projects/materials/routes. POST /api/matching/inputs accepts confirmed MATERIAL_MASS/ROUTE_DISTANCE/PROJECT_FACTS corrections with relevant IDs, values, basis, expected_revision and idempotency_key. The transaction saves audit/before/after, invalidates affected matching and enqueues applicable actual-impact refreshes. It never changes physical-use facts or creates a factor dataset.

Material weight is kg per catalogue unit; route distance is road km. Confirmed demonstration estimates are permitted with truthful basis. Null/blank/conflicting project corrections cannot erase facts. Source context must remain verifiable.

## Browser contract

Material-first search, filters, sorting and pagination organise the complete returned result set without relevance ranking/top-N suppression. Totals add only comparable units within the selected alternative. Review passes the exact source/recipient pair and existing run identity into confirmation; missing pairs never select another automatically. Sidebar entry is fresh; contextual Back restores browsing preference scoped to workspace identity. A lost connection keeps visible work but disables execution until current checks succeed.

## Sources and tests

[Routes](../backend/app/routes/impact.py), [matching routes](../backend/app/routes/matching.py), [matching service](../backend/app/services/matching_service.py), [comparison orchestration](../backend/app/services/optimisation_preview_service.py), [persistence](../backend/app/services/optimisation_comparison_service.py). Tests cover same-input alternatives, replay/stale rejection, scoring/timing/unit cases and complete browser pagination; see [Document 06](06_REQUIREMENTS_AND_TESTS.md) for acceptance limits.
