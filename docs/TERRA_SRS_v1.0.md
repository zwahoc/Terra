# Terra — Software Requirements Specification (SRS)

**Version:** 1.0 — Approved project-team requirements baseline  
**Date:** 13 October 2026  
**Project:** Sime Darby Property University Hackathon 2026  
**Product:** Terra — AI-Assisted Construction Material Reuse and Carbon Optimisation  
**Status:** Team-defined prototype specification; **not** an official Sime Darby Property specification

> **Document control.** This SRS defines *what* Terra must do. The existing `docs/00`–`docs/09` documents define product context, architecture, implementation contracts and evidence. The eight decisions recorded in Section 11 were confirmed by the project owner on 13 October 2026 and supersede conflicting earlier design assumptions. Avoid duplicating conflicting requirement IDs: detailed requirements in this document use the `SRS-FR-` prefix, while existing `docs/06_REQUIREMENTS_AND_TESTS.md` retains its original `FR-01`–`FR-24` identifiers.

---

## 1. Introduction

### 1.1 Purpose

This SRS defines Terra's functional requirements, non-functional requirements, business rules, data requirements, system interfaces, acceptance conditions and MVP limits. The intended readers are the four-person development team and AI coding assistants working within the Terra repository.

### 1.2 Background and opportunity

Separate construction projects can have usable, unused material while other projects need equivalent material. Reuse opportunities may be obscured by disconnected document formats, material terminology, availability dates, location, procurement and project schedules. Terra proposes to interpret existing records, expose potential material reuse opportunities, optimise eligible transfers and retain environmental evidence.

**Evidence boundary:** Publicly available information does **not** establish that SDP lacks an existing cross-project reuse platform or that a particular amount of SDP-reported waste is reusable surplus. Terra is a proposed solution, tested using explicitly synthetic construction scenarios. Pantas is an existing ESG service associated with SDP; integration to Pantas is *not* implemented or assured.

### 1.3 Objectives

| ID | Objective |
|---|---|
| OBJ-01 | Improve visibility of unused material and outstanding cross-project demand. |
| OBJ-02 | Reduce manual processing of differently formatted construction documents. |
| OBJ-03 | Identify and optimise feasible reuse opportunities subject to technical and operational constraints. |
| OBJ-04 | Evaluate estimated environmental outcomes under clearly disclosed assumptions. |
| OBJ-05 | Track the chain from proposal to reservation, transport, receipt and actual reuse. |
| OBJ-06 | Export traceable information to support internal ESG review and a possible future approved Pantas exchange. |

### 1.4 Intended operator

The hackathon prototype is a **single-user application**. One operator may view all projects, review extraction, confirm example release/acceptance steps, run optimisation, manage transfer states and export reports. There are **no application user accounts, logins, sessions, role tables or role-based authorisation** in the MVP. Business confirmation statuses remain in the workflow but do not imply actual approvals by independent companies or personnel.

### 1.5 MVP scope

**Included:** project/material catalogue; CSV/XLSX and selected text-PDF intake; assisted extraction and review; separate inventory/supply/demand semantics; deterministic matching; allocation optimisation; carbon-aware comparisons; transfer/event lifecycle; actual-use tracking; environmental dashboard; CSV/JSON export; local React/FastAPI application; local Data Connect emulator and later optional shared cloud database configuration during integration.

**Excluded:** live SDP ERP/BIM/procurement integration; automatic engineering certification; real logistics operations or payments; full lifecycle assessment; official corporate carbon accounting; carbon-credit issuance; live Pantas API; user/role management; public application hosting; a second Node.js application backend.

### 1.6 Terminology

| Term | Definition |
|---|---|
| BOQ | Bill of Quantities: planned construction work/material quantities, **not evidence of owned stock**. |
| PO | Purchase order: items ordered, **not evidence of delivery, available stock or surplus**. |
| Inventory | Recorded on-hand material; not necessarily surplus or releasable. |
| Potential surplus | Provisional excess inferred or reported, pending verification; **not reservable**. |
| Confirmed surplus | Verified unused/releasable material offered for reuse; subject to further compatibility and reservation checks. |
| Demand | A validated outstanding need; must account for already fulfilled and actively committed incoming quantities. |
| Proposal | Optimiser suggestion; **not** a reservation, transfer or achieved reuse. |
| Actual reuse | Quantity confirmed physically used by the receiving project, not merely dispatched or received. |
| CO₂e | Carbon dioxide equivalent; comparisons are estimates and may be incomplete. |
| ESG | Environmental, social and governance reporting; Terra supports an upstream operational evidence layer. |

---

## 2. System overview

### 2.1 Four capabilities

1. **AI Material Intelligence** — Process construction files, extract original facts, classify document sources and propose canonical material mappings. Keep review, uncertainty and provenance.
2. **Circular Optimisation Engine** — Use confirmed supply, validated unmet need, material specifications, units, condition and dates to produce explainable allocation plans without oversubscription.
3. **Carbon Intelligence** — Estimate avoided new-material production against additional transport and handling/processing effects; compare plans using clearly versioned factors, explicit baselines and incomplete-data states.
4. **Transfer & ESG Management** — Simulate required confirmations, reserve eligible quantities, record dispatch/receipt/actual reuse, retain events and export separate operational and environmental measures.

### 2.2 End-to-end workflow

1. Operator selects a project and registers structured facts or uploads a supported document.
2. Parser/LLM extracts source text, values, units, dates, material descriptions and source locators.
3. Operator reviews extracted rows, corrects errors and accepts them individually or in bulk; all records enter review, including high-confidence ones.
4. Deterministic services distinguish BOQ, PO, actual inventory and outstanding demand; they may flag *potential* surplus but cannot certify it.
5. Operator confirms that a releasable, suitable quantity is available; this becomes eligible supply.
6. Optimiser computes eligible supply/demand pairings and creates multiple comparable plans where feasible.
7. Carbon module estimates environmental differences under documented factors, mass and baseline assumptions.
8. Operator chooses a proposal; example source/recipient confirmation states are recorded; a successful atomic transaction reserves supply **and** unmet recipient demand.
9. Dispatch, receipt and actual use are recorded separately, including discrepancies and material left over at the recipient.
10. Operational metrics and revised environmental assessments reflect what actually occurred; exports distinguish achieved results from forecasts.

### 2.3 Confirmed architecture and environment phases

**Application:** React + TypeScript + Tailwind CSS → FastAPI (Python) → framework-independent Python services → Python Data Connect adapter → Firebase Data Connect / PostgreSQL.

**Phase A — Development:** React/FastAPI and the **Firebase Data Connect Local Emulator** run locally. Seed data is reproducible per developer, so local data is not necessarily shared live among teammates.

**Phase B — Full-system integration:** React and FastAPI **continue running locally**. The team intends to configure **one shared Firebase Data Connect Cloud SQL PostgreSQL database** so local application instances can work with uniform project data. Cloud database setup is a distinct, explicitly approved integration task; it is **not** permission to host the frontend or backend online or incur charges without approval.

The Python adapter must isolate emulator vs cloud endpoints and authentication. Server-side credentials must not appear in browser code, public connector mutations or Git history. A cloud deployment is not demonstrated by emulator test success. Firebase tooling may require Node.js; **no separate Node.js application backend** is permitted.

### 2.4 Baseline and implementation state

The submitted repository documentation (`docs/SEED_VALIDATION.md`, dated 13 October 2026) **reports** a tested synthetic 13-entity seed and local emulator importer. Its dataset as-of date is **2026-10-12** and must not silently be changed merely because the SRS date is later. This SRS describes the **full MVP**, most of which is *not* yet implemented. The data foundation's reported validation is not evidence that the real document parser, solver, FastAPI workflow or UI is complete.

---

## 3. Functional requirements

**Priority definitions:** `P0-SEED` = essential seeded foundation; `P0-MVP` = required complete prototype; `P1` = optional enhancement; `P2` = future system. The `SRS-FR-` numbering is unique to this SRS and does not replace the existing `FR-01`–`FR-24` IDs in Document 06.

### 3.1 Project and material catalogue

| ID | Priority | Requirement |
|---|---|---|
| SRS-FR-01 | P0-SEED | Store stable project identifiers, names, locations/townships and lifecycle/status fields. |
| SRS-FR-02 | P0-SEED | Store canonical material categories, critical specifications, explicit base unit and defensible unit mass when available. |
| SRS-FR-03 | P0-MVP | Browse and filter projects, materials, surplus and demand through FastAPI-backed UI views. |

**Acceptance:** Every linked record uses an existing project/material ID; materially different grades, dimensions or finishes remain distinguishable.

### 3.2 AI document intake and review

| ID | Priority | Requirement |
|---|---|---|
| SRS-FR-04 | P0-MVP | Accept CSV, XLSX and selected text-based PDF documents; clearly reject unsupported layouts/formats. |
| SRS-FR-05 | P0-MVP | Classify source type as BOQ, purchase order, inventory, demand or other. |
| SRS-FR-06 | P0-MVP | Extract raw descriptions, quantity, unit, dates, technical properties and page/sheet/row references. |
| SRS-FR-07 | P0-MVP | Suggest canonical material mapping while checking category and critical specification conflicts. |
| SRS-FR-08 | P0-SEED + MVP | Preserve original content, normalised fields, source provenance, uncertainty, source type and review information. |
| SRS-FR-09 | P0-MVP | Require review of **all** extracted rows before publication; support per-row correction/rejection and **bulk acceptance** of reviewed selections. Highlight low-confidence, incomplete or conflicting rows. |
| SRS-FR-10 | P0-SEED + MVP | Reject automatic publishing of unreviewed BOQ/PO/inventory rows as confirmed surplus; prevent reprocessing from duplicating operational quantities. |

**Clarification (OD-04):** LLM confidence never bypasses review automatically. Bulk acceptance is a deliberate operator action. `PENDING`, `ACCEPTED`, `CORRECTED` and `REJECTED` are the existing logical review outcomes; any new real-ingestion substate must be harmonised with the source contract.

### 3.3 Surplus and outstanding-demand analysis

| ID | Priority | Requirement |
|---|---|---|
| SRS-FR-11 | P0-SEED + MVP | Keep BOQ requirements, POs, recorded stock, potential surplus, confirmed surplus and outstanding demand semantically separate. |
| SRS-FR-12 | P0-MVP | Calculate possible excess stock **only where complete, validated stock and remaining-project-need inputs exist**. |
| SRS-FR-13 | P0-SEED + MVP | Maintain separate `POTENTIAL` and `CONFIRMED` states; source-project release confirmation remains a deliberate action. |
| SRS-FR-14 | P0-SEED + MVP | Calculate newly allocatable demand after subtracting fulfilled quantity and active incoming commitments; do not infer all BOQ quantities remain needed. |
| SRS-FR-15 | P0-SEED + MVP | Never reserve potential, suspended or unverified supply. |

Example: stock 1,000 pcs − independently verified remaining site need 700 pcs = **potential** 300 pcs, **not** immediately confirmed surplus.

### 3.4 Matching and allocation optimisation

| ID | Priority | Requirement |
|---|---|---|
| SRS-FR-16 | P0-MVP | Check material/specification, condition, measurement-unit and date compatibility before suggesting an eligible match. |
| SRS-FR-17 | P0-MVP | Expose rejection or `REVIEW_REQUIRED` explanations when compatibility cannot be established. |
| SRS-FR-18 | P0-MVP | Produce feasible proposals without exceeding confirmed supply or uncommitted demand. |
| SRS-FR-19 | P0-MVP | Allocate one source to multiple demand projects when valid; allow partial fulfilment. |
| SRS-FR-20 | P0-MVP | Compare at least reuse-maximising and carbon-aware optimisation objectives on the same input snapshot. |
| SRS-FR-21 | P0-SEED + MVP | Retain optimisation run objective, assumptions, input/factor version, plan and reason codes; proposed plans never reserve stock automatically. |

**Tie-break rule (OD-05):** After feasibility constraints and the chosen primary optimisation objective, equal-ranked alternatives are ordered by **earliest feasible delivery**; then **shorter applicable transport distance**; then **stable project ID** for reproducibility. Actual delivery-time data must not be fabricated; if unavailable, the system may use validated availability dates as a stated proxy or leave the tie unresolved with a deterministic ID fallback.

### 3.5 Carbon and environmental comparisons

| ID | Priority | Requirement |
|---|---|---|
| SRS-FR-22 | P0-SEED | Store factor value, unit, applicability, provenance, geography, calculation boundary, dataset version and synthetic/verified status. |
| SRS-FR-23 | P0-MVP | Calculate estimated avoided production only against a justified equivalent-new-material baseline. |
| SRS-FR-24 | P0-MVP | Calculate added transport from **actual transported mass**, route length and suitable tonne-km factor where available. |
| SRS-FR-25 | P0-MVP | Derive net avoided CO₂e only when required baseline, transport and handling/processing inputs exist; otherwise mark `INSUFFICIENT_DATA`. |
| SRS-FR-26 | P0-MVP | Compare carbon outcomes across feasible plans; negative or incomplete outcomes are valid. |
| SRS-FR-27 | P0-MVP | Distinguish forecast proposal assessments from actual-use assessments and support versioned revisions. |

**Simple illustrative equations:**

- Avoided production (kgCO₂e) = **quantity actually substituted** × documented production factor per corresponding unit.
- Transport (kgCO₂e) = **actual mass transported (tonnes)** × additional distance (km) × documented kgCO₂e/(tonne·km) factor.
- Estimated net avoided = avoided production − additional transport − documented additional handling/processing (plus any other explicitly modelled baseline differences).

**Illustrative only:** 600 paving blocks × 0.75 kgCO₂e/pcs = 450 kgCO₂e potentially avoided in production. If 600 blocks × 2.5 kg = 1.5 t are moved 25 km with a synthetic factor of 0.12 kgCO₂e/t-km, transport = 4.5 kgCO₂e. If *explicitly assumed* additional handling is 10 kgCO₂e, net estimate = **435.5 kgCO₂e**. If handling is required by the declared boundary but unknown, **net = null/incomplete**, not 445.5.

**Partial reuse decision (OD-02):** If 600 units are transported and only 500 units are actually used, the actual-use substitution calculation uses **500**, while the transport calculation uses the **mass really transported**, even if that quantity is larger. Known handling and unresolved residual/missing material effects must be accounted for or flagged. Do not prorate all emissions to 500 without evidence.

**Revision decision (OD-03):** Recalculations create **a new immutable assessment revision** (with previous revision, timestamp, factor versions and reason). Preserve earlier revisions; only the latest appropriately **reviewed** revision for a given scope/basis is the current reported figure. Forecast and actual scopes must never be combined as if both achieved reuse. The existing seed may contain one assessment per basis; full revision behaviour belongs to the later carbon module.

**Accounting boundaries:** Comparative avoided-emissions estimates are not official Scope 1/2/3 inventory deductions, issued credits, or automatically SDP-reported waste diversion. Verified direct reuse, demonstrated waste prevention and waste diversion are separate measures.

### 3.6 Transfer, receipt, residual material and history

| ID | Priority | Requirement |
|---|---|---|
| SRS-FR-28 | P0-MVP | Create a transfer request from an eligible selected proposal. |
| SRS-FR-29 | P0-MVP | Capture simulated source/destination confirmation states without user accounts. |
| SRS-FR-30 | P0-MVP | Atomically reserve quantities on both supply and demand sides, rechecking current eligibility and balances. |
| SRS-FR-31 | P0-MVP | Track dispatched quantity and timestamp separately from approved/reserved amounts. |
| SRS-FR-32 | P0-MVP | Track received quantity and timestamp separately from dispatch. |
| SRS-FR-33 | P0-MVP | Record actual reuse separately from receipt; allow later additional-use confirmation of valid remaining material. |
| SRS-FR-34 | P0-MVP | Keep chronological append-only-style operational events and corrections. |
| SRS-FR-35 | P0-MVP | Handle cancellation, partial delivery and remaining/damaged/returned/discarded material without silently restoring stock or claiming reuse. |

**Standard path:** `REQUESTED → APPROVED → RESERVED → IN_TRANSIT → RECEIVED → REUSED`, with supported rejection/cancellation and exceptional partial-use states.

**Remainder decision (OD-01):** For example, if 600 are dispatched, 580 received, and 500 reused, the system must distinguish the **20-unit dispatch/receipt discrepancy** from the **80 units received but not yet used**. The 80 remain tracked at the receiving project with a disposition such as `AWAITING_USE`, later `REUSED`, `RETURNED`, `DAMAGED` or `DISCARDED` supported through event data/appropriate records. Do not silently declare all 600 reused, return 80 to source stock, or interpret 20 missing as discarded. A release/return must preserve stock and incoming-demand accounting. Exact API payloads and persistence fields may be finalised in the transfer implementation, not guessed from the seed's existing fields.

**Safety checks:** `actually_used ≤ received ≤ dispatched ≤ approved ≤ proposed`; active source reservations cannot exceed confirmed releasable stock; active incoming commitments cannot exceed unmet demand. Idempotency prevents duplicate use/dispatch/receipt. A reservation must be atomic under competing actions; emulator import transaction success is **not** sufficient evidence of operational concurrent-reservation safety.

### 3.7 Dashboard and ESG exports

| ID | Priority | Requirement |
|---|---|---|
| SRS-FR-36 | P0-MVP | Display inventory, confirmed reservable surplus, potential surplus and outstanding demand with appropriate unit grouping. |
| SRS-FR-37 | P0-MVP | Display allocation proposals and transfer event/status history separately from actual reuse. |
| SRS-FR-38 | P0-MVP | Calculate confirmed actual reuse from valid completed-use records without double counting. |
| SRS-FR-39 | P0-MVP | Present carbon assessments, factor/source caveats, assumptions and incomplete flags; distinguish forecasts and actual outcomes. |
| SRS-FR-40 | P0-MVP | Export traceable CSV/JSON reuse and environmental summaries for internal review and potential future approved Pantas integration. |

**Dashboard rule:** Totals must derive from persisted data; don't sum incompatible units or count alternative proposals as performed transfers. An actual-use quantity is counted once. No live Pantas integration is part of the MVP.

---

## 4. Use cases

### UC-01 — Upload, extract and review construction data

**Actor:** Single demo operator. **Precondition:** Known project, supported source document.  
**Main flow:** Select project → upload → classify source → extract text/fields/provenance → propose normalisation → review all rows → correct/reject/bulk-accept checked rows → publish valid reviewed records.  
**Exceptions:** Unsupported file/layout; absent unit; incompatible grade; duplicate source; LLM failure; uncertain document type.  
**Outcome:** Reviewed records retain raw facts; no implicit confirmed surplus.

### UC-02 — Identify and confirm releasable surplus

**Precondition:** Validated inventory, local project requirement and commitment records are available.  
**Main flow:** Compute potential excess → display derivation → operator verifies physical unused condition, ownership/release and quantity → mark eligible confirmed surplus.  
**Exceptions:** Unknown remaining requirement, insufficient stock, unsuitable material, conflicting evidence.  
**Outcome:** Only confirmed suitable quantity is eligible for reservation.

### UC-03 — Optimise and compare allocation plans

**Precondition:** Valid confirmed supply and outstanding demand.  
**Main flow:** Choose objective → snapshot inputs → deterministic eligibility checks → optimise feasible quantities → assess carbon where data exists → display rationale, ties and uncertainties → select proposal.  
**Exceptions:** No eligible matches; incompatible units/specs; infeasible date; incomplete carbon factors.  
**Outcome:** Reproducible proposals, no stock change yet.

### UC-04 — Execute a material transfer

**Precondition:** Selected currently valid proposal and simulated confirmations.  
**Main flow:** Request → approve → atomically reserve source and destination → dispatch → receive → confirm actual use → record residual disposition/events → update counters and impact records.  
**Exceptions:** Changed stock, partial delivery, missing quantity, damage, cancellation, repeated actions, late supplier.  
**Outcome:** Operational balances and evidence remain consistent; unused material is tracked.

### UC-05 — Calculate, revise and export ESG information

**Precondition:** Proposal or physical reuse facts and environmental inputs.  
**Main flow:** Select scope/baseline → calculate factor-based estimate → flag missing assumptions → review → version any corrections → dashboard/export latest reviewed actual scope separately from forecast.  
**Outcome:** Traceable CSV/JSON for internal review; no claim of external credit or official inventory reduction.

---

## 5. Data requirements

### 5.1 Core logical entities

1. `projects` — construction locations and project information.
2. `materials` — canonical material specifications and unit/mass reference.
3. `documents` — source-document metadata (stubbed until real files are added).
4. `extracted_rows` — source text and accepted/corrected standardisation.
5. `supply_offers` — potential and confirmed surplus with stock counters.
6. `demand_requests` — outstanding requirements and fulfilment.
7. `route_distances` — site-to-site route-distance assumptions.
8. `optimisation_runs` — saved objective/inputs and results.
9. `allocation_proposals` — candidate source/demand/quantity pairings.
10. `transfers` — selected operational movements and quantities.
11. `transfer_events` — append-only-style lifecycle/evidence events.
12. `emission_factors` — governed impact factor references.
13. `impact_assessments` — scenario-specific forecasts and actual-use estimates.

Use `docs/02_DATA_MODEL_CONTRACT.md` and `docs/SEED_DATA_DICTIONARY.md` for current physical fields, statuses, base units and relations. The new leftover/disposition and assessment-versioning decisions are **future implementation requirements**, not a claim that the current seeded schema already stores every field.

### 5.2 Key integrity rules

| ID | Requirement |
|---|---|
| SRS-DR-01 | Stable unique record IDs and referential integrity across all 13 entities. |
| SRS-DR-02 | Numeric quantities, compatible units and explicit unit conversion basis; null is not automatically zero. |
| SRS-DR-03 | Prevent stale approvals, competing reservations and double commitment on supply **and** demand. |
| SRS-DR-04 | Keep physically transported, received, reused, returned, damaged and discarded quantities reconcilable. |
| SRS-DR-05 | Maintain source document provenance and immutable original extraction values. |
| SRS-DR-06 | Distinguish simulated demonstration history from real uploaded evidence. |
| SRS-DR-07 | Version impact assumptions/factors and identify the authoritative reviewed revision for each reporting basis. |
| SRS-DR-08 | Repeatable seed import must not duplicate quantities, transfers, events or carbon achievements. |

### 5.3 Existing seed foundation (reported status, not SRS completion)

The uploaded `docs/SEED_VALIDATION.md` reports the following current synthetic fixture:

| Entity | Rows | Entity | Rows |
|---|---:|---|---:|
| `projects` | 5 | `materials` | 20 |
| `documents` | 15 | `extracted_rows` | 50 |
| `supply_offers` | 22 | `demand_requests` | 22 |
| `route_distances` | 10 | `optimisation_runs` | 4 |
| `allocation_proposals` | 15 | `transfers` | 8 |
| `transfer_events` | 31 | `emission_factors` | 8 |
| `impact_assessments` | 8 | | |

Seed snapshot: **2026-10-12**, synthetic. The document reports 38 offline automated tests and 10 emulator tests passing; operational concurrent reservation, real-file extraction, solver and full FastAPI/UI integration remain future work. This is an implementation evidence reference, **not** an acceptance claim for the complete SRS.

---

## 6. External interfaces

### 6.1 Application UI

Four functional areas, which may be implemented as combined or separate screens:

1. Overview dashboard.
2. Projects, materials, confirmed/potential supply and demand.
3. AI document intake, row review and corrections.
4. Optimisation comparison, transfer management and ESG results/export.

### 6.2 FastAPI interface

React must call FastAPI for application reads, writes and processing. FastAPI provides Pydantic validation, consistent error responses and orchestration around independent Python domain services. The endpoints in `docs/08_MODULE_INTERFACES.md` are proposals until implemented. Do not imply they already exist.

### 6.3 Database access

A Python repository/adapter executes named Firebase Data Connect operations. Development uses the emulator. At full integration, the same domain services should work with a configured, permissioned cloud adapter. The provider's emulator administrative capabilities do not establish equivalent cloud IAM or credential permissions. All privileged secrets remain outside the client and repository.

### 6.4 ESG interface

Support local CSV/JSON export of source/destination, material and conditions, actually reused quantity/mass, event/evidence references, assessment basis/factors, calculated estimates and uncertainty. Future use in SDP/Pantas is conditional on approval and compatible data contracts; it is not a live interface.

---

## 7. Non-functional requirements

| ID | Category | Requirement |
|---|---|---|
| SRS-NFR-01 | Traceability | Accepted extracted values link to source document and row/page where available; synthetic stubs explicitly labelled. |
| SRS-NFR-02 | Explainability | Eligibility constraints and deterministic tie-breaks have inspectable inputs and reason codes. |
| SRS-NFR-03 | Atomicity | Reservations/commitments cannot oversubscribe supply or recipient need under concurrent commands. |
| SRS-NFR-04 | Security | No public privileged mutations, client-exposed DB credentials, committed secrets or accidental production/admin access. |
| SRS-NFR-05 | Validation | Reject invalid units, quantities, states and unreviewed publications. |
| SRS-NFR-06 | Failure isolation | Ingestion or computation failures do not corrupt verified supply/demand or transfer records. |
| SRS-NFR-07 | Reproducibility | Runs retain input snapshots/objectives; impact revisions retain factor provenance and original calculations. |
| SRS-NFR-08 | Maintainability | Domain calculations can be unit-tested without FastAPI server or cloud database. |
| SRS-NFR-09 | Contract consistency | React DTOs, FastAPI schemas, domain models and Data Connect operations use agreed semantics. |
| SRS-NFR-10 | Auditability | Material transfer and correction events remain recoverable and chronological. |
| SRS-NFR-11 | Local portability | Development and tests can run against reproducible emulator seed without cloud configuration. |
| SRS-NFR-12 | Clarity | Display `POTENTIAL`, `CONFIRMED`, `PROPOSED`, `RESERVED`, `RECEIVED` and `REUSED` distinctly. |
| SRS-NFR-13 | Honest reporting | Keep projected carbon and actual-use outcome, credits, corporate scopes and waste diversion separate. |
| SRS-NFR-14 | Testability | Provide automated positive/negative tests for critical logic and replay/idempotency. |

### 7.1 Agreed performance targets (OD-08)

These are **initial MVP targets for a representative local development setup**, not currently measured guarantees or service-level agreements. Benchmark with a documented machine, test-file sizes and LLM configuration; report exceptions rather than assuming success.

| Operation | Target |
|---|---|
| Normal dashboard or material listing response | Within **2 seconds** |
| Small CSV/XLSX file extraction | Within **30 seconds** |
| Selected text-based PDF extraction | Within **45 seconds** |
| Optimisation on the baseline dataset | Within **10 seconds** |
| Transfer approval/reservation operation | Within **2 seconds** |

The UI should give clear progress/working/error feedback when an LLM call or integration operation exceeds its target. Performance testing must distinguish local parsing from external LLM network latency where applicable.

### 7.2 Deployment and data sharing (OD-06 and OD-07)

- **Application:** Remains local; no public React/FastAPI deployment is planned, and no login system is required.
- **Development database:** Firebase Data Connect **local emulator** through isolated module development.
- **Shared integration database:** When the full system is ready for integration, move/configure a **shared Firebase Cloud SQL PostgreSQL instance** for consistent data across each developer's locally running Terra app.
- A cloud database requires controlled authentication and a deliberate provision/billing decision. Nothing in this SRS authorises paid provisioning. If the cloud is unavailable, continue local development; do not present the databases as already synchronised.

---

## 8. Business rules

| ID | Rule |
|---|---|
| SRS-BR-01 | BOQ amounts are planned requirements, not surplus. |
| SRS-BR-02 | PO quantities are ordered, not proof of physical delivery or releasable stock. |
| SRS-BR-03 | Stock is not automatically confirmed surplus. |
| SRS-BR-04 | Only eligible confirmed surplus may be reserved. |
| SRS-BR-05 | Critical material specifications, units, time windows and conditions govern eligibility. |
| SRS-BR-06 | Unselected or alternative proposals are not actual reservations. |
| SRS-BR-07 | Recheck and atomically reserve both source stock and recipient outstanding need. |
| SRS-BR-08 | Dispatch, receipt and actual use are not interchangeable states or amounts. |
| SRS-BR-09 | Unused, missing, damaged and returned quantities are tracked with explicit dispositions, not silently counted or restocked. |
| SRS-BR-10 | Actual-use production benefits apply only to quantities demonstrably substituted; transport impacts use actually moved mass. |
| SRS-BR-11 | Carbon revisions are append-only and report a single latest reviewed current result per basis. |
| SRS-BR-12 | Net environmental impact is incomplete when required factors or boundaries are undefined. |
| SRS-BR-13 | No carbon credit, official GHG deduction, official waste diversion or Pantas live connection can be inferred from a reuse entry. |
| SRS-BR-14 | Real AI extraction requires human review; high-confidence values are not silently auto-published. |
| SRS-BR-15 | Equal-objective feasible options use earliest feasible delivery, then shorter route, then stable ID. |
| SRS-BR-16 | App is local/single-user; shared data across teammates arrives only when the cloud database integration milestone is configured. |

---

## 9. Acceptance tests

| ID | Given | Expected result |
|---|---|---|
| SRS-AT-01 | BOQ 2,000 pavers or PO 1,800 | Neither creates confirmed supply by itself. |
| SRS-AT-02 | Equivalent variant names, same verified spec | Same canonical material may be proposed. |
| SRS-AT-03 | Tile dimension/grade mismatch | Pair rejected or marked review-required. |
| SRS-AT-04 | Potential surplus, even with declared quantity | Reservable quantity is zero. |
| SRS-AT-05 | Confirmed 1,000 units; demands 600+400 | Feasible one-to-many proposal without over-allocation. |
| SRS-AT-06 | Supplier availability after recipient deadline | Ineligible or review-required with explanation. |
| SRS-AT-07 | Two concurrent reservations for same remaining stock | At most one succeeds if combined demand exceeds stock. |
| SRS-AT-08 | Two sources competing to fulfil same demand | Combined incoming commitments never exceed unmet need. |
| SRS-AT-09 | Dispatched 600, received 580, used 500 | Report 500 actual use; track 20 discrepancy and 80 received/unreused. |
| SRS-AT-10 | 600 × 0.75 kgCO₂e/pcs | Reproduce 450 kgCO₂e avoided production under valid baseline. |
| SRS-AT-11 | 600 × 2.5 kg and 25 km at 0.12 kgCO₂e/t-km | Reproduce 4.5 kgCO₂e transport. |
| SRS-AT-12 | Required handling factor missing | Net is `INSUFFICIENT_DATA`, not a fabricated zero. |
| SRS-AT-13 | Two revisions of one impact basis | Preserve both; dashboard uses latest reviewed authoritative version, counted once. |
| SRS-AT-14 | High-confidence extracted record | Remains subject to explicit review; supported bulk review works. |
| SRS-AT-15 | Equal-score feasible allocations | Earlier feasible delivery, then shorter distance, then stable ID decides order. |
| SRS-AT-16 | Re-upload same source row / repeated action | No duplicate published supply, reservations, events or impact. |
| SRS-AT-17 | Dashboard forecast and actual assessment | Never sums both as actual achievement. |
| SRS-AT-18 | Local development fresh checkout | Can initialise emulator and load reproducible seed without cloud credentials. |
| SRS-AT-19 | Local frontend and FastAPI; integrated shared cloud database | Local apps use approved server-side connection and see the same persisted records, after separate cloud configuration. |
| SRS-AT-20 | Representative local environment and sample data | Evaluate five performance targets, record observed measurements and any failed target. |
| SRS-AT-21 | Completed scenario | Operator can demonstrate upload → review → surplus/demand → optimisation → compare → reserve → dispatch → receive → reuse → export. |

**Acceptance interpretation:** Tests involving the full API, LLM, live solver, concurrent reservations, revisioned impact and cloud integration are *future implementation acceptance tests*, not tests claimed to have passed when the seed was generated.

---

## 10. Requirements traceability and development milestones

### 10.1 Documentation sources

| Repository document | Governs |
|---|---|
| `docs/00_PRODUCT_BRIEF.md` | Product boundaries, pitch and non-goals. |
| `docs/01_BUSINESS_WORKFLOW.md` | Business states, process, carbon example. |
| `docs/02_DATA_MODEL_CONTRACT.md` | Base entity schema, stock/demand invariants. |
| `docs/03_SEED_DATABASE_SPEC.md` | Option B synthetic seed input contract. |
| `docs/04_FIREBASE_ARCHITECTURE.md` | Firebase model, GraphQL schema, operations. |
| `docs/05_AI_INGESTION_CONTRACT.md` | Parsing, LLM review and publication contract. |
| `docs/06_REQUIREMENTS_AND_TESTS.md` | Original `FR-01`–`FR-24` and seed tests A01–A26. |
| `docs/07_DECISIONS_AND_SOURCES.md` | Decisions, provenance, earlier open issues. |
| `docs/08_MODULE_INTERFACES.md` | Proposed cross-module DTOs and API conventions. |
| `docs/09_ARCHITECTURE_UPDATE.md` | FastAPI/Python/Firebase architecture. |
| `docs/SEED_DATA_DICTIONARY.md` | Actual implemented synthetic seed definitions. |
| `docs/SEED_VALIDATION.md` | Reported results and limits of seed tests. |
| `docs/LOCAL_DEVELOPMENT.md` | Local emulator reproducibility instructions. |

**Synchronization action required:** When this SRS is added to the repo, the developer should update affected older documents—especially the decision log and future task instructions—so OD-01 through OD-08 are no longer described as unresolved. Retain historical decision provenance and do not modify seed snapshots merely to satisfy new workflow features.

### 10.2 Milestone boundaries

- **M0 — Seed foundation (reported completed):** synthetic catalogue, planned scenarios, validated JSON, emulator queries/import. Check `SEED_VALIDATION.md` for what was actually tested.
- **M1 — Modules and local MVP:** React/FastAPI contracts, document ingestion/review, deterministic surplus-demand rules, optimiser, carbon service, reservations/transfer workflow, dashboard/exports. All run locally against emulator.
- **M2 — Integrated shared database:** After whole-system integration is viable, configure a shared Firebase Cloud SQL database with approved authentication/hosting costs. Continue running React and FastAPI locally. Demonstrate uniform data across teammates.
- **M3 — Future enterprise roadmap:** Actual approved SDP systems/Pantas integrations, deployment, access roles, material passports and stronger assurance.

---

## 11. Approved decisions — 13 October 2026

These choices resolve the eight questions left open in the earlier draft. They are binding for the prototype unless the owner explicitly revises them.

| ID | Decision | Final policy |
|---|---|---|
| OD-01 | Partial or leftover material | **A:** Track receiver-side leftover quantity and its later use, return, damage or discard; preserve dispatch/receipt discrepancies. |
| OD-02 | Partial-use carbon | **A:** Only actually reused units support production-substitution estimate; transport uses the quantity physically transported. |
| OD-03 | Carbon recalculation | **A:** Version/review new assessments; retain prior results, report latest reviewed authoritative result per basis. |
| OD-04 | Extraction review | **A:** Human review all extracted rows, with bulk acceptance and uncertainty highlighting; no confidence-based auto-accept. |
| OD-05 | Solver tie-break | **A:** Earliest feasible delivery, then shortest distance, then stable project ID. |
| OD-06 | App exposure | **Local-only** single-user application; do not host frontend/backend publicly. Future cloud DB is for shared data only. |
| OD-07 | Development environment | **Local Data Connect emulator until full-system integration**, then plan a shared Firebase Cloud database. |
| OD-08 | Performance | **A:** Initial targets: dashboard 2 s; small CSV/XLSX 30 s; text PDF 45 s; baseline solver 10 s; reserve/approve 2 s. |

### 11.1 Remaining technical implementation details (not unresolved scope choices)

The decisions above settle business intent; implementation must still specify (a) transfer residual/event fields and how return updates inventory and demand commitments without duplication; (b) verified route/delivery inputs for tie-breaks; (c) authoritative impact revision identifiers and selection; (d) how local FastAPI authenticates against Firebase Cloud at the future integration phase; and (e) benchmark machine and realistic file sizes. These details may be specified by the implementing team without contradicting the approved policies; any materially different business behavior must be escalated for confirmation.

---

## 12. Approval and change control

**Approved baseline:** The owner has accepted the SRS draft and confirmed decisions OD-01–OD-08. The document defines a *student-team hackathon prototype*, not SDP engineering/procurement policy or an official sustainability reporting methodology.

Any future requirement change should record: ID, changed text, reason, affected modules/data contracts, updated acceptance test and effective date. Changes to the architecture or reporting boundary must also be synchronised with existing Terra handoff documents.

**End of Terra SRS v1.0.**
