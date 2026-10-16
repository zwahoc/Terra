# Terra impact calculation and export API

## Non-persisting forecast and optimisation previews (14 October 2026)

Member 4 now exposes `ForecastPreviewCalculator` in
[forecast_preview_service.py](../backend/app/services/forecast_preview_service.py).
It accepts existing record collections, detaches one consistent input context,
validates operational eligibility/caps, and exposes:

- `assess_forecast_preview(supply_offer_id, demand_request_id, quantity)`:
  temporary forecast components, missing data, factor snapshots and assumptions.
- `score_linear_candidates()`: Member 3's `LinearCarbonScores` batch for all
  eligible pairs. This explicitly guarantees fixed-context per-piece linearity;
  proposed = moved = processed quantity, substitution ratio 1, no fixed/shared trips.

Factor selection and arithmetic are shared with saved assessments through
`calculate_context_components()` in impact_service.py. No placeholder proposals,
impact IDs, revision heads, reservations or database writes are needed.
Missing net is None, never zero; negative coefficients reach Member 3's agreed
exclusion policy. Previews do not add a database basis enum.

Two new **read-only-in-effect POST** extensions use Terra's `{data, meta, error}`
envelope. Each reads the emulator snapshot once and never calls persistence:

`POST /api/impact-assessments/forecast-preview`

```json
{
  "supply_offer_id": "SUP-003",
  "demand_request_id": "DEM-003",
  "quantity": 200,
  "planning_date": "2026-10-12",
  "factor_dataset_version": "demo-v1"
}
```

Baseline result: production 190, freight 5.19168, processing 4, net 180.80832
kgCO2e. `data` includes `preview: true`, `persisted: false`, context/snapshot
hashes, components, status, missing data and factor provenance. Decimal results
are JSON **strings** to preserve precision; the frontend should parse them for
display rather than implement carbon arithmetic.

`POST /api/optimisation-runs/preview`

```json
{
  "objective": "MAX_NET_CO2E_AVOIDED",
  "planning_date": "2026-10-12",
  "factor_dataset_version": "demo-v1",
  "destination_project_id": "PRJ-002"
}
```

Accepts all three existing objectives. `data.plan` contains the allocator result;
`data.forecast_previews` assesses each chosen pair at its final proposed quantity
using the same detached context. `data.forecast_summary` distinguishes complete
selected-plan net, known subtotal, incomplete allocations and candidate scoring
coverage. An unscored carbon run can return an empty plan: inspect the plan's
`carbon_scoring_available` and `incomplete_carbon`, not just its zero quantity.
MAX_REUSE/deadline plans can have missing final forecasts despite needing no
carbon scores for allocation. Opposing strategies should be compared separately,
not added together.

The preview endpoint deliberately does **not** persist anything. To save the
chosen matching calculation, call `POST /api/optimisation-runs` with the same
calculation fields plus a required `idempotency_key` and `actor_label`. It
recalculates from one current database snapshot, then atomically inserts an
optimisation run and its `SELECTED`/`ELIGIBLE` allocation proposals. It does not
create a transfer, reservation, stock mutation, demand commitment, or any
physical-delivery event. `GET /api/optimisation-runs/{run_id}` retrieves the
persisted run and proposals. `destination_project_id` is optional for backward
compatibility; when supplied, the optimiser considers only confirmed demand for
that destination while retaining cross-project supply candidates. The browser
must send this scope to FastAPI rather than filtering a global plan locally.
Potential-surplus preview is not accepted.

Planning date must cover the timestamps of supplied live records. Baseline date
2026-10-12 works on untouched seed data; use the applicable live planning date
after runtime writes. Preview factor applicability uses planning_date. Existing
saved proposal forecasts still use proposal.created_at: integration must agree
that date and bind the same full context before claiming identical saved results.
The allocation-input hash is stored as the persisted run's input snapshot hash;
it fingerprints mapped allocation inputs rather than a complete source-document
or engineering-certification record.

HTTP 400 rejects noneligible pairs, quantities exceeding caps and invalid
snapshot/context records; 422 rejects malformed/unknown request fields; 503
reports emulator unavailability without seed fallback. Missing factors/mass/routes
produce an incomplete forecast rather than a fabricated value.

Offline tests: `python3 -m unittest tests.test_forecast_preview -v`.

The original persisted assessment and export APIs below retain their contracts.

This milestone calculates traceable comparative impact estimates through
framework-independent Python services and persists them through Terra's
loopback-only SQL Connect adapter. It does not issue credits, certify factors,
alter a corporate inventory, call Pantas, or claim independent environmental
verification.

## Boundaries and arithmetic

`PROPOSAL_FORECAST` uses `allocation_proposals.proposed_quantity` for
production, freight and the supported per-piece handling assumption.
`ACTUAL_CONFIRMED_USE` uses `transfers.actually_used_quantity` for production
but retains the physical `dispatched_quantity` for freight. Freight and
processing are never silently set to actual-use quantity.

The deterministic Decimal engine applies:

- per-piece production = assessed quantity x `kgCO2e/pcs` factor;
- per-kg production = assessed quantity x mass kg/unit x `kgCO2e/kg` factor;
- freight = moved quantity x mass kg/unit / 1000 x route km x
  `kgCO2e/t-km` factor;
- processing = explicit processed quantity x matching per-piece or per-kg
  factor;
- simplified net = production substitution - additional freight - processing.

The baseline is hypothetical displacement of functionally equivalent new
procurement. Baseline freight, disposal and credit issuance are excluded. The
route is the single synthetic symmetric road-distance record between source and
destination. For forecast and fully used transfers, all moved units receive the
seed model's per-piece handling factor. When a received shipment is only partly
used, Terra has no approved allocation of handling between used and residual
units: processing and net are `null`, status is `INSUFFICIENT_DATA`, and
`PROCESSING_BOUNDARY` is reported. Missing inputs/factors are never zero, and a
negative calculated net is preserved.

The component methods align with the GHG Protocol's activity-data-times-factor
and mass-distance freight approaches and its comparative avoided-emissions
guidance. Those sources do not certify Terra's synthetic factors or establish
carbon-credit eligibility:

- <https://ghgprotocol.org/sites/default/files/2022-12/Chapter1.pdf>
- <https://ghgprotocol.org/sites/default/files/2022-12/Chapter4.pdf>
- <https://ghgprotocol.org/estimating-and-reporting-avoided-emissions>

## Deterministic factor selection

A factor must match factor type, optimisation run's dataset version, activity
date (`valid_from` not later than activity), supported unit and the exact
lifecycle boundary. Transport also requires `ROAD_FREIGHT`. Material-specific
factors outrank category factors, which outrank factors with no material scope.
Within the winning scope, the newest valid date wins. Two equally specific
factors on that date are ambiguous; Terra reports missing coverage instead of
choosing by row order. Stored assessments retain factor IDs and complete factor
snapshots, including source, URL, version, boundary and `is_demo_factor`.

## Revision and current-result contract

Every successful calculation inserts an immutable `impact_assessments` row and
advances one scope head (`basis + proposal` or `basis + transfer`) in the same
transaction. The head is Terra's current result: the latest successfully
persisted operator-requested revision for that exact scope and basis. It is not
an independent environmental approval. The assessment records revision number,
previous assessment ID, reason, actor, current timestamp and reproducible input
fingerprint. Exports select heads only, so superseded revisions cannot be
double-totalled.

The persistence mutation compares the expected head revision and the source
proposal/transfer quantities and timestamps. If use changes while calculation
is in flight, the stale result cannot overwrite the newer state; HTTP 409
`IMPACT_INPUT_STALE` instructs the caller to recalculate. An identical
idempotency retry returns the same assessment with `replayed: true`; changing
request input while reusing the key returns HTTP 409.

## Postman setup and exact requests

From `D:\Terra`, run `npm run emulator`, `npm run seed`, and `npm run
dev:backend` in separate terminals. In Postman use base URL
`http://127.0.0.1:8000`, Authorization `No Auth`, header `Content-Type:
application/json`, and raw JSON bodies.

Forecast regression:

`POST /api/impact-assessments/proposals/ALC-001/calculate`

```json
{"idempotency_key":"postman-impact-alc001-r2","revision_reason":"Recalculate documented seed regression","actor_label":"Demo operator"}
```

Verified fixture inputs are 600 pcs, 2.5 kg/pcs, 25 km, EF-001 = 0.75
kgCO2e/pcs, EF-007 = 0.12 kgCO2e/t-km and EF-008 = 0.02 kgCO2e/pcs.
Expected components are production `600 x 0.75 = 450`, freight `600 x 2.5 /
1000 x 25 x 0.12 = 4.5`, processing `600 x 0.02 = 12`, net `433.5`
kgCO2e. This is not Document 01's separate illustrative 10 kg handling
assumption and 435.5 result. The new row is revision 2 after seed `IMP-001`.

Actual confirmed-use calculation:

`POST /api/impact-assessments/transfers/TRF-007/calculate`

```json
{"idempotency_key":"postman-impact-trf007-r2","revision_reason":"Recalculate confirmed-use result","actor_label":"Demo operator"}
```

`TRF-007` has 400 used/moved pieces of MAT-001 at 2.5 kg/piece over 8 km.
Expected production is 300, freight 0.96, processing 8, and net 291.04
kgCO2e. Use the response's current timestamp; do not expect a seed timestamp.

Partial-use missing-data check:

`POST /api/impact-assessments/transfers/TRF-006/calculate`

```json
{"idempotency_key":"postman-impact-trf006-r2","revision_reason":"Verify unresolved partial-use boundary","actor_label":"Demo operator"}
```

The fixture has 550 actually used but 600 dispatched. Production is 412.5 and
freight is 4.5; processing and net are `null`, status is
`INSUFFICIENT_DATA`, and missing data includes `PROCESSING_BOUNDARY`.

Read-back requests:

- `GET /api/impact-assessments?basis=PROPOSAL_FORECAST&current_only=true`
- `GET /api/impact-assessments?basis=PROPOSAL_FORECAST&current_only=false`
- `GET /api/impact-assessments/{assessment_id}` using the ID returned by POST

The current-only list contains one row for ALC-001: the new assessment. The all
revisions list also retains `IMP-001`. Repeat a POST body unchanged to verify
the same ID/revision and `replayed: true`; use a fresh idempotency key and
reason to create the next immutable revision.

## Export checks

Exact endpoints:

- `GET /api/exports/impact?basis=ACTUAL_CONFIRMED_USE&format=json`
- `GET /api/exports/impact?basis=ACTUAL_CONFIRMED_USE&format=csv`
- `GET /api/exports/impact?basis=PROPOSAL_FORECAST&format=json`
- `GET /api/exports/impact?basis=PROPOSAL_FORECAST&format=csv`

JSON uses Terra's `{data, meta, error}` envelope; CSV is an attachment with one
flat row per current assessment. Both include trace IDs, projects/material,
quantities, components, complete factor provenance, assumptions, evidence
references, status, missing-data coverage, revision and disclaimer. Forecast
and actual are selected separately and `aggregation` is explicitly `null` in
JSON. The export does not combine competing alternatives into a plan or label
reused mass as diverted waste without baseline evidence.
