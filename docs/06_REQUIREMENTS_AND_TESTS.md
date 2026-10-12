# 06 — Requirements, traceability and automated acceptance criteria

This supersedes `legacy/CircularFlow_Requirements_v0.1.md` where it assumed multiple users/role-based access and implied raw document uploads are present in the initial seed. Existing FR IDs are intentionally retained as much as possible.

These are future acceptance targets. The earlier documentation review ran consistency checks only. Local seed implementation evidence is now in SEED_VALIDATION.md; these criteria still do not authorize full application APIs. The confirmed runtime is React/TypeScript/Tailwind → FastAPI → independent Python services/repositories → Python REST adapter → Firebase SQL Connect → Cloud SQL PostgreSQL. Application operations use FastAPI; Python database authentication/read-write behavior remains to be proven. Node.js is limited to tooling and justified one-off utilities.

## 1. Priority definitions

- **P0-SEED:** needed now to make a consistent populated database and local implementation tests.
- **P0-MVP:** needed in the complete hackathon demonstration, but **not** necessarily part of Codex's first seed task.
- **P1:** enhancements only if time remains.
- **P2:** future enterprise roadmap; do not implement now.

## 2. Functional requirements (source: original FR-01 through FR-24, updated to Terra)

| ID | Priority | Requirement and demonstrable acceptance |
|---|---|---|
| FR-01 | P0-SEED | Store/list 5 synthetic distinct projects with stable IDs, names, townships and date fields from Document 02. |
| FR-02 | P0-MVP | Parse known CSV/XLSX and selected text PDFs when raw docs are provided later. |
| FR-03 | P0-SEED + MVP | Distinguish BOQ, PO, inventory, demand; accepted BOQ must not become confirmed surplus. |
| FR-04 | P0-SEED + MVP | `extracted_rows` contract includes name, amount, unit, specs, dates and source locator; seeded rows are explicitly synthetic. |
| FR-05 | P0-SEED + MVP | Different raw names can map to same canonical ID; different critical specs do not map automatically. |
| FR-06 | P0-SEED + MVP | Confidence/review flags and correction fields represented now; review UI later. |
| FR-07 | P0-SEED + MVP | Unreviewed rows do not automatically publish confirmed supply or demand. |
| FR-08 | P0-SEED | Store separate confirmed/potential supply and outstanding demand, with status/quantity rules. |
| FR-09 | P0-MVP | Matching respects critical specs/units; incompatible fixture produces ineligibility. |
| FR-10 | P0-SEED + MVP | Dates and quantities consistent; no over-allocation, including recipient commitments. |
| FR-11 | P0-SEED + MVP | Seed one-to-many allocation example and implement matching later. |
| FR-12 | P0-SEED + MVP | Seed explainable historical run/proposals; optimiser later generates fresh run. |
| FR-13 | P0-SEED + MVP | Include two comparable alternative strategy runs; do not count both as execution. |
| FR-14 | P0-SEED | Store demonstrative, explicitly labelled factor values, units and provenance. |
| FR-15 | P0-SEED + MVP | Seed impact records reproduce from stored factors; live calculator later. |
| FR-16 | P0-MVP | Carbon-aware algorithm can rank valid alternatives, not just nearest supplier. |
| FR-17 | P0-SEED | Unknown unit mass/routes/handling/factors yield `INSUFFICIENT_DATA`, not invented emission outputs. |
| FR-18 | P0-SEED + MVP | Single-user status-based approvals (NO users/RBAC schema). Seed sample states; later implement transitions. |
| FR-19 | P0-SEED + MVP | Source/destination counters reconcile; later test truly atomic concurrent reservation mutation. |
| FR-20 | P0-SEED | Separate dispatched, received and actually used; `RECEIVED` not automatically `REUSED`. |
| FR-21 | P0-SEED | Append-only-style transfer events and chronological history in seed. |
| FR-22 | P0-MVP | CSV/JSON export of actual reused quantities and estimates, with Pantas disclaimers. |
| FR-23 | P0-MVP | Overview, documents/review, supply-demand/matching, transfer/ESG UI. |
| FR-24 | P0-MVP | E2E demo on synthetic projects: review → verify supply/demand → match → confirm/approve → reserve → dispatch → receive → confirm use → export. |

## 3. Nonfunctional requirements

| ID | Requirement |
|---|---|
| NFR-01 | Traceability: store source file metadata / row/page; synthetic stub labels must be explicit. |
| NFR-02 | Explainable deterministic eligibility: factor, material, date and quantity decisions can be reproduced. |
| NFR-03 | Atomic stock consistency: no reservations exceeding confirmed stock or demand need. |
| NFR-04 | **Single-user adaptation:** workflow confirmations through statuses/events only; no role-based auth for MVP. Enterprise controls future. |
| NFR-05 | Unit correctness: reject invalid or ambiguous conversions; no pieces-to-tonnes without mass. |
| NFR-06 | Reproducibility: stable seed, run IDs, objectives, input snapshots, factor version. |
| NFR-07 | Error isolation: invalid extracted data cannot corrupt supply or demand. |
| NFR-08 | ESG boundary: distinct avoided emission estimates vs official corporate inventory/carbon credits/waste diversion. |
| NFR-09 | Demo security: no secrets/public privileged writes; repository contains synthetic, non-sensitive data. |
| NFR-10 | Honest claims: source distinctions, limitations, synthetic values, no fake integration or real AI calls. |
| NFR-11 | Idempotent seed: repeat command does not inflate stock, events or carbon. |
| NFR-12 | Provider compatibility: actual `.gql` schema/connector operations compile on Firebase SQL Connect emulator, or blockers are explicitly recorded. |
| NFR-13 | Python integration proof: demonstrate named REST read/write/read-back with verified credentials/routing, operation error handling and replay-safe behavior; distinguish local/cloud results and blocked steps. |
| NFR-14 | Module separation: business calculations/transitions can be tested as Python functions without FastAPI or Firebase. React uses FastAPI; no persistent Node application backend. |

## 4. Seed-specific acceptance scenarios: expected results

| Test | Given | Expected |
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
| A22 | Same 500 pcs confirmed stock, two concurrent reservation commands each 500 | At most one succeeds; later MVP test if not part of initial seed task. |
| A23 | Scenario index IDs in README | Every listed scenario ID has valid referenced records. |
| A24 | Data source assertions | Every example has `synthetic=true` metadata; real-file URI/hash absent; factors labelled demo. |
| A25 | Minimal standalone Python REST adapter proof | Read/write/read-back and repeat behavior observed through named operations; authentication/authorization, routing and errors documented. No full FastAPI server required. |
| A26 | Historical partial reuse and current commitments | Actual-use quantity counts once; unused/missing residuals explained and not silently released/restocked. Undefined cost allocation leaves net incomplete. |

Tests A01–A21/A23–A26 are seed milestone targets. A25 may remain explicitly blocked if a safe Python path cannot be proven; Node import success does not pass it. A26 requires documented fixture assumptions and must flag unresolved closure/cost policy from Document 07 rather than invent a rule. A22 requires operational transactional mutation implementation and can be documented as an explicit subsequent task if first implementation scope stays seed-only. Later concurrency coverage must include two sources competing for the same recipient need as well as two requests competing for the same stock.

Historical eligibility uses the run's saved inputs and event time; new reservation uses current stock, demand and confirmation state. Do not reject a valid past transfer solely because its stock is now depleted or demand fulfilled. For immediate baseline impact checks, use one assessment per entity/basis; later revisions need an explicit authoritative-record rule.

## 5. P1 and P2

**P1:** expanded PDF layouts/OCR, future surplus predictions, sensitivity analysis, alerts, advanced material matching rules, richer waste prevention vs diversion charts.

**P2:** real SDP ERP/BIM and Pantas connectors (only with permission and provided specs); enterprise identity and project access policy; evidence vault; verified lifecycle calculations; investigate but **do not promise** carbon-credit certification/BCX revenue.

## 6. Demo/dashboard fixture queries to support

- Projects grouped by location/status.
- Materials grouped by category.
- Confirmed eligible supply remaining by material/category/project.
- Potential supply shown separately, never included in "ready to reserve".
- Open/committed demand by category; not summed across incompatible units.
- Count of proposals by run/strategy/status.
- Transfers by current workflow stage and date.
- **Confirmed** material reuse mass (not dispatch or receipts), separately from proposal forecast.
- Estimated actual carbon outcome with missing-factor/assumption flags.
- Synthetic ESG export preview (future read model).
