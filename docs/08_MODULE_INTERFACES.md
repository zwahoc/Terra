# 08 — Module interfaces, API DTOs and collaboration boundaries (future MVP)

**Status:** Future API/DTO contract, synchronised with Document 09. The chosen framework and runtime are fixed; endpoint details may be refined during implementation. **The local seed task must not build the full API.** Quantity/status/provenance semantics remain stable.

```text
React + TypeScript + Tailwind CSS
    -> HTTPS/JSON -> FastAPI, thin Python routes + Pydantic DTOs
    -> framework-independent Python services/domain functions
    -> repositories -> Python REST adapter, authentication proof required
    -> Firebase SQL Connect named operations -> Cloud SQL PostgreSQL
```

FastAPI owns endpoints, intake orchestration, validation and error mapping. Python services own business calculations. No separate Node backend or browser-direct Firebase application access is planned. Node.js is limited to Firebase tooling or justified one-off utilities. API DTOs use `snake_case`; the adapter maps SQL Connect `camelCase` fields without exposing provider credentials.

## 1. Module ownership and contracts

| Module | Responsibility | Consumes | Produces | Excludes |
|---|---|---|---|---|
| Frontend (Member 1) | React/TypeScript/Tailwind dashboard, inventory, review, matches/carbon, transfers/ESG | FastAPI DTOs and status enums | Operator requests/actions through FastAPI | Authoritative stock/carbon calculations or direct Firebase operations |
| AI Material Intelligence (Member 2) | Independent Python parsers, normalized rows, LLM-assist, review/publication integration | Document and catalogue metadata | Reviewable `extracted_rows` + candidate canonical mappings | Declaring confirmed surplus from LLM alone or updating transfer counters |
| Circular Optimiser (Member 3) | Constraint validation, allocation alternatives and reasons | Confirmed uncommitted supply, outstanding demand, routes, material specs | `optimisation_runs` + `allocation_proposals` | Direct transfer reservations and physical-use claims |
| Carbon & Transfer (Member 4) | Factor selection, forecast/actual carbon results, atomic lifecycle, exports | Proposals, transfers, factors, routes, verified use | `transfers`, `transfer_events`, `impact_assessments`, ESG export | Real carbon credits and official corporate GHG accounting |

The Python backend is one application with shared database state. Processing modules call internal service/repository interfaces; React calls FastAPI. A supply/demand service performs deterministic potential-surplus/outstanding-demand calculations after documented input validation. Modules do not independently write coupled counters. Repositories isolate REST credentials, operation names, mappings and persistence. Test domain functions without HTTP/Firebase, then test adapter and API separately. No independently deployed module services or queues are required.

## 2. Proposed API responses

Use a consistent envelope:

```json
{
  "data": {},
  "meta": {"dataset_version": "1.0.0", "synthetic": true, "as_of_date": "2026-10-12"},
  "error": null
}
```

For failures: `data=null`, `error={"code":"...", "message":"...", "details":{...}}`; appropriate HTTP codes. Avoid untyped silent success and never expose admin credentials in responses.

The metadata above describes the synthetic baseline, not the current time. The Firebase REST response is provider-specific; the adapter must detect operation errors and FastAPI maps them into this Terra envelope. Server-to-database authentication remains necessary despite the absence of app login. Public demo writes require a separately agreed access plan.

### Read endpoints for initial frontend mocking

- `GET /api/projects` — project list.
- `GET /api/materials?category=PAVING_BLOCK` — catalogue.
- `GET /api/supply-offers?status=CONFIRMED&project_id=PRJ-001` — effective stock and raw counters. Each record should include **derived** `reservable_quantity` (does not increase confirmed amount).
- `GET /api/demand-requests?status=OPEN` — include `remaining_unfulfilled_quantity` and `newly_allocatable_quantity` reflecting active incoming commitments.
- `GET /api/optimisation-runs` and `GET /api/optimisation-runs/{id}/proposals` — alternative plans by run.
- `GET /api/transfers` — current stages and quantities.
- `GET /api/dashboard/summary` — derived metrics, with forecast vs actual impact split.

The first Codex task may only create a **query/connector data path and docs**, not HTTP routes.

### Document/AI endpoints (later)

- `POST /api/documents` — file reference/upload, class type, project.
- `GET /api/documents/{id}/extracted-rows` — raw/candidate extraction fields.
- `PATCH /api/extracted-rows/{id}` — human correction status and fields.
- `POST /api/extracted-rows/{id}/publish` — idempotent conversion after business validation.
- `GET /api/materials?query=...` — canonical lookup and mapping suggestions, also supporting the category filter above.

### Optimisation endpoints

Non-persisting integration extensions are implemented at
`POST /api/optimisation-runs/preview` and
`POST /api/impact-assessments/forecast-preview`. See
[IMPACT_API.md](IMPACT_API.md) for their explicit request/response contracts.
They return temporary plans/forecasts without run/proposal/assessment IDs or
writes.

`POST /api/optimisation-runs`

```json
{
  "objective": "MAX_NET_CO2E_AVOIDED",
  "planning_date": "2026-10-12",
  "factor_dataset_version": "demo-v1",
  "destination_project_id": "PRJ-002",
  "idempotency_key": "optimise-2026-10-12-prj-002",
  "actor_label": "Demo operator"
}
```

This computes the same eligible matching calculation from one database snapshot,
then atomically creates an immutable `optimisation_run`, its `SELECTED` and
`ELIGIBLE` allocation proposals, and an idempotency operation record. The
response returns `data.run` and `data.proposals`; `GET
/api/optimisation-runs/{run_id}` returns that persisted run and its proposals.
The endpoint creates no transfer, reservation, stock mutation, demand
commitment, dispatch, receipt, or reuse. Repeating the same idempotency key and
payload returns the original result; reusing it with different input returns a
conflict. Previewing potential surplus must **never make it reservable**.

For the current MAX_REUSE implementation, the latest user-requested priority is
maximum allocated pcs, earliest demand `required_by`, earliest feasible delivery,
shorter route and stable IDs. See SRS Section 12.1 for the amendment and provenance.
This changes the internal plan preference policy, not the endpoint or DTO fields.

### Transfer workflow endpoints

`POST /api/allocation-proposals/{id}/approve` — approve a matching proposal, then atomically create its `REQUESTED` transfer and `REQUESTED` event. It accepts `actor_label`, `idempotency_key`, optional `evidence_ref`, and optional `notes`. The proposal must be `SELECTED` and `ELIGIBLE`; duplicate requests for a proposal return a conflict. Its requested quantity equals the proposal quantity. It creates no reservation, stock mutation, demand commitment, dispatch, receipt, or reuse.
`POST /api/transfers/{id}/approve` — legacy compatibility for existing synthetic baseline records only; new proposal approvals use the endpoint above.
`POST /api/transfers/{id}/reserve` — **transactional, idempotent** stock and incoming demand commitment check.  
`POST /api/transfers/{id}/dispatch` — record quantity dispatched and decrement active reservation.  
`POST /api/transfers/{id}/receive` — intentional MVP restriction: confirm the complete dispatched quantity arrived in one operation; no request quantity, partial/missing delivery, or confirmed reuse.
`POST /api/transfers/{id}/confirm-use` — record quantity actually used and update demand fulfilled counters.  
`POST /api/transfers/{id}/cancel` — cancel before dispatch with a reason and atomic release of remaining holds/commitments; post-dispatch exception handling remains an open contract.  
`POST /api/impact-assessments/proposals/{proposal_id}/calculate` — append a `PROPOSAL_FORECAST` assessment revision.

`POST /api/impact-assessments/transfers/{transfer_id}/calculate` — append an `ACTUAL_CONFIRMED_USE` assessment revision after confirmed use.

`GET /api/impact-assessments?basis={basis}&current_only=true|false` — read one current head per scope by default, or immutable revision history.

`GET /api/impact-assessments/{assessment_id}` — read one traceable assessment revision.

`GET /api/exports/impact?basis=ACTUAL_CONFIRMED_USE&format=json|csv` — controlled ESG export.

For any mutating route, require `idempotency_key` or equivalent replay-safe operation ID; duplicate requests must not double-apply quantity. Return updated transfer state and inventory snapshot.

Selection and approval are not reservation. At reserve time, revalidate current confirmation, specs/units/date window, source stock and recipient uncommitted need within the same race-safe operation. Dispatch reduces the source hold and increases transferred-out quantities once. Receipt does not increase fulfilled demand; confirmed use does. Remaining unused/missing promises require explicit resolution before release. No endpoint may silently invent a return or count a forecast as achieved reuse. See Document 07 for unresolved partial-transfer closure and actual-use transport-cost policy.

## 3. Shared error codes

| Code | Meaning |
|---|---|
| `INVALID_SOURCE_TYPE` | BOQ/PO data improperly offered as available stock |
| `ROW_NOT_REVIEWED` | Attempted publication before acceptance |
| `MATERIAL_SPEC_MISMATCH` | Critical dimensions/grade/type mismatch |
| `UNIT_CONVERSION_UNSUPPORTED` | Cannot convert to catalogue unit reliably |
| `SUPPLY_NOT_CONFIRMED` | Potential/suspended/closed supply not reservable |
| `INSUFFICIENT_STOCK` | Confirmed stock minus commitments too small |
| `DEMAND_ALREADY_COMMITTED` | Existing incoming transfers exhaust need |
| `INVALID_DATE_WINDOW` | Availability vs need-by mismatch |
| `INVALID_TRANSFER_TRANSITION` | Status stage prerequisites not met |
| `IDEMPOTENCY_REPLAY` | Operation already processed (may return original success) |
| `CARBON_INSUFFICIENT_DATA` | Missing factor/mass/route/handling boundary for full assessment |
| `UNSUPPORTED_FORMAT` | Document parser cannot handle a file |
| `PARSING_FAILED` | Supported document format could not be parsed; retain failure context without publishing business records |

## 4. Example response: eligibility with carbon explanation

```json
{
  "proposal_id": "ALC-001",
  "supply_offer_id": "SUP-001",
  "demand_request_id": "DEM-001",
  "proposed_quantity": 600,
  "unit": "pcs",
  "compatibility_result": "ELIGIBLE",
  "reason_codes": ["SAME_CANONICAL_MATERIAL", "SPECIFICATIONS_MATCH", "DATE_WINDOW_OK"],
  "carbon_preview": {
    "calculation_status": "DEMO",
    "avoided_production_kgco2e": 450,
    "additional_transport_kgco2e": 4.5,
    "additional_processing_kgco2e": 10,
    "net_avoided_kgco2e": 435.5,
    "all_factors_synthetic": true,
    "baseline_description": "Hypothetical replacement of 600 functionally equivalent new blocks"
  }
}
```

Numbers above refer only to the illustrative example in `01_BUSINESS_WORKFLOW.md`. This DTO is illustrative and is **not** a guaranteed record ID in the eventual seed; the generated scenario index is authoritative.

## 5. Versioning and ownership rule

When one module changes a shared field, add a migration/contract change and update API types/docs/tests in the same pull request. Provide canonical schema models and enum definitions as shared artifacts where practical. Do not let members invent independent interpretations of `confirmed_quantity`, `actually_used_quantity`, or carbon factor units.
