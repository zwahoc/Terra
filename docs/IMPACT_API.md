# Terra impact calculation and export API

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
