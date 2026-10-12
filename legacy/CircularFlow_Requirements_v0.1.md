# CircularFlow — Requirements Catalogue

> Archived historical source. The original v0.1 content below is preserved for lineage, not current implementation instructions. Terra Documents 00–08 supersede conflicting product/account, dataset and workflow requirements; [Document 09](../docs/09_ARCHITECTURE_UPDATE.md) is authoritative for architecture. Use [Document 06](../docs/06_REQUIREMENTS_AND_TESTS.md) for current priorities/acceptance criteria. The adjacent legacy JSON is an unchanged illustrative proposal, not the Option B seed or evidence of completed reuse.

**Proposed MVP requirements | Draft v0.1 | 12 October 2026**  
**Status:** Team review material — these are **our proposed requirements**, not a published SDP specification.

## 1. Scope and system boundary

**Purpose:** Use data from existing construction records to identify and optimise approved reuse of unused, traceable, standardised, primarily non-structural construction materials across projects.

**CircularFlow does:** document extraction, material normalisation, supply/demand tracking, compatible matching, allocation optimisation, environmentally informed comparison, transfer lifecycle, evidence records and ESG-ready exports.

**CircularFlow does NOT (MVP):** certify structural safety, own physical logistics, replace company procurement/ERP, generate tradable carbon credits, replace Pantas or claim a live integration with it.

**Proposed roles:** project contributor, source-project approver, receiving-project approver, procurement reviewer, sustainability reviewer, administrator. For the demo, authentication may be mocked but approval actions must identify an actor.

**Requirements priority:** **P0** = working end-to-end demo; **P1** = enhancement; **P2** = future roadmap.

## 2. Functional requirements — P0 (must-have)
V
### A. Intake & AI Material Intelligence

| ID | Requirement | Acceptance check |
|---|---|---|
| FR-01 | Create and view 3–5 distinct projects | Projects have stable IDs and township/location fields |
| FR-02 | Upload CSV, XLSX and **selected** text-based PDF formats | Known sample templates parse; unsupported formats produce clear errors |
| FR-03 | Classify document as BOQ, PO, inventory or demand | BOQ quantity cannot directly become available surplus |
| FR-04 | Extract material names, quantities, units, dimensions/specs and relevant dates | Structured fields returned with source row/page reference |
| FR-05 | Map variant descriptions to canonical material types | `RECT PAVER 200X100X60` and equivalent wording are linked while specs preserved |
| FR-06 | Show AI uncertainty and allow correction before publishing | Reviewer can correct quantity/unit/specs and retain original text |
| FR-07 | Store accepted normalised records, not unreviewed guesses | Pending extracted row cannot silently become confirmed supply |

### B. Supply, Demand & Optimisation

| ID | Requirement | Acceptance check |
|---|---|---|
| FR-08 | Register confirmed or forecast surplus, and separate demand requests | Two explicit datasets; forecast offers non-reservable |
| FR-09 | Validate specification compatibility and compatible units | Different grades/dimensions rejected or flagged for review |
| FR-10 | Check supply/demand quantity and time windows | Cannot allocate beyond confirmed available quantity |
| FR-11 | Support allocations from one supplier to multiple projects | Example: 1,000 units → 600 to B + 400 to C |
| FR-12 | Produce at least one valid optimised allocation plan | Output includes supplier, receiver, quantity, and reason codes |
| FR-13 | Show two scenario comparisons (e.g. reuse-first vs carbon-aware) | Same input snapshot; differences explainable |

### C. Carbon-Aware Matching

| ID | Requirement | Acceptance check |
|---|---|---|
| FR-14 | Apply documented material production and transport factors | Units and factor provenance displayed |
| FR-15 | Estimate avoided new-production emissions, additional transport/processing and net avoided CO₂e | Calculation breakdown presented, including assumptions |
| FR-16 | Support carbon-aware selection/ranking among feasible allocations | Outcome can differ from a naive first-come allocation |
| FR-17 | Flag missing mass/factors/routes instead of inventing values | Incomplete cases marked `INSUFFICIENT_DATA` or handled with explicitly labelled assumptions |

### D. Transfer & Environmental Reporting

| ID | Requirement | Acceptance check |
|---|---|---|
| FR-18 | Request/approve/reserve material transfers with source and recipient confirmation | Recorded actor, status and timestamp |
| FR-19 | Prevent double booking of inventory | Two simultaneous reservations cannot exceed stock |
| FR-20 | Record dispatched, received and actually used quantities separately | Receiving stock is **not** automatically counted as reused |
| FR-21 | Store non-destructive transfer/audit events | Reuse record traces back to source and approval |
| FR-22 | Export CSV/JSON with confirmed reuse quantities and preliminary environmental estimates | Clear field definitions; no claim of carbon-credit issuance |

### E. Frontend / Demonstration

| ID | Requirement | Acceptance check |
|---|---|---|
| FR-23 | Provide dashboard, upload/review, match/carbon planner, and transfer/ESG views | Full workflow accessible from the UI |
| FR-24 | Demonstrate on synthetic 3–5-project scenario | Upload → review → optimise → approve → confirm reuse → export |

## 3. P1 improvements (if time remains)

| ID | Feature | Value |
|---|---|---|
| P1-01 | More PDF layout handling / OCR fallback | More flexible file intake; OCR should not be a dependency |
| P1-02 | Future Surplus Radar based on updated procurement/schedules | Proactive matching before stock becomes waste |
| P1-03 | Carbon sensitivity analysis / factor ranges | Show uncertainty in environmental conclusions |
| P1-04 | Automatic alerts before disposal/clearance deadlines | Rescue reusable materials in time |
| P1-05 | Versioned material catalogue + matching-rule configuration | Easier extension beyond initial material types |
| P1-06 | Dashboard of documented reuse vs simply diverted waste | Clearer sustainability metrics |

## 4. P2 roadmap (not required for current prototype)

- Approved API/ETL integration with SDP ERP, construction systems, BIM or procurement platforms.
- Approved structured integration to **Pantas**, while **Pantas remains the ESG system of record**.
- Broader material categories and industrial-grade eligibility/ownership checks.
- Full material passport / evidence vault with stronger enterprise controls.
- Independent assessment of carbon-credit methodology eligibility; **do not promise BCX revenue**.

## 5. Non-functional requirements

| ID | Requirement | Why |
|---|---|---|
| NFR-01 | Traceability | Every extracted item links to an original file and source row/page |
| NFR-02 | Deterministic constraints | Same specs/stock/requirements yield an explainable eligible set |
| NFR-03 | Atomic stock reservation | Avoid duplicate allocation under simultaneous requests |
| NFR-04 | Role separation / auditable approvals | Project owners and receivers have distinct responsibilities |
| NFR-05 | Unit and emissions accuracy | Never silently treat pieces as tonnes or generic CO₂ factors as exact |
| NFR-06 | Repeatable optimisation | Record solver objective, input snapshot and factor versions |
| NFR-07 | Resilience to imperfect documents | User can correct outputs; failure doesn't corrupt existing data |
| NFR-08 | ESG reporting boundaries | Avoided emissions remain separate from official inventory accounting |
| NFR-09 | Privacy and data access | Real contractor/procurement files require project-scoped permissions |
| NFR-10 | Honest MVP claims | Distinguish demo figures, forecasts and verified material reuse |

## 6. Acceptance scenarios your team can use as tests

**T1 — Correct AI classification.** Upload a BOQ for 2,000 blocks. Output should be `planned_requirement`, **not** 2,000 available blocks.

**T2 — Name normalisation.** `RECT CONC PAVER GREY 200X100X60` and `Grey concrete paver 200 × 100 × 60 mm` may map to same canonical material; conflicting thickness or grade must block/flag matching.

**T3 — Cross-project allocation.** Supply = 1,000 confirmed units. Demand B = 600; C = 400. Engine proposes 600+400 and cannot propose 1,100.

**T4 — Reservation race condition.** Two approval requests for the same remaining 500 units are processed; both cannot succeed for 500 units.

**T5 — Carbon comparison.** Two feasible transfer plans with different routes produce different estimated transport emissions. Both have cited or clearly synthetic factors.

**T6 — Incomplete carbon data.** Material lacks unit mass and there is no defensible per-unit factor; calculation returns incomplete, not invented kgCO₂e.

**T7 — Status accuracy.** A transfer moves `RESERVED` → `RECEIVED` but the impact dashboard's *actually reused* metric stays unchanged until `USED` confirmation.

**T8 — Pantas-ready export.** Export contains source/destination, material, mass/units, dates, evidence references, calculation assumptions, and a separate `estimated_avoided_kgco2e` field. Export does **not** claim official Pantas API integration or issued carbon credits.

## 7. Proposed sample data to collect or simulate

| Dataset | Why we need it | Practical starting point |
|---|---|---|
| 3–5 project records | Geographical context / different sites | **Synthetic**, labelled as demo |
| 20–50 construction line items | Exercise the document-extraction module | Real public descriptions, with simulated project fields |
| 10–20 surplus offers | Matching and quantities | Synthetic but plausible; status distinctions included |
| 10–20 demand requests | Multiple allocation plans | Synthetic requirements and dates |
| 2–5 material categories | Keep matching manageable | Unused paving blocks, bricks, tiles, etc. |
| Environmental factors | Carbon-aware ranking | Public documented factors, with units, region and boundary; fallback values labelled synthetic |
| Source documents | Demonstrate AI intake | Distinctly formatted CSV, XLSX and selected PDFs |

**Useful public references:**
- [OpenConstructionEstimate datasets](https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR) — construction line items; check licence.
- [buildingSMART IFC sample models](https://github.com/buildingSMART/IFC4.x-specification-models) — formal BIM structures.
- [Caltrans contract item data](https://sv08data.dot.ca.gov/) — real bid descriptions and quantities, not stock.
- [ÖKOBAUDAT](https://www.oekobaudat.de/en/service/downloads.html) — construction-product environmental data; adjust boundaries/geography before usage.

**Pantas boundary:** Treat `CircularFlow → ESG export → SDP-approved ESG workflow / potential Pantas import` as a **proposed data exchange**, not a live built integration. Never count an internal project transfer twice in consolidated reuse totals.
