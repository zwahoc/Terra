# 02 — Canonical logical data model for Terra

**Scope:** Proposed logical **relational** contract for an MVP, written independently of Firebase. This is a revised and expanded version of `legacy/CircularFlow_Data_Model_v0.1.md`. It is **not** a deployed schema, SQL DDL or a representation of actual SDP/Pantas fields.

**Application ownership:** React/TypeScript/Tailwind consumes FastAPI DTOs. Independent Python services own business calculations and transitions; repositories use a Python SQL Connect REST adapter to the PostgreSQL-backed Firebase service. Named administrative reads/writes are verified on the local emulator; cloud authentication/read-write validation remains pending. Node.js may support Firebase tooling or a justified one-off utility, never a second application backend. Provider-neutral field meanings below do not authorize a generic PostgreSQL or Supabase integration.

## 1. General conventions

- Dataset JSON: top-level arrays named `snake_case` (listed below), each row has `id: String` with readable stable IDs. FKs are **string IDs** from parent arrays; never store only display names as FK.
- Database: PostgreSQL via Firebase SQL Connect. `.gql` uses camelCase field identifiers, mapped to SQL column names as needed; see architecture reference. Use explicit primary-key `String` where supported, not default implicit UUID keys.
- Numeric quantities and factor values are nonnegative exact decimals in application validators; calculated net avoided emissions can be negative if reuse impacts exceed avoided production. Avoid binary floating-point for quantity math and financial figures. For sample whole-unit `pcs`, quantities are integers. JSON numeric representation plus unit string; validate precision in DB/application.
- Dates: `YYYY-MM-DD`; timestamps: RFC3339 `2026-10-07T14:30:00+08:00`. `null` ≠ `0`; factor unknown stays `null`.
- Units: canonical unit `pcs` for the starter material catalogue; mass `kg` (per item), distance `km`, emissions `kgCO2e`, optionally money `MYR` where used.
- Seed metadata: `metadata.dataset_name`, `version`, `as_of_date: "2026-10-12"`, `synthetic: true`, `timezone: "Asia/Kuala_Lumpur"`, `currency: "MYR"`, `carbon_unit: "kgCO2e"`, `disclaimer`, matching Document 03.
- Mutable counters on `supply_offers` / `demand_requests` are cached projections of transfer state. Reconcile and validate against transfer records so they never drift.
- Every table's ID must be stable across repeat imports. `created_at`/`updated_at` may be added consistently where useful, but no `created_by`, `approved_by_user_id`, `user_id`, `role_id` or `auth_uid`.

## 2. Tables: names, core fields and constraints

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
| `category` | enum | `PAVING_BLOCK`, `BRICK`, `TILE` |
| `canonical_name` | string | specific material/spec name |
| `specifications` | object | typed dictionary: dimensions in `*_mm`; grade/type/colour/finish where relevant |
| `standard_unit` | enum | MVP `pcs` |
| `mass_kg_per_unit` | decimal/null | numeric only if explicitly demo-estimated or sourced |
| `mass_source` | string/null | `SYNTHETIC_ASSUMPTION` or named source; not invented verified weight |
| `reference_code` | string/null | example SKU, not real manufacturer certification |
| `is_synthetic` | bool | true in demo |

Catalogue uniqueness must combine category + identifying specs (not name alone). Different thickness/grade/size => different SKUs.

### `documents` — 12–15 **metadata-only** records

| Field | Type | Constraint / semantics |
|---|---|---|
| `id` | string PK | `DOC-001` |
| `project_id` | string FK | `projects.id` |
| `document_type` | enum | `BOQ`, `PURCHASE_ORDER`, `INVENTORY`, `DEMAND`, `OTHER` |
| `display_filename` | string | `example_project_inventory.xlsx` synthetic label |
| `file_uri` | string/null | **null until a real test fixture is provided** |
| `file_hash` | string/null | **null**, don't forge SHA values for absent files |
| `source_availability` | enum | `METADATA_ONLY`, later `FILE_AVAILABLE` |
| `processing_status` | enum | `SIMULATED`, later `QUEUED`, `PROCESSED`, `FAILED`, `REVIEWED` |
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

The seed retains BOQ, PO and on-hand facts in reviewed extraction rows; it does not introduce a separate procurement or inventory ledger. Deterministic Python services can calculate potential surplus/outstanding need only from sufficient documented inputs. These calculations and accepted row status do not confirm releasable stock. Real-ingestion review modes and richer reconciliation are future contract items in Document 07.

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

For planning, subtract not only fulfilled quantity but **active incoming committed** transfers, established at reservation and retained until use or explicit resolution. A requested transfer created by proposal approval does not hold demand. `APPROVED` is retained only for historical seed compatibility and likewise does not hold demand. Seed `fulfilled_quantity` reconciles to transfer actual-use quantities; `FULFILLED` requires `fulfilled_quantity=required_quantity`. Alternative procurement fulfilment records are outside this seed model. Cancelled demands are not available for fresh allocations; cancellation must not silently discard an active incoming commitment.

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

`reserved + dispatched <= approved`. No `approved_by_user_id` or auth FK. For a terminal `REUSED` record, actual usage must be positive; no claim of real operator verification in synthetic seed. The flow may include partial deliveries/usages; dashboard aggregates actual-use quantities only.

Selection, request and approval alone have no stock/demand commitment effect. Successful reservation atomically establishes both commitments; dispatch moves units from reservation to transferred-out exactly once. For partial reuse, residual quantities require explicit disposition before an incoming commitment is released. The current fields do not fully specify partial-transfer closure; see Document 07. A historical terminal fixture must document that resolution, and cannot imply missing units were returned to source stock.

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

`quantity_assessed` defines production substitution, not automatically freight quantity. Undefined partial-use cost allocation means `INSUFFICIENT_DATA`. For the seed, use one assessment per proposal/basis or transfer/basis so dashboard values cannot double-count revisions. Revision selection for later recalculation requires a contract decision; the relationship map permits history but does not define a revision selector.

## 3. Relationship map

```text
projects 1--N documents 1--N extracted_rows
projects 1--N supply_offers N--1 materials
projects 1--N demand_requests N--1 materials
projects 1--N route_distances (both endpoints)
extracted_rows 1--0..N supply_offers / demand_requests (optional provenance)
optimisation_runs 1--N allocation_proposals
supply_offers 1--N allocation_proposals N--1 demand_requests
allocation_proposals 1--0..1 transfers 1--N transfer_events
allocation_proposals 1--N impact_assessments (forecast)
transfers 1--N impact_assessments (actual, revisioned)
impact_assessments N--N emission_factors (via factor ID array for MVP)
```

Because `factor_ids` is an array for MVP, Codex may normalise it into an `assessment_factors` join table if required by the provider. Keep external JSON contract stable and document the mapping. No `users` FK anywhere.

## 4. Example: linked records (minimal only, not a seed)

```json
{
  "supply_offers": [{
    "id": "SUP-001", "source_project_id": "PRJ-001", "material_id": "MAT-001",
    "declared_quantity": 1000, "confirmed_quantity": 1000,
    "reserved_active_quantity": 400, "transferred_out_quantity": 200,
    "unit": "pcs", "surplus_status": "CONFIRMED", "condition": "UNUSED",
    "available_from": "2026-10-01", "available_until": null,
    "origin_document_row_id": null, "batch_or_lot_code": "DEMO-LOT-001"
  }],
  "demand_requests": [{
    "id": "DEM-001", "destination_project_id": "PRJ-002", "material_id": "MAT-001",
    "required_quantity": 600, "fulfilled_quantity": 200, "unit": "pcs",
    "needed_from": "2026-10-01", "required_by": "2026-10-20",
    "request_status": "OPEN", "is_outstanding_need_confirmed": true
  }]
}
```

This short excerpt only illustrates FK names and counter semantics; its counters **cannot be validated alone** without corresponding transfer records. The eventual complete seed MUST reconcile all counters against those records.

## 5. The six highest-risk invariants

1. No orphan FK; no missing enum values; no repeated PK; no self-project source-to-destination allocations.
2. Source available stock never negative: `confirmed >= active_reserved + dispatched`.
3. Recipient unmet **uncommitted** demand never negative: `required >= fulfilled + unfulfilled_active_incoming_commitment`.
4. `actually_used <= received <= dispatched <= approved <= proposed` and event chronology/status agree.
5. Units, dimensions and mass factor match the assessed material or have documented conversion.
6. Forecast-impact records are never aggregated with actual-use records as if both occurred.

See `03_SEED_DATABASE_SPEC.md` for exact dataset cases and `06_REQUIREMENTS_AND_TESTS.md` for validator checks.
