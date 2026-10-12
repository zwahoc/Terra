# CircularFlow — Proposed Data Structures

> Archived historical source. The original v0.1 content below is preserved for lineage, not current implementation instructions. Terra Documents 00–08 supersede conflicting schema/workflow details; [Document 09](../docs/09_ARCHITECTURE_UPDATE.md) is authoritative for architecture. UUID defaults, account/role identities, incomplete transfer quantities and old routes below are superseded. Use [Document 02](../docs/02_DATA_MODEL_CONTRACT.md) and [Document 08](../docs/08_MODULE_INTERFACES.md) for the current contracts.

**Technical reference | Draft v0.1 | 12 October 2026**  
**Status:** Proposed hackathon design, **not** Sime Darby Property's actual database or an exposed Pantas schema.

## A. First, recognise five different kinds of construction data

| Term | Meaning | Example | Can an optimiser reserve it? |
|---|---|---|---|
| **BOQ / estimated requirement** | Material anticipated by a design or cost estimate | 2,000 paving blocks planned | **No** — not proof stock exists |
| **Purchase order (PO)** | Material ordered from a supplier | 1,800 paving blocks ordered | **No** — not proof delivered or surplus |
| **Inventory / stock** | Items recorded as physically held | 500 unused blocks on site | **Not until released as surplus** |
| **Potential surplus** | Material that *may* remain unused, forecast or inferred | Expected 300 extra blocks next week | **Suggest only**, pending confirmation |
| **Confirmed surplus offer** | Material counted, permitted for reuse, with source-project approval | 250 blocks available 25 Oct | **Yes**, subject to receiving-project checks and reservation |

A document row must be tagged with its source type (`BOQ`, `PO`, `INVENTORY`, `DEMAND`, etc.). LLM extraction should **never** silently turn BOQ quantities into available supply.

## B. Proposed logical data model

Here are **12 key entities** for a coherent first prototype. These are logical tables; you can adjust their physical implementation. Suggested PostgreSQL types are shown.

### 1. `projects`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | Internal identifier |
| `code` | TEXT, UNIQUE | e.g. `ELM-A` |
| `name` | TEXT | Project display name |
| `township` | TEXT | e.g. `City of Elmina` |
| `location_lat`, `location_lon` | DECIMAL, nullable | Optional centroid; use route-specific estimates for carbon calculation |
| `status` | ENUM | `ACTIVE`, `COMPLETED` |
| `managing_organisation` | TEXT | May differ from material's legal owner |

### 2. `documents`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `project_id` | UUID, FK → projects | |
| `document_type` | ENUM | `BOQ`, `PURCHASE_ORDER`, `INVENTORY`, `DEMAND`, `OTHER` |
| `filename` | TEXT | Original filename |
| `file_hash` | TEXT | Deduplication / traceability |
| `uploaded_by` | UUID / TEXT | Authenticated user in production |
| `uploaded_at` | TIMESTAMP | |
| `processing_status` | ENUM | `QUEUED`, `PROCESSED`, `FAILED`, `REVIEWED` |

### 3. `extracted_rows`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `document_id` | UUID, FK → documents | |
| `source_locator` | TEXT | Spreadsheet tab + row, or PDF page/table |
| `raw_description` | TEXT | Preserve original words |
| `parsed_fields` | JSONB | Extracted name, quantity, unit, specs, dates |
| `confidence_score` | DECIMAL, nullable | AI's indicative confidence, **not** scientific calibration |
| `review_status` | ENUM | `PENDING`, `ACCEPTED`, `CORRECTED`, `REJECTED` |
| `reviewed_by`, `reviewed_at` | TEXT / TIMESTAMP | Audit provenance |

### 4. `materials` (canonical material catalogue)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | e.g. `MAT-PAVER-001` |
| `category` | TEXT | `PAVING_BLOCK`, `TILE`, `BRICK` |
| `canonical_name` | TEXT | `Concrete paving block` |
| `specifications` | JSONB | Standardised dimensions, colour, grade, finish, etc. |
| `standard_unit` | TEXT | e.g. `pcs` |
| `mass_kg_per_unit` | DECIMAL, nullable | Only if backed by defensible estimate/spec |
| `reference_code` | TEXT, nullable | Product/material code if available |

**Matching principle:** AI may suggest equivalent descriptions, but **deterministic constraints** decide whether critical dimensions, grades, units and other required specifications agree. Matching is not based on text similarity alone.

### 5. `supply_offers`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `source_project_id` | UUID, FK → projects | |
| `material_id` | UUID, FK → materials | |
| `origin_document_row_id` | UUID, FK → extracted_rows, nullable | Traceable input |
| `declared_quantity` | DECIMAL | Value extracted/entered |
| `confirmed_quantity` | DECIMAL, nullable | Null until verified |
| `reserved_active_quantity` | DECIMAL | Quantity currently reserved but not transferred |
| `transferred_out_quantity` | DECIMAL | Quantity dispatched/completed |
| `unit` | TEXT | Canonical unit |
| `surplus_status` | ENUM | `POTENTIAL`, `CONFIRMED`, `SUSPENDED`, `CLOSED` |
| `condition` | ENUM | `UNUSED`, `RECOVERED`, `UNKNOWN` |
| `available_from`, `available_until` | DATE | Release/expiry window |
| `material_owner` | TEXT | Ownership/authority for release |
| `batch_or_lot_code` | TEXT, nullable | Batch traceability |
| `evidence_refs` | JSONB | Documents/photos/inspection references |

**Reservable quantity** = `confirmed_quantity − reserved_active_quantity − transferred_out_quantity`, floored at zero. Only `CONFIRMED` offers may be reserved. Updates must be performed in a single database transaction to avoid double booking.

### 6. `demand_requests`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `destination_project_id` | UUID, FK → projects | |
| `material_id` | UUID, FK → materials | |
| `required_quantity`, `fulfilled_quantity` | DECIMAL | Separate total need from satisfied need |
| `unit` | TEXT | |
| `needed_from`, `required_by` | DATE | Delivery window |
| `request_status` | ENUM | `OPEN`, `FULFILLED`, `CANCELLED` |
| `origin_document_row_id` | UUID, nullable | Traceable input |

### 7. `optimisation_runs`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `created_at` | TIMESTAMP | |
| `objective` | ENUM | `MAX_REUSE`, `MAX_NET_CO2E_AVOIDED`, `EARLIEST_DEADLINE` |
| `inputs_snapshot_hash` | TEXT | Identifies exact inputs used |
| `factor_dataset_version` | TEXT | Reproducibility |
| `solver_status` | ENUM | `SUCCEEDED`, `FAILED`, `INFEASIBLE` |
| `assumptions` | JSONB | Constraints, transport distances, missing-factor handling |

### 8. `allocation_proposals`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `run_id` | UUID, FK → optimisation_runs | |
| `supply_offer_id` | UUID, FK → supply_offers | |
| `demand_request_id` | UUID, FK → demand_requests | |
| `proposed_quantity` | DECIMAL | |
| `unit` | TEXT | |
| `compatibility_result` | ENUM | `ELIGIBLE`, `REVIEW_REQUIRED`, `INELIGIBLE` |
| `status` | ENUM | `PROPOSED`, `SELECTED`, `REJECTED`, `EXPIRED` |
| `reason_codes` | JSONB | Explain why matched or rejected |

Proposals are **not** stock reservations; approving one must create a reservation atomically.

### 9. `transfers`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `proposal_id` | UUID, FK → allocation_proposals | |
| `approved_quantity`, `received_quantity`, `actually_used_quantity` | DECIMAL | Three distinct quantities |
| `status` | ENUM | `REQUESTED`, `APPROVED`, `RESERVED`, `IN_TRANSIT`, `RECEIVED`, `REUSED`, `CANCELLED` |
| `source_approved_by`, `destination_approved_by` | TEXT / UUID | Approval responsibilities |
| `delivered_at`, `reuse_confirmed_at` | TIMESTAMP, nullable | |

**Don't call stock “reused” at `RESERVED` or `RECEIVED`.** Count only `actually_used_quantity` after confirmation.

### 10. `transfer_events`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `transfer_id` | UUID, FK → transfers | |
| `event_type` | ENUM | `APPROVED`, `RESERVED`, `DISPATCHED`, `RECEIVED`, `USED`, `CANCELLED` |
| `actor`, `occurred_at` | TEXT / TIMESTAMP | Who did what, when |
| `evidence_ref`, `payload` | TEXT / JSONB | Proof and quantity changes |

### 11. `emission_factors`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `factor_type` | ENUM | `NEW_MATERIAL_PRODUCTION`, `TRANSPORT`, `PROCESSING`, `OTHER` |
| `material_id` | UUID, nullable | Factor may apply to material or transport mode |
| `value` | DECIMAL | Numerical factor |
| `unit` | TEXT | e.g. `kgCO2e/pcs`, `kgCO2e/kg`, `kgCO2e/t-km` |
| `source`, `source_url` | TEXT | Traceable dataset/publication |
| `geography`, `lifecycle_boundary` | TEXT | Critical for sound interpretation |
| `version`, `valid_from` | TEXT / DATE | Reproducibility |
| `is_demo_factor` | BOOLEAN | Prevent hypothetical numbers being presented as factual |

### 12. `impact_assessments`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `proposal_id` or `transfer_id` | UUID, FK | Proposal = *forecast*, transfer = *post-reuse estimate* |
| `baseline_description` | TEXT | e.g. new procurement of functionally equivalent material |
| `avoided_production_kgco2e` | DECIMAL | Calculated estimate |
| `additional_transport_kgco2e` | DECIMAL | Calculated estimate |
| `additional_processing_kgco2e` | DECIMAL | Calculated estimate |
| `net_avoided_kgco2e` | DECIMAL | Derived amount |
| `factor_ids`, `assumptions` | JSONB | Full inputs and caveats |
| `calculation_status` | ENUM | `DEMO`, `PRELIMINARY`, `REVIEWED` |
| `calculated_at` | TIMESTAMP | |

Do **not** model `carbon_credits` as automatically earned. Avoided-emissions estimates ≠ issued carbon credits and should not be silently netted against corporate scope inventories.

**Cross-cutting:** add application users/roles and project-level permissions once the core flow works. For a production solution, user/organisation tables and access policies are required.

## C. Relationships at a glance

```text
projects 1 ─── N documents 1 ─── N extracted_rows
projects 1 ─── N supply_offers N ─── 1 materials
projects 1 ─── N demand_requests N ─── 1 materials
optimisation_runs 1 ─── N allocation_proposals
supply_offers 1 ─── N allocation_proposals N ─── 1 demand_requests
allocation_proposals 1 ─── 0..1 transfers 1 ─── N transfer_events
allocation_proposals / transfers 1 ─── N impact_assessments
impact_assessments N ─── N emission_factors (via referenced factor IDs)
```

## D. Example normalised records (ILLUSTRATIVE ONLY)

**Example extracted row:**

```json
{
  "document_id": "DOC-001",
  "document_type": "INVENTORY",
  "source_locator": "Sheet: Stock, Row: 12",
  "raw_description": "GREY RECT PAVER 200X100X60",
  "parsed_fields": {
    "canonical_material": "concrete_paver_200x100x60_grey",
    "quantity": 1000,
    "unit": "pcs",
    "dimensions_mm": {"length": 200, "width": 100, "thickness": 60},
    "condition": "unused"
  },
  "confidence_score": 0.93,
  "review_status": "PENDING"
}
```

**Example confirmed surplus:**

```json
{
  "id": "SUP-A-001",
  "source_project_id": "ELM-A",
  "material_id": "MAT-PAVER-001",
  "declared_quantity": 1000,
  "confirmed_quantity": 1000,
  "reserved_active_quantity": 0,
  "transferred_out_quantity": 0,
  "unit": "pcs",
  "surplus_status": "CONFIRMED",
  "available_from": "2026-10-20",
  "condition": "UNUSED",
  "material_owner": "Demo contractor A"
}
```

**Example demand:**

```json
{
  "id": "DEM-B-001",
  "destination_project_id": "BBR-B",
  "material_id": "MAT-PAVER-001",
  "required_quantity": 600,
  "fulfilled_quantity": 0,
  "unit": "pcs",
  "needed_from": "2026-10-25",
  "required_by": "2026-10-30",
  "request_status": "OPEN"
}
```

## E. Proposed API boundaries (not mandatory implementation)

| Route | Producer / user | Purpose |
|---|---|---|
| `POST /documents` | AI module | Upload / register file |
| `GET /documents/{id}/rows` | Frontend | Show extracted rows with source references |
| `PATCH /extracted-rows/{id}` | Frontend → AI review | Correct and accept extraction |
| `GET /supply-offers`, `GET /demand-requests` | Frontend | Browse existing supply and demand |
| `POST /optimisation-runs` | Optimisation | Generate proposals for chosen objective |
| `GET /optimisation-runs/{id}/proposals` | Frontend | Show proposed allocations |
| `POST /allocation-proposals/{id}/reserve` | Transfer | Atomic stock reservation after required checks |
| `POST /transfers/{id}/confirm-receipt` | Transfer | Record received quantity |
| `POST /transfers/{id}/confirm-use` | Transfer | Record actual quantity reused |
| `GET /exports/circularity?format=csv` | ESG | Export reviewed circularity results |

## F. Non-negotiable data rules

1. **Provenance:** every AI-extracted claim should link to the original document and row/page.
2. **Units:** never compare `pcs`, `m²`, `kg` or `tonnes` without an explicit conversion basis.
3. **Matching:** material name similarity is a hint, **not** sufficient proof of specification compatibility.
4. **Supply:** potential or unconfirmed stock must not be reservable.
5. **No double allocation:** one unit of confirmed stock cannot be reserved for two receivers.
6. **Dates:** supply availability must fit demand dates, or be explicitly flagged for review.
7. **Accounting:** `proposed`, `reserved`, `received`, and `actually used` are different metrics.
8. **Emissions:** every factor and baseline needs source, units, boundary and version.
9. **Audit:** don't erase transfer approval/reuse events; append corrective events if needed.
10. **Pantas:** export environmental data for a possible approved integration; do not imply a live link exists.

## G. Public datasets / structures worth reviewing

These are **real external references**, not proof of SDP's internal data formats or actual usable surplus.

- Construction resource descriptions and work items: [OpenConstructionEstimate — DDC-CWICR](https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR). Check licensing and usage permissions.
- IFC/BIM data structure: [buildingSMART IFC4.x specification models](https://github.com/buildingSMART/IFC4.x-specification-models).
- Real road-construction bid item descriptions/quantities: [Caltrans contract cost database](https://sv08data.dot.ca.gov/).
- Building-material environmental impact datasets: [ÖKOBAUDAT downloads](https://www.oekobaudat.de/en/service/downloads.html). Methodology and geography may not fit Malaysia without adjustments.
- Transport GHG factors: [UK Government conversion factors](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025). Confirm valid factor for the vehicle and declared boundaries.

**Suggested study order:** distinguish source document types → examine materials/supply/demand → examine proposals/transfers → examine emissions factors. This is a reading reference, not a team agenda.
