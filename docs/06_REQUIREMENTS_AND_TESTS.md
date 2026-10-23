# 06 — Requirements and verification

[SRS](TERRA_SRS_v1.0.md) uses SRS-FR/SRS-NFR/SRS-BR/SRS-AT IDs. The original FR/NFR/A IDs below remain stable for traceability. Requirements and acceptance scenarios are not blanket claims of executed tests.

## Requirement priorities

P0-SEED describes the canonical fixture foundation; P0-MVP the implemented prototype's required workflow. P1/P2 are optional/future scope, not permission to start new features.

## Functional requirements

| ID | Priority | Requirement |
|---|---|---|
| FR-01 | P0-SEED | Store/list 5 synthetic distinct projects with stable IDs, names, townships and date fields from Document 02. |
| FR-02 | P0-MVP | LLM-led broad document interpretation with optional readers/preprocessing; validate actual format/model support and preserve per-file failures. No forced templates or arbitrary row cap. |
| FR-03 | P0-SEED + MVP | Distinguish BOQ, PO, inventory, demand; accepted BOQ must not become confirmed surplus. |
| FR-04 | P0-SEED + MVP | `extracted_rows` contract includes name, amount, unit, specs, dates and source locator; seeded rows are explicitly synthetic. |
| FR-05 | P0-SEED + MVP | Different raw names can map to same canonical ID; different critical specs do not map automatically. |
| FR-06 | P0-SEED + MVP | Preserve original facts, assumptions and operator edits; structured review with whole-source viewing and no compulsory written override reasons. Seed review flags remain synthetic. |
| FR-07 | P0-SEED + MVP | Every item resolved by acceptance/correction/exclusion; each file approved separately; only the fully dealt-with approved batch publishes atomically. No unreviewed or partial operational publication. |
| FR-08 | P0-SEED | Store separate confirmed/potential supply and outstanding demand, with status/quantity rules. |
| FR-09 | P0-MVP | Matching respects critical specs/units; incompatible fixture produces ineligibility. |
| FR-10 | P0-SEED + MVP | Dates and quantities consistent; no over-allocation, including recipient commitments. |
| FR-11 | P0-SEED + MVP | Support one-to-many feasible allocation with shared budgets; retain seed examples. |
| FR-12 | P0-SEED + MVP | Retain explainable saved inputs/runs/proposals and generate current deterministic plans. |
| FR-13 | P0-SEED + MVP | Compare reuse, deadline and carbon strategies on consistent inputs; do not count both as execution. |
| FR-14 | P0-SEED | Store demonstrative, explicitly labelled factor values, units and provenance. |
| FR-15 | P0-SEED + MVP | Reproduce seed and current impact results from stored inputs/factors with versioned assessment heads. |
| FR-16 | P0-MVP | Carbon-aware algorithm can rank valid alternatives, not just nearest supplier. |
| FR-17 | P0-SEED | Unknown unit mass/routes/handling/factors yield `INSUFFICIENT_DATA`, not invented emission outputs. |
| FR-18 | P0-SEED + MVP | Single-user status-based approvals (NO users/RBAC schema). Retain truthful sample states and guarded operational transitions. |
| FR-19 | P0-SEED + MVP | Source/destination counters reconcile; enforce atomic source/recipient reservation under contention. |
| FR-20 | P0-SEED | Separate dispatched, received and actually used; `RECEIVED` not automatically `REUSED`. |
| FR-21 | P0-SEED | Append-only-style transfer events and chronological history. |
| FR-22 | P0-MVP | CSV/JSON export of actual reused quantities and estimates, with Pantas disclaimers. |
| FR-23 | P0-MVP | Overview, documents/review, supply-demand/matching, transfer/ESG UI. |
| FR-24 | P0-MVP | E2E demo on synthetic projects: review → verify supply/demand → match → confirm/reserve → dispatch → receive → confirm use → export. |

## Nonfunctional requirements

| ID | Requirement |
|---|---|
| NFR-01 | Traceability: preserve source file metadata / row/page and truthful audit provenance. Local model-test provenance may live outside LLM context; no per-record synthetic labels or simulation commentary are required there. See Document 05. |
| NFR-02 | Explainable deterministic eligibility: factor, material, date and quantity decisions can be reproduced. |
| NFR-03 | Atomic stock consistency: no reservations exceeding confirmed stock or demand need. |
| NFR-04 | **Single-user adaptation:** workflow confirmations through statuses/events only; no role-based auth for MVP. Enterprise controls future. |
| NFR-05 | Unit correctness: reject invalid or ambiguous conversions; no pieces-to-tonnes without mass. |
| NFR-06 | Reproducibility: stable seed, run IDs, objectives, input snapshots, factor version. |
| NFR-07 | Error isolation: invalid extracted data cannot corrupt supply or demand. |
| NFR-08 | ESG boundary: distinct avoided emission estimates vs official corporate inventory/carbon credits/waste diversion. |
| NFR-09 | Demo security: no secrets/public privileged writes; repository contains synthetic, non-sensitive data. |
| NFR-10 | Honest reporting: distinguish demonstration results from real inventory/verified environmental performance, preserve actual evidence limitations and never invent integration or executed AI-call claims. This does not require announcing fixture origin to the model during local tests. |
| NFR-11 | Idempotent seed: repeat command does not inflate stock, events or carbon. |
| NFR-12 | Provider compatibility: actual `.gql` schema/connector operations compile on Firebase SQL Connect emulator, or blockers are explicitly recorded. |
| NFR-13 | Python integration proof: demonstrate named REST read/write/read-back with verified credentials/routing, operation error handling and replay-safe behavior; distinguish local/cloud results and blocked steps. |
| NFR-14 | Module separation: business calculations/transitions can be tested as Python functions without FastAPI or Firebase. React uses FastAPI; no persistent Node application backend. |

## Canonical fixture and transaction acceptance

| ID | Given | Expected |
|---|---|---|
| A01 | Baseline fixture | 13 top-level arrays excluding metadata, correct counts, no `users`/`roles`. |
| A02 | All FK relations | Every reference points to an existing row; IDs unique. |
| A03 | Paver descriptions in separate rows | Both map same canonical SKU when specs agree. |
| A04 | Two tiles have different dimensions or critical grades | Not an eligible selectable proposal. |
| A05 | BOQ record of 2,000 blocks and PO of 1,800 | No confirmed supply created from those rows alone. |
| A06 | `POTENTIAL` supply with declared units | Reservable amount = 0. |
| A07 | Confirmed supply Q=1,000, R=400, D=200 | Remaining reservable = 400. |
| A08 | Two recipients together demand > remaining stock | Historical *selected/live* commitments do not exceed stock; alternative proposals aren't additive. |
| A09 | Open demand N=600, F=200, active incoming C=300 | New allocatable demand = 100. |
| A10 | Receipt of 600, confirmed use of 0 | Confirmed reuse dashboard contributes 0. |
| A11 | Proposed 600, approved 580, dispatched 570, received 550, used 500 | Actual reused 500; all inequalities hold. |
| A12 | Cancelled transfer before dispatch | Reservation released, no transferred-out delta. |
| A13 | Historical completed transfer | All event timestamps <= 2026-10-12, order reflects state. |
| A14 | Future release 2026-10-20 | Cannot have an already-completed actual transfer before 2026-10-12. |
| A15 | Two same-material sources with different distances | Forecast transport differs if unit mass/factors known. |
| A16 | 600 pcs, 2.5 kg each, 25 km, transport EF 0.12 kgCO2e/t-km | Estimated additional transport = **4.5 kgCO2e**. |
| A17 | Production factor 0.75 kgCO2e/pcs and quantity 600 | Estimated avoided production = **450 kgCO2e**, *if* displaced production baseline. |
| A18 | Missing handling factor required by declared boundary | Net = null, status = `INSUFFICIENT_DATA`, not a false `0`. |
| A19 | Two assessments for one allocation (forecast and actual) | Dashboard actual reuse/carbon uses only actual assessment, not sum. |
| A20 | Run seed importer twice | Same row counts, no duplicated effects, stable IDs. |
| A21 | Import into local SQL Connect emulator | All tables/query paths read back, FK constraints hold, no provider-syntax errors. |
| A22 | Same 500 pcs confirmed stock, two concurrent reservation commands each 500 | At most one succeeds; operational transaction test. |
| A23 | Documented seed scenario IDs | Every listed scenario ID has valid referenced records. |
| A24 | Data source assertions | Every example has `synthetic=true` metadata; real-file URI/hash absent; factors labelled demo. |
| A25 | Minimal standalone Python REST adapter proof | Read/write/read-back and repeat behavior observed through named operations; authentication/authorization, routing and errors documented. No full FastAPI server required. |
| A26 | Historical partial reuse and current commitments | Actual-use quantity counts once; unused/missing residuals explained and not silently released/restocked. Undefined cost allocation leaves net incomplete. |

Historical seed eligibility uses its saved inputs/event time; new reservations revalidate current inputs. Fixture quantities may include legacy partial physical movements. Current full-receipt controls must not claim support for creating those discrepancy cases.

## Test map

| Area | Representative test files |
|---|---|
| Canonical data/tooling | test_seed.py, test_seeding_lock.py, test_dev_tooling.mjs |
| Fresh-clone integrated demo | test_demo_workspace.py: date rebasing, mixed units/carbon, guarded empty-only bootstrap, draft refusal, repeat preservation and full transfer/export |
| Intake/storage/access | test_ingestion.py, test_ingestion_emulator.py, test_workspace.py |
| Provider orchestration/prompts | test_analysis.py, test_analysis_improvements.py, test_analysis_coverage.py |
| Material resolution | test_material_search.py, test_project_material_workflow.py, test_reviewed_catalogue_matching.py |
| Formats/large inputs | test_pdf_preparation.py, test_office_readers.py, test_large_documents.py |
| Output recovery | test_duplicate_json.py, test_batched_repairs.py, test_ingestion_cleanup.py |
| Review/conversion/publication | test_review.py, test_prepared_review.py, test_material_editor.py, test_publication.py |
| Allocation/forecast/impact | test_eligibility.py, test_allocation_objectives.py, test_forecast_preview.py, test_impact_service.py |
| Connected transactions | test_checkpoint_a.py, test_checkpoint_b.py, test_checkpoint_c.py, test_ab_corrections.py |
| Client contracts | test_live_client.mjs, test_ingestion_client.mjs, test_workspace_client.mjs, test_workspace_presentation.mjs |

Tests live under `tests/`. The historical nine-tool/FileDraft compatibility snapshot is a dedicated JSON fixture at `tests/fixtures/ingestion_contract_v1.json`, not embedded in a documentation report. Scripted provider tests verify mechanisms, not measured model accuracy.

## Running checks

```sh
npm test
npm run build:frontend
npm run python -- scripts/generate_seed.py --check
npm run demo:check
npm run python -- scripts/generate_provider.py --check
npm run test:integration
```

The integration runner starts disposable 9499 and refuses an occupied test port; it does not use the owner's 9399 database. Dedicated connected suites are `test:checkpoint-a`, `test:checkpoint-b` and `test:checkpoint-c`; their names are retained executable interfaces, not required phases for contributors. Run them sequentially, without manually enabling destructive flags against an existing workspace. Default unit/client suites use temporary/scripted fixtures with no live model call.

## Evidence and acceptance limits

The 24 October repository preparation run reported 27 tooling/client tests and 468 Python tests with 73 skipped and no failures. A separate disposable-emulator integration run passed all 49 tests, including the new-clone demo journey. These counts describe those runs; skipped database tests are not passed integration proof. The frontend build and seed/demo/provider generator checks passed. Native/cloud/provider acceptance must name the actual environment, source files and results; CI configuration alone is not evidence of execution.

The owner completed an initial integrated walkthrough. Remaining scenarios and refinements are tested after the first integrated version rather than repeatedly blocking delivery on exhaustive manual sandbox work. Existing validation/atomicity/provenance safeguards are not deferred.

### Remaining scenarios

The first integrated version is available. The items below remain representative acceptance/refinement work, rather than claims that their underlying services are absent. Existing automated coverage is retained.

| ID | Scenario | Existing evidence | Acceptance still to run |
|---|---|---|---|
| DA-01 | Existing project quantities and newer documents | Existing identities recognised; automated add/replace/history and supersession checks. | Use meaningful prior quantities plus newer documents. Verify repeated evidence, additions and corrections without double counting or losing history. |
| DA-02 | Verified units and operational quantities | Conversion preview exercised; unit-conflicted rows used history/exclusion in the owner publication. | Use supported conversion evidence or the agreed same-unit representation. Verify original/converted values, complete stock scopes, local need/net demand, confirmed release/timing and matching-ready quantities. Never auto-confirm calculated surplus. |
| DA-03 | Multiple documents, duplicates, revisions and conflicts | Scripted file isolation, duplicate lookup, added-file reuse/rebase, edit preservation and approval checks. | Test representative live documents together and over time, including semantic overlaps, conflicting statements, reviewed supersession and affected reconfirmation. |
| DA-04 | New projects and multi-project documents | Proposal/reference validation and published multi-project examples; repeat with independently prepared evidence. | Publish a genuinely new project; assign several projects in one document and resolve ambiguous shared quantities without invented allocations. |
| DA-05 | Provider/file failures and recovery | Scripted/mechanical errors, retained partial files/groups, retry, skip/manual replacement and restoration tests; some historical provider failures. | Exercise the assembled UI with provider/network/backend interruptions. Verify retained successes/edits, explicit retry, truthful manual provenance, fresh restored context and no early publication or silent paid replay. |
| DA-06 | Representative formats and completeness | Generic Office/PDF/image, hidden-cell/formula and page/group/provenance tests. | Test owner-provided construction Word/Excel, scanned/mixed/large documents, missing formula caches and full relevant-item/source coverage. Unsupported content must remain explicit. |
| DA-07 | Matching, transfer and impact journey | Component and connected local transaction tests; automatic matching and impact processing are implemented. | Verify the implemented path from upload through eligible matching/alternative selection, reserve/dispatch/receive/use and impact/export, including timing, capacities, missing carbon inputs and no double counting of alternatives. |
| DA-08 | Replay, stale state, competing writes and handoff failure | Unit/isolated database coverage for replay, rollback, staleness and some concurrency. | Verify these through the assembled workflow, including duplicate publications/reservations, actual matcher retries and protected active-transfer corrections. Matching failure must not roll back publication or silently lose notification. |
| DA-09 | Native platforms | Native macOS and portable tooling checks; simulated paths do not prove another OS. | Verify native Windows and the complete macOS workflow: setup, Unicode/source paths, emulator, model configuration and recovery. Record Linux separately if exercised. |



## Known limitations and future scope

Model omissions, mistaken identity/meaning/source references, ambiguous conversions and context-only project gaps can still require operator correction/exclusion. Coverage checks do not establish semantic correctness. Current workspace/publication read and transaction capacities fail explicitly rather than truncating a supposedly complete batch. Indexed catalogue performance at production scale, broad native accessibility, hard-crash/engine-upgrade persistence, complete exception workflows and cloud access remain separate acceptance work.

P1 possibilities include future surplus forecasting, sensitivity/alerts and richer visual analysis. P2 includes separately approved ERP/BIM/Pantas integration, enterprise access, evidence vault and verified lifecycle assurance. No carbon-credit certification or revenue is promised.
