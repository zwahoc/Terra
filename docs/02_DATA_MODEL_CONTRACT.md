# 02 — Data model contract

## Scope and sources

The portable canonical seed has 13 arrays with fixed demonstration entities/enums and an as-of date of 2026-10-12. The implemented runtime extends it with open-ended material identities/units, exact quantities, provisional intake and immutable publication evidence. Do not apply old seed-only category/pcs restrictions to new runtime materials or rewrite the seed to match current operations.

`terra/contract.py` defines FIELDS and seed/runtime validators; generated `.gql` defines provider relations. Python validates JSON evidence where a database FK does not cover an embedded member. React uses FastAPI DTOs, not provider rows. [Document 09](09_ARCHITECTURE_UPDATE.md) governs access.

## General conventions

- String IDs are stable identities, never names/array positions. Existing database IDs and temporary run-local proposal IDs remain distinct until publication resolves them.
- API/portable JSON fields use snake_case; SQL Connect fields use camelCase. Dates are YYYY-MM-DD; timestamps preserve instants with the local +08:00 display/mapping convention.
- Null means unknown/absent, not zero. Never silently discard provenance or map an unknown material quantity to a source-work number.
- Operational exact quantities use Python integers/Decimal and SQL Int64 millionths. Persisted QuantityEncoding.version=millionths-v1 governs the adapter. Six decimal places are supported up to 9223372036854.775807 ordinary units. Whole counts apply to pcs, bag, sheet, roll and length. Unsupported precision/range fails without rounding.
- JSON evidence/source snapshots retain ordinary units. Seed JSON stays unchanged. A missing encoding marker denotes legacy whole-unit data; never initialise a marker over populated legacy rows.
- Original source fields, reviewed current fields, conversion factor/basis and operator-edit flags are separate. Revisions and physical events are not replaced by a regenerated summary.
- Current offer/demand counters reconcile to transfers. See [Document 01](01_BUSINESS_WORKFLOW.md) for budgets and physical lifecycle.

The following field tables describe the canonical entities and fixed sample counts, not the owner's current database. Synthetic/metadata-only flags remain truthful in seed storage; local model-facing business context need not repeat fixture-origin labels. Unknown evidence remains visible.

## Canonical entity field reference

### `projects` — 5 records

| Field | Type | Constraint / semantics |
|---|---|---|
| `id` | string PK | e.g. `PRJ-001` |
| `code` | string unique | human-readable code |
| `name` | string | fictional demo project |
| `township` | string | real-sounding Malaysian location, site fictional |
| `location` | object/null | `{lat, lon}` approximate demo coordinate if needed; route distances remain authoritative |
| `start_date`, `target_end_date` | date/null | project schedule |
| `status` | enum | `ACTIVE`, `COMPLETED` |
| `managing_organisation` | string | e.g. `Synthetic Contractor A` |

No project record may claim to be verified from SDP's internal systems.

### `materials` — ~20 canonical SKUs/spec combinations

| Field | Type | Constraint / semantics |
|---|---|---|
| `id` | string PK | `MAT-001` etc. |
| `category` | enum | Existing seed: `PAVING_BLOCK`, `BRICK`, `TILE`; runtime registration uses open-ended category strings |
| `canonical_name` | string | specific material/spec name |
| `specifications` | object | typed dictionary: dimensions in `*_mm`; grade/type/colour/finish where relevant |
| `standard_unit` | enum | Existing seed `pcs`; runtime registration/conversion accepts validated comparable units |
| `mass_kg_per_unit` | decimal/null | numeric only if explicitly demo-estimated or sourced |
| `mass_source` | string/null | `SYNTHETIC_ASSUMPTION` or named source; not invented verified weight |
| `reference_code` | string/null | example SKU, not real manufacturer certification |
| `is_synthetic` | bool | true in demo |

Catalogue uniqueness must combine category + identifying specs (not name alone). Different thickness/grade/size => different SKUs.

### `documents` — 12–15 **metadata-only** records

| Field | Type | Constraint / semantics |
|---|---|---|
| `id` | string PK | `DOC-001` |
| `project_id` | string FK | `projects.id` in the seed; multi-project runtime provenance uses the publication records below |
| `document_type` | enum | `BOQ`, `PURCHASE_ORDER`, `INVENTORY`, `DEMAND`, `OTHER` |
| `display_filename` | string | `example_project_inventory.xlsx` synthetic label |
| `file_uri` | string/null | **null until a real test fixture is provided** |
| `file_hash` | string/null | **null**, don't forge SHA values for absent files |
| `source_availability` | enum | `METADATA_ONLY`, `FILE_AVAILABLE` for actual uploaded evidence |
| `processing_status` | enum | `SIMULATED`, `QUEUED`, `PROCESSED`, `FAILED`, `REVIEWED` for actual processing |
| `recorded_at` | timestamp | before/as-of seed date |
| `is_simulated` | bool | true |

The existence of a document *record* is not evidence an actual XLSX/PDF is present.

### `extracted_rows` — 40–60 synthetic AI-like row records

| Field | Type | Constraint / semantics |
|---|---|---|
| `id` | string PK | `ROW-001` |
| `document_id` | string FK | `documents.id` |
| `source_locator` | string | `Sheet: Inventory, Row: 12` is a synthetic location only |
| `raw_description` | string | preserve noisy original style |
| `raw_quantity`, `raw_unit` | string | source text, e.g. `1,200`, `PCS` |
| `parsed_fields` | object | canonical quantity/unit, dimensions/specs/date/classification |
| `suggested_material_id` | string FK/null | mapping candidate to `materials` |
| `confidence_score` | decimal/null | in `[0,1]`; **indicative, synthetic** |
| `review_status` | enum | `PENDING`, `ACCEPTED`, `CORRECTED`, `REJECTED` |
| `review_mode` | enum | `DEMO_PREAPPROVED`, `PENDING_DEMO`, `MANUAL_CORRECTION` |
| `is_simulated` | bool | true |

Use `parsed_fields.record_kind`: `PLANNED_REQUIREMENT`, `PURCHASE_ORDER`, `ON_HAND_INVENTORY`, `POTENTIAL_SURPLUS`, `CONFIRMED_SURPLUS`, `OUTSTANDING_DEMAND`. **A document type alone does not prove actual surplus or outstanding demand**. Reject invalid quantities/units, preserve both raw and corrected values. A source document row might be linked to a supply or demand via an explicit reviewed action.

The seed retains BOQ, PO and on-hand facts in reviewed extraction rows; it does not introduce a separate procurement or inventory ledger. Deterministic Python services can calculate potential surplus/outstanding need only from sufficient documented inputs. These calculations and accepted row status do not confirm releasable stock. Runtime review/publication use the separate records described below.

### `supply_offers` — 20–25 rows

| Field | Type | Constraint / semantics |
|---|---|---|
| `id` | string PK | `SUP-001` |
| `source_project_id` | string FK | `projects.id` |
| `material_id` | string FK | `materials.id` |
| `origin_document_row_id` | string FK/null | `extracted_rows.id`; optional manual-demo origin |
| `declared_quantity` | decimal | nonnegative |
| `confirmed_quantity` | decimal/null | null if no confirmed stock |
| `reserved_active_quantity` | decimal | default 0; derived from active transfers |
| `transferred_out_quantity` | decimal | default 0; cumulative stock issued, **not** reused |
| `unit` | string | matches or explicitly converts to material canonical unit |
| `surplus_status` | enum | `POTENTIAL`, `CONFIRMED`, `SUSPENDED`, `CLOSED` |
| `condition` | enum | `UNUSED`, `RECOVERED`, `UNKNOWN` |
| `available_from`, `available_until` | date/null | start required; until optional >= from |
| `batch_or_lot_code` | string/null | traceability |
| `material_owner_label` | string/null | synthetic organisation label; not auth user |
| `evidence_refs` | array | real evidence absent; use synthetic labels only |

For seeded `POTENTIAL` offers, `confirmed_quantity=null` and active reservation/dispatched quantities are zero. For `CONFIRMED`, `confirmed_quantity >= reserved_active_quantity + transferred_out_quantity`. Do not derive confirmation from a BOQ. `reservable=max(0,confirmed-reserved-transferred)` only for eligible condition/status/date. Missing stock confirmation means zero reservable quantity, not subtraction from null.

### `demand_requests` — 20–25 rows

| Field | Type | Constraint / semantics |
|---|---|---|
| `id` | string PK | `DEM-001` |
| `destination_project_id` | string FK | `projects.id` |
| `material_id` | string FK | `materials.id` |
| `origin_document_row_id` | string FK/null | `extracted_rows.id` |
| `required_quantity` | decimal | > 0 |
| `fulfilled_quantity` | decimal | actual satisfied need; >=0, <= required |
| `unit` | string | canonical/explicitly convertible |
| `needed_from`, `required_by` | date | required_by >= needed_from |
| `request_status` | enum | `OPEN`, `FULFILLED`, `CANCELLED` |
| `is_outstanding_need_confirmed` | bool | BOQ-only estimates false until reviewed |

For planning, subtract not only fulfilled quantity but **active incoming committed** transfers, established at reservation and retained until use or explicit resolution. New individual approval/reservation creates RESERVED and holds demand atomically. A historical requested transfer does not hold demand. `APPROVED` is retained only for historical seed compatibility and likewise does not hold demand. Seed `fulfilled_quantity` reconciles to transfer actual-use quantities; `FULFILLED` requires `fulfilled_quantity=required_quantity`. Alternative procurement fulfilment records are outside this seed model. Cancelled demands are not available for fresh allocations; cancellation must not silently discard an active incoming commitment.

### `route_distances` — 10 unordered inter-project pairs for 5 projects

| Field | Type | Constraint / semantics |
|---|---|---|
| `id` | string PK | `RTE-001` |
| `from_project_id`, `to_project_id` | string FK | distinct `projects.id`; for a symmetric fixture store one canonical ordered pair |
| `distance_km` | decimal | > 0 |
| `assumption_type` | enum | `SIMULATED_ROAD_DISTANCE` |
| `transport_mode` | enum | MVP `ROAD_FREIGHT` |
| `is_synthetic` | bool | true |

Route lookup may treat 10 canonical undirected pairs as bidirectional only if the calculation explicitly states symmetric demo assumption. No straight-line route substituted silently for realistic transport distance.

### `optimisation_runs` — 3–5 historical runs

| Field | Type | Constraint / semantics |
|---|---|---|
| `id` | string PK | `RUN-001` |
| `created_at` | timestamp | <= `as_of_date` |
| `objective` | enum | `MAX_REUSE`, `MAX_NET_CO2E_AVOIDED`, `EARLIEST_DEADLINE` |
| `inputs_snapshot_hash` | string | deterministic hash of serialised input snapshot; do not fabricate hash unrelated to inputs |
| `input_snapshot` | object | bounded snapshot or resolvable reference to versioned historical inputs, sufficient to recompute the hash and eligibility |
| `factor_dataset_version` | string | match factor versions used |
| `solver_status` | enum | `SUCCEEDED`, `INFEASIBLE`, `FAILED` |
| `assumptions` | object | constraint and method details |

Historical plans are **results from earlier inputs**, not fresh reservations. Recompute current recommendations against current stock/demand, not history.

### `allocation_proposals` — 10–15 rows

| Field | Type | Constraint / semantics |
|---|---|---|
| `id` | string PK | `ALC-001` |
| `run_id` | string FK | `optimisation_runs.id` |
| `supply_offer_id` | string FK | `supply_offers.id` |
| `demand_request_id` | string FK | `demand_requests.id` |
| `proposed_quantity` | decimal | > 0 |
| `unit` | string | canonical material unit |
| `compatibility_result` | enum | `ELIGIBLE`, `REVIEW_REQUIRED`, `INELIGIBLE` |
| `status` | enum | `PROPOSED`, `SELECTED`, `REJECTED`, `EXPIRED` |
| `reason_codes` | string[] | e.g. `SAME_SPEC`, `DISTANCE_BETTER`, `TOO_LATE`, `GRADE_MISMATCH` |
| `created_at` | timestamp | consistent with run |

Only `ELIGIBLE` selectable; `REVIEW_REQUIRED` means human check before reclassification. Ineligible proposals may appear as rejected/explained candidates but MUST NOT create reserved transfers. Proposals in different runs are competing *alternatives*, not additive allocations.

### `transfers` — 5–8 rows

| Field | Type | Constraint / semantics |
|---|---|---|
| `id` | string PK | `TRF-001` |
| `proposal_id` | string FK unique | `allocation_proposals.id` (one transfer/proposal) |
| `approved_quantity` | decimal | >=0 and <= proposed |
| `reserved_quantity` | decimal | active hold while not issued; derived/reconciled |
| `dispatched_quantity` | decimal | cumulative physically issued |
| `received_quantity` | decimal | <= dispatched |
| `actually_used_quantity` | decimal | <= received |
| `status` | enum | `REQUESTED`, `APPROVED`, `RESERVED`, `IN_TRANSIT`, `RECEIVED`, `REUSED`, `CANCELLED` |
| `source_confirmation_status`, `destination_confirmation_status` | enum | `PENDING`, `CONFIRMED`, `DECLINED` (workflow simulation, not identities) |
| `requested_at`, `delivered_at`, `reuse_confirmed_at` | timestamp/null | chronologically consistent |
| `notes` | string/null | synthetic exceptions |

`reserved + dispatched <= approved`. No `approved_by_user_id` or auth FK. For a terminal `REUSED` record, actual usage must be positive; no claim of real operator verification in synthetic seed. Historical fixtures may contain partial deliveries/usages. The current first-version runtime permits full dispatch/full receipt and partial/repeated use; dashboard aggregates actual-use quantities only.

Selection alone has no stock/demand effect. Current combined confirmation creates a RESERVED transfer with both commitments; historical unreserved requests/approvals retain zero holds. Successful reservation atomically establishes both commitments; dispatch moves units from reservation to transferred-out exactly once. For partial reuse, received-but-unused quantities stay committed and later positive use increments reduce the remainder. Cancellation is allowed before dispatch and releases both holds. Returns/partial-shipment closure remain outside the first version; A historical terminal fixture must document that resolution, and cannot imply missing units were returned to source stock.

### `transfer_events` — 15–25 rows

| Field | Type | Constraint / semantics |
|---|---|---|
| `id` | string PK | `EVT-001` |
| `transfer_id` | string FK | `transfers.id` |
| `event_type` | enum | `REQUESTED`, `APPROVED`, `RESERVED`, `DISPATCHED`, `RECEIVED`, `USED`, `CANCELLED`, `CORRECTION` |
| `occurred_at` | timestamp | nondecreasing within a transfer |
| `actor_label` | string | `Demo operator` (not a user account) |
| `payload` | object | quantity deltas, reason and synthetic evidence info |
| `evidence_ref` | string/null | synthetic label if no actual evidence |

Event history is append-only. Seeding pre-existing state may use *consistent synthetic event histories*. No claims of real signatures or approvals.

### `emission_factors` — 6–10 rows; include missing-factor cases intentionally

| Field | Type | Constraint / semantics |
|---|---|---|
| `id` | string PK | `EF-001` |
| `factor_type` | enum | `NEW_MATERIAL_PRODUCTION`, `TRANSPORT`, `PROCESSING` |
| `material_id` | string FK/null | nullable for road-freight general factor |
| `material_category` | enum/null | category fallback, if explicitly allowed |
| `transport_mode` | enum/null | `ROAD_FREIGHT` if applicable |
| `value` | decimal | >=0 |
| `unit` | string | `kgCO2e/pcs`, `kgCO2e/kg`, `kgCO2e/t-km`, etc. |
| `source_label`, `source_url` | string/null | use `SYNTHETIC_DEMO_FACTOR` if demo; don't invent journal/URL |
| `geography`, `lifecycle_boundary` | string | explain scope including exclusions |
| `version` | string | `demo-v1` |
| `valid_from` | date | as-of / before seed |
| `is_demo_factor` | bool | true unless verified |

Missing factors are **absent records**, not factors with `value=0`. Explain what boundary is in/out.

### `impact_assessments` — 5–10 rows

| Field | Type | Constraint / semantics |
|---|---|---|
| `id` | string PK | `IMP-001` |
| `basis` | enum | `PROPOSAL_FORECAST`, `ACTUAL_CONFIRMED_USE` |
| `proposal_id` | string FK/null | non-null exactly when basis=forecast |
| `transfer_id` | string FK/null | non-null exactly when basis=actual |
| `quantity_assessed`, `unit` | decimal + string | proposal quantity or actually used, respectively |
| `baseline_description` | string | functional substitution assumption |
| `avoided_production_kgco2e` | decimal/null | result or unknown |
| `additional_transport_kgco2e` | decimal/null | result or unknown |
| `additional_processing_kgco2e` | decimal/null | result or unknown |
| `net_avoided_kgco2e` | decimal/null | only non-null if required components defined |
| `factor_ids` | array of FK strings | trace versioned factor rows |
| `assumptions` | object | distance, transport mode, mass, boundaries, omissions; actual moved quantity and allocation of transport/handling costs if different from used quantity |
| `calculation_status` | enum | `DEMO`, `PRELIMINARY`, `INSUFFICIENT_DATA`, `REVIEWED` |
| `calculated_at` | timestamp | <= seed baseline for seeded history |

Do not sum forecast and actual for the same underlying material. The transfer actual-use assessment is authoritative for confirmed-reuse display. **Environmental estimates are never carbon-credit balances**.

`quantity_assessed` defines production substitution. Current runtime freight and loading/unloading handling use full moved quantity even during partial use. Unknown component inputs keep net null. Seed assessments remain unchanged. Runtime immutable revisions use ImpactAssessmentHead to select one current assessment per scope, with pending/failed refreshes excluded from current reporting. Original forecasts remain separate from actual use and chosen-quantity execution forecasts.


## Runtime and provider-only records

| Record | Contract |
|---|---|
| IngestionBatch/IngestionRevision | Typed provisional batch JSON and immutable revisions; source submissions/context, isolated comparisons, working review, file resolutions and approvals. CAS protects edits. |
| Original source store | Private content-addressed original bytes and checkpoints referenced by metadata/hash; a multi-project upload is not forced into one operational document FK. |
| Model preference/usage ledger | Private local configuration and accounting, separate from inventory and human approval; exact model/slot selection, estimated/uncertain usage and provenance. |
| OperationalVersion | GLOBAL guard revision shared by participating operational transactions. |
| QuantityEncoding | Persisted exact-wire marker; initialisation requires empty legacy operational data. |
| ProjectMaterialRecord | Immutable approved document/manual contribution with project/material, original/reviewed payload, meaning, treatment, timing, quantity/unit and source. |
| SupersededRecord | Exact predecessor→successor relation; earlier evidence remains readable but has no active effect. |
| ProjectStockHead | Confirmed scope/member state and dispatch baseline; a stock head is not another additive observation. |
| IngestionPublication | Unique batch publication/key/fingerprint, receipt, resolved IDs, approved snapshot and durable matching handoff. |
| RegisteredMaterial | Historical JSON registration compatibility. New reviewed materials use Material with open-ended categories/units; do not silently promote/duplicate old identities. |
| MatchingScope/MatchingGeneration | Per-material pending/failed/current scope and immutable same-input three-objective alternatives, dependencies/day and current generation. |
| RuntimeAudit | Confirmed project/master/carbon-input correction with basis and before/after values. Association alone does not change project masters. |
| TransferWorkflowOperation | Command identity/fingerprint and replay-safe lifecycle effects; confirmation events retain original/chosen quantity and forecast. |
| ImpactAssessmentHead | Current revision per forecast/actual scope; old immutable assessments remain available. |
| ImpactRefreshIntent | Transfer-keyed token/status/payload, atomically enqueued with use/applicable corrections; calculation failure does not undo physical facts. |
| WorkspaceIdentity | Dataset epoch; prevents cross-workspace replay of commands and recommendations. |
| Archive manifests | Private ordered table/source backups with encoding, revisions, counts and checksums; read-only historical evidence, not a live operational fallback. |

## Relationship and write boundaries

```text
project/material → source observations → effective reviewed contributions
                                  ↘ confirmed released offer / validated demand
current generation → run/proposal → transfer → physical events / actual-use assessment
batch → immutable review/source history → one publication receipt → matching intent
```

A publication transaction resolves approved proposal IDs, writes contributions/supersession/heads, new catalogue/master facts, validated offer/demand projections, audit and handoff together. Partial batch writes are forbidden. Legacy registered materials remain readable; embedded JSON references receive explicit service validation.

New transfers use one confirm/reserve operation rather than request→approve→reserve. REQUESTED/APPROVED remain historical compatibility states. Partial/repeated use consumes the received remainder; unused received quantities stay committed. Head/intent/source checks select current actual-impact revisions without rewriting old results.

## Unit and carbon consistency

Aliases such as m³/m3 and pieces/pcs normalise without changing source text. Genuine unit conversion requires a product-specific confirmed basis. Production/handling factors must use kgCO2e per catalogue unit or a valid explicit mass basis; freight uses kgCO2e/t-km. An incompatible per-piece factor cannot silently become per-kg for a metre/kg material.

Factor/source snapshots, calculation_policy_version and source/head revisions preserve assessment provenance. Pending/failed actual refreshes exclude older results from current reports/exports. A completed calculation can still be INSUFFICIENT_DATA.

Schema sources: [shared registry](../terra/contract.py), [quantity codec](../terra/quantities.py), [generated schema](../dataconnect/schema/schema.gql), [analysis DTOs](../backend/app/schemas/analysis.py), [review DTOs](../backend/app/schemas/review.py).
