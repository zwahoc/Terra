# 03 — Option B fully populated synthetic seed: generation and verification specification

**This is the contract for a separately requested first implementation task.** It describes the **data that must be generated**, not the actual final seed. The earlier documentation review did not generate data, schemas or tooling. The owner has since authorized the local seed milestone; observed results are recorded in SEED_VALIDATION.md. Do not confuse this specification with the four-project, one-material legacy example.

## 1. Output

Generate `terra_seed.json` as the portable single source of truth, plus Firebase SQL Connect schema/connectors, database importer, validator, setup docs and tests. Use the tables and fields in `02_DATA_MODEL_CONTRACT.md`. All references must resolve within the JSON; no post-import manual patching. The JSON must be valid and directly consumable by explicit offline frontend mock adapters or an import script. In the eventual application, React/TypeScript/Tailwind uses FastAPI for all application reads and writes; Python services own business logic and use a repository/Python REST adapter for Firebase SQL Connect backed by PostgreSQL.

Prefer Python import/read-back tooling after a minimal REST authentication/connectivity proof. A justified one-off Node Admin CLI is allowed where essential; no persistent Node backend, direct-SQL fallback or full FastAPI API belongs in this milestone. Document blocked adapter steps rather than claim Node tooling proves Python integration.

**As-of date:** `2026-10-12`; timezone `Asia/Kuala_Lumpur`; synthetic `true`. Historical `created_at`, events, completed transfers and environmental assessments must be dated **no later than 2026-10-12**. Future supply availability and demand deadlines are fine, but must not be counted as historical transfers.

```json
{
  "metadata": {
    "dataset_name": "Terra Option B Synthetic Baseline",
    "version": "1.0.0",
    "as_of_date": "2026-10-12",
    "timezone": "Asia/Kuala_Lumpur",
    "synthetic": true,
    "currency": "MYR",
    "carbon_unit": "kgCO2e",
    "disclaimer": "Synthetic demonstration data; not actual SDP project inventories or verified GHG factors."
  },
  "projects": [], "materials": [], "documents": [], "extracted_rows": [],
  "supply_offers": [], "demand_requests": [], "route_distances": [],
  "optimisation_runs": [], "allocation_proposals": [],
  "transfers": [], "transfer_events": [],
  "emission_factors": [], "impact_assessments": []
}
```

No `users`, `roles`, `sessions`, `accounts`, `permissions`, `organisations` auth tables, `carbon_credits` or `pantas_integrations` pretending a live relationship.

## 2. Exact target sizes

| Array | Target | Requirements |
|---|---:|---|
| `projects` | **5** | Fictional projects at distinct Malaysian SDP-style locations |
| `materials` | **20** | Distinct specifications across 3 categories; not 20 aliases for 1 item |
| `documents` | **12–15** | Metadata only, no real files or hashes; include BOQ, PO, inventory, demand |
| `extracted_rows` | **40–60** | Simulated messy source descriptions, varied review confidence/statuses |
| `supply_offers` | **20–25** | confirmed, potential, suspended, closed; varying quantities/dates |
| `demand_requests` | **20–25** | open, fulfilled and cancelled; varying requirements/dates |
| `route_distances` | **10** | complete 5-choose-2 pairs, synthetic symmetric distances |
| `optimisation_runs` | **3–5** | distinct objective types, input snapshot version/hash |
| `allocation_proposals` | **10–15** | eligible, review-required, rejected/ineligible, selected, expired |
| `transfers` | **5–8** | requested/approved/reserved/in-transit/received/reused/cancelled represented sensibly |
| `transfer_events` | **15–25** | exactly sufficient histories explaining persisted transfer states |
| `emission_factors` | **6–10** | production, freight and handling; deliberately incomplete coverage |
| `impact_assessments` | **5–10** | forecasts, actual-use estimates, missing data and carbon comparisons |

**If the constraints conflict** (e.g., one event per transition exceeds 25), prefer complete internally consistent transaction histories over a numeric range, and explain the deviation. No filler data created solely to hit a count.

## 3. Seed geography and identity

Use fictional site names clearly prefixed or suffixed `Demo`, e.g. `Elmina Demo Phase A`, `Bukit Raja Demo Phase B`, `Serenia Demo C`, `Nilai Impian Demo D`, `Putra Heights Demo E`. Real-world township names are location context, **not evidence those projects/inventories exist**. Project IDs `PRJ-001`...`PRJ-005`, all persistent and human-readable.

For route distances, create 10 unordered pairs with plausible fictional Malaysian road distances. Store `assumption_type=SIMULATED_ROAD_DISTANCE`; do **not** claim these are live Google Maps distances, actual truck routes, or project addresses. The route matrix should enable a genuinely nearer/lower-transport alternative.

## 4. Material catalogue blueprint: 20 distinct specifications

Exact SKU descriptions can be chosen by Codex, but include **at least**:

- **8 paving blocks:** 200×100×60 and 200×100×80 in grey/red; other distinct thickness, shape/finish and spec variations.
- **6 bricks:** clay and concrete types with different dimensions; some relevant strength/grade differences.
- **6 tiles:** 300×300, 600×600 and 300×600 ceramic floor/wall tiles; different finishes/colours and at least one explicit unsuitable floor/wall or slip-rated match.

A category type and thickness change should have different `material_id`s even if free-text names are similar. Include `mass_kg_per_unit` with synthetic source when needed for calculations; reserve some with unknown mass to exercise `INSUFFICIENT_DATA`.

Use descriptive test aliases **in `extracted_rows.raw_description` only**, rather than building noncanonical duplicate materials. Example equivalent surface forms:

- `GREY RECT CONC PAVER 200X100X60`; `Concrete paving block, grey, 200 × 100 × 60 mm`.
- `CER FLR TILE 600*600 MATT`; `600x600 ceramic floor tiles matte`.
- `RED CLAY BRICK (spec grade here)`; avoid asserting unverifiable manufacturer grades.

## 5. Construction document and extraction fixtures (no actual files yet)

`documents` must have meaningful *synthetic* metadata, e.g. `PRJ-001_INVENTORY_DEMO.xlsx`, but `file_uri=null`, `file_hash=null`, `source_availability=METADATA_ONLY`, `processing_status=SIMULATED`, `is_simulated=true`. Nothing may depend on a nonexistent disk file, network URL or remote storage blob.

`extracted_rows` should show:

- rows confidently mapped to existing materials with canonical units;
- low-confidence or pending mappings;
- one or more corrected records (retain original source text);
- rejected rows (ambiguous or wrong unit/spec);
- **BOQ/PO rows that do not create surplus**;
- inventory rows that remain `ON_HAND_INVENTORY` until a separate surplus verification;
- explicit accepted demand rows only when an outstanding need is confirmed;
- source locators like `Sheet: DemoStock, Row: 9` **marked synthetic**.

To facilitate future Member 2 ingestion, retain raw name and raw quantity strings, parsed canonical values, source type and candidate material ID; map `origin_document_row_id` only for rows whose status and meaning justify a supply/demand. `PENDING` rows must **never** create confirmed supply.

## 6. Required carefully constructed operational scenarios

Each scenario below must be reproducible via known IDs. The generated README should include a **scenario index** mapping narrative to exact `PRJ`, `MAT`, `SUP`, `DEM`, `ALC`, `TRF` IDs.

| ID | Data fixture scenario | What it must prove |
|---|---|---|
| S01 | Exact same-spec paver supply and demand in different projects | at least one feasible allocation |
| S02 | Variant descriptions referencing one material ID | normalization without duplicate catalogue records |
| S03 | Similar tile descriptions but mismatched thickness/dimensions/grade | matching rejected or `REVIEW_REQUIRED`, never silently eligible |
| S04 | One confirmed offer serving two other projects | combined quantities in one plan <= snapshot reservable stock; live holds/dispatches reconcile to confirmed stock |
| S05 | Competing offers: same eligible material, one short route and one longer route | carbon-aware comparison can prefer one route |
| S06 | Forecast potential surplus with non-null declared quantity | cannot reserve; do not populate confirmed quantity |
| S07 | Supply release after recipient's required-by deadline | ineligible due to date |
| S08 | Source has a partially reserved quantity | current reservable derived exactly and no double booking |
| S09 | Historical complete transfer with actual use less than proposed/received | only actual used contributes confirmed reuse |
| S10 | Reserved / in-transit / received-but-not-used transfers | committed stock vs confirmed ESG impact separated |
| S11 | Rejected / expired historical proposal | has zero stock impact |
| S12 | Material with missing mass / relevant factor | valid operational match but incomplete carbon assessment |
| S13 | BOQ planned quantity or PO ordered amount | neither is released surplus; no automatic demand confirmation |
| S14 | Existing fulfilled and cancelled demands | their fulfilled amounts and statuses cannot create fresh demand |
| S15 | Alternative optimisation runs with same input snapshot but different objectives | feasible alternatives are **not** summed as if executed |

**Recommended intentional relationships** (not fixed IDs): choose one paver SKU present at 3 sites and demanded by 2 others; choose a separate tile SKU with near-matching but incompatible attributes; choose a brick SKU with no relevant production factor; choose some older demands/transfers fulfilled before the as-of date.

**Important chronology:** The legacy scenario's `2026-10-20` future supply cannot be used to assert a transfer was completed before seed date `2026-10-12`. Either keep those as future proposals, or use separate earlier-dated confirmed offers for historical transfers.

## 7. Stock and demand consistency definition

### Source-side (verified inventory)

Each confirmed supply offer:

`remaining_reservable = confirmed_quantity - reserved_active_quantity - transferred_out_quantity`.

Required: `0 <= reserved_active_quantity + transferred_out_quantity <= confirmed_quantity` (with per-unit precision). Active reservations equal the sum of currently active transfer hold quantities for that supply; transferred-out equals historical/current cumulative dispatched quantities. The baseline models no return transactions. A later return/reversal contract must account for them explicitly rather than silently restock on cancellation.

### Destination-side (outstanding need)

`remaining_unfulfilled = required_quantity - fulfilled_quantity`.

`newly_allocatable_demand = max(0, required_quantity - fulfilled_quantity - active_incoming_commitments)`.

Active incoming commitments begin at successful reservation and represent remaining promised quantity on existing live transfers **not yet actually used**, avoiding double allocation to the same request. Requested/approved-only transfers do not hold stock or demand. Dispatched/received units still count as promises until used or explicitly resolved. Pre-dispatch cancellation releases its commitment atomically; post-dispatch exceptions must not erase movement or unresolved promises.

Seed `fulfilled_quantity` equals actual-use quantities linked to the demand. Other procurement fulfilment is outside this model. For partial historical reuse, describe residual disposition in notes/event payloads. Do not derive commitment release solely from `REUSED`, invent a return, or silently resolve the open closure policy in Document 07.

### Transfer-side

`0 <= actually_used <= received <= dispatched <= approved <= proposal_quantity`.

`reserved + dispatched <= approved` for each transfer. Reservations cannot survive as still reserved after their units are dispatched. A completed historic transfer should ordinarily have no active reservation.

Persist all counters consistently; validator must recompute aggregate source and demand snapshots from current transfers and compare them. Do **not** count proposal quantities from multiple different alternative runs in stock commitments.

## 8. Carbon arithmetic, provenance and dashboard

Demo production factors must be clearly labelled `is_demo_factor=true`. Store factor scope/source/version/units. For each assessed allocation with unit mass `m` kg/pcs, quantity `q` pcs, route distance `d` km, transport EF `e_transport` kgCO2e/(tonne·km), material production factor `e_prod` kgCO2e/pcs:

```text
mass_t                           = q * m / 1000
avoided_new_production_kgCO2e    = q * e_prod
additional_transport_kgCO2e      = mass_t * d * e_transport
net_avoided_kgCO2e              = avoided_new_production_kgCO2e
                                   - additional_transport_kgCO2e
                                   - additional_processing_kgCO2e
```

If the material factor uses `kgCO2e/kg` instead, convert explicitly: `q * m * e_prod`. If route/mass/factor/handling boundary required by the declared assessment is unavailable, leave net `null` and label `INSUFFICIENT_DATA`; never silently use zero. Store calculation inputs and factor IDs. Baseline new procurement must actually be displaced for an avoided-production comparison to be valid.

The example assumes proposed quantity and freight quantity are equal. For an actual-use assessment, production uses confirmed used quantity while freight/handling inputs reflect the actual movement and a stated cost-allocation boundary. If less is used than moved, do not silently prorate away emissions. Until that boundary is defined, a partial-use assessment can retain known components but its net stays null. Use one assessment per entity/basis in the baseline; do not sum recalculation revisions.

For seeded dashboard fixtures calculate **from records, not hand-typed contradictory summary numbers**:

- Total confirmed material reused = sum `actually_used_quantity * mass_kg_per_unit` for actual-use transfer entries, converting to tonnes where mass known.
- Reuse project count = distinct projects involved in actual reused transfers (define whether source/receiving are included; document).
- Open demand = outstanding quantity minus commitments, grouped by material unit, never sum unlike units as one number.
- Proposed savings = forecast assessments only; actual savings = actual-use assessments only; never combine.
- Carbon records lacking inputs are reported separately as incomplete.

Recommended baseline 2+ historically completed/reused records and >0 outstanding stock/demands so overview looks alive at day one; at least one `RECEIVED` transfer with zero use to demonstrate that it doesn't boost reuse totals.

## 9. Repeatability and exports

- `terra_seed.json` is immutable/reference fixture; app runtime changes in database must not mutate the seed file.
- Import CLI supports `validate`, `dry-run`, `seed local`, `reset local` with explicit destructive confirmation, and `verify after-import`.
- Re-seeding on same database must not duplicate rows or double-apply quantity deltas; use **deterministic upsert of snapshot state**, not replay transfer events that increment counters again.
- If seeding a *nonempty, actively used* database would overwrite changes, default to refusing or offer explicit `--reset-demo` consent, not silent overwrite.
- Seed insertion order: projects/materials → docs → rows → supplies/demands/routes/factors → optimisation runs/proposals → transfers/events → impact assessments.
- The importer/read-back utility accesses Firebase through verified local tooling. The future frontend queries FastAPI; Python repositories/REST adapter access SQL Connect. Avoid divergent hardcoded JSON copies in frontend/AI modules.

## 10. Validation: minimum automated checks

1. JSON syntactically parses and metadata correct; file deterministic from known generation inputs.
2. Required arrays present and counts within agreed ranges; no `users`.
3. Unique IDs, all FKs resolve; no ambiguous project/source mappings.
4. No negative quantity or invalid unit; demand date windows valid; no impossible past/future chronology.
5. Offer counters reconcile with transfer quantities and status; demand fulfillment/active commitment reconcile; no double booking.
6. Transfer event history matches stage/status and quantities; actually used never exceeds received.
7. Incompatible/date-expired/potential supplies never appear as eligible **selected/committed** matching transfers. Historical eligibility is checked against the saved run snapshot and event time, not today's depleted stock or closed statuses; new reservations revalidate current state.
8. Every completed reuse counted exactly once; `RECEIVED` without `USED` contributes zero confirmed reuse.
9. Every net emission estimate recomputes with factor records and route assumptions; missing inputs -> null net with correct status.
10. No real-source assertion, fake Pantas integration, fake file hashes or invented verified GHG factors; all source/synthetic flags explicit.
11. The exemplar four-project legacy allocation remains a useful regression fixture but is **not** treated as already completed and not included as factual SDP data.

## 11. Files to create (suggested repository placement)

These paths describe the seed implementation, separately authorized after documentation synchronisation. See LOCAL_DEVELOPMENT.md for the implemented layout.

```text
data/terra_seed.json

dataconnect/schema/*.gql       # SQL Connect application schema, verified on emulator
dataconnect/<connector>/*.gql  # named queries/mutations
scripts/seed_terra.py          # Python importer when REST proof succeeds
scripts/validate_seed.py       # offline source-of-truth validator
scripts/check_import.py        # Python read-back checks when supported
scripts/sql_connect_probe.py   # minimal standalone REST read/write/read-back proof
README.md                      # local setup, repeatability, results and blockers
```

Codex may arrange paths to fit the actual repo and reuse the minimal proof model as a seed entity rather than introduce extra domain arrays. If a Node Admin utility is essential, document the reason and its one-off scope. No application scaffold is required. The seed remains usable without Firebase credentials for **offline validation and frontend mocking**. Report offline, emulator, Python REST and cloud results separately; cloud testing/provisioning requires explicit approval.
