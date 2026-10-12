# 00 — Terra product brief and system boundary

**Status:** Agreed hackathon product concept; requirements for prototype, not an existing deployed SDP system.  
**Documentation synchronised:** 2026-10-13. Synthetic seed baseline remains 2026-10-12.

## A. Elevator pitch

**Terra** is an AI-assisted operational decision platform for **cross-project reuse of unused construction materials**. It converts heterogeneous construction records into reviewable, standardised material information; uses deterministic constraints and optimisation to connect surplus to future demand; evaluates potential environmental impact; then records actual transfers and evidence that can contribute to ESG review.

**One-line business workflow:** Existing construction data → AI interpretation + human review → verified supply/outstanding demand → compatible allocations → carbon-aware comparison → approval/reservation → dispatch/receipt/confirmed use → ESG-ready export.

The product is **not** merely a classified marketplace for users to manually list every leftover material. Its differentiator is actionable discovery from existing records and **cross-project optimisation** with traceable decisions.

## B. Problem and evidentiary boundary

Construction projects can simultaneously hold unused materials and buy new ones. Fragmented descriptions, timing, stock availability and cross-project logistics can make reuse difficult. Terra proposes to help find and evaluate these opportunities.

SDP's public sustainability reporting and existing initiatives demonstrate that construction waste and environmental reporting matter. **No public evidence in the supplied sources establishes that SDP lacks any existing cross-project material transfer platform, or that any specific quantity of reported waste is reusable surplus.** Do not assert either as fact in the product or pitch.

**Pantas** is an existing ESG management/reporting provider used in SDP sustainability processes. Terra is a *proposed upstream operational material-decision layer*. CSV/JSON exports could eventually be considered for an SDP-approved exchange; **there is no confirmed Terra-to-Pantas API or live integration**.

## C. Four capabilities and ownership boundaries

### 1. AI Material Intelligence (core; future raw-file input)

- CSV/XLSX and selected text-based PDFs, progressively.
- Classify document type (BOQ, purchase order, inventory, demand/requirements).
- Extract material, amount, unit, dimensions, finish/grade, project, date, source locator; retain original text.
- Suggest canonical material mapping and semantic equivalents with uncertainty flags; the single operator can correct and accept.
- Does **not** infer physically confirmed surplus solely from BOQ arithmetic or LLM confidence.
- For the first seed-database implementation, use **simulated extracted rows only**; don't pretend actual LLM output exists.

### 2. Circular Optimisation Engine

- Consider verified `CONFIRMED` supplies and outstanding/project-validated demands.
- Enforce material category/specification/unit compatibility, project timing and quantity.
- Allocate one supply to multiple demands; avoid over-allocation on source **and recipient** sides.
- Produce explainable alternative plans (`MAX_REUSE`, `MAX_NET_CO2E_AVOIDED`, `EARLIEST_DEADLINE`).
- May use OR-Tools later, but begin with a deterministic feasible baseline.

### 3. Carbon-Aware Matching

- Compare avoided production from genuine material substitution with additional transport and handling/processing impacts using explicit factor units and baselines.
- Rank feasible alternatives; missing inputs produce an incomplete evaluation, not fabricated precision.
- Estimates are not carbon credits or official emissions-inventory reductions.

### 4. Transfer Tracking, ESG Export and later Evidence Vault

- Record approval simulation, reservations, dispatch, receipt and actual reuse, with append-only event history.
- Distinguish proposed, committed and actually used quantities.
- Export project/material/quantity/evidence and environmental calculations as machine-readable CSV/JSON.
- Full evidence vault and carbon-credit eligibility assessment belong to future roadmap, not MVP.

## D. MVP screens (context for seed fields; no UI implementation required yet)

1. **Overview:** overall materials, confirmed supply, open demand, transfers, historical reuse and estimated environmental metrics.
2. **Projects & Materials:** project catalogue, stock and demand with filters.
3. **AI Intake & Review:** uploaded-document list, synthetic/real extraction rows, corrections and review statuses.
4. **Matching, Transfer & ESG:** allocation comparison and rationale, transfer status/history, outcomes and export.

These are conceptual areas, not a requirement to build all pages immediately.

## E. Personas / user accounts

Single operator controls the hackathon app. There are **no application accounts, login, sessions, role permissions or user/role tables**. The UI can simulate project-side confirmations via fields/events such as `source_confirmation_status`, `destination_confirmation_status`, `actor_label: "Demo operator"`; no real multi-party attestation is implied. Server-to-database authentication is a separate technical requirement.

**Security caveat:** Single-user does **not** mean exposing privileged mutations publicly. A shared demo with no authentication needs server-side gated privileged writes or a deliberately read-only public deployment; see architecture document.

## F. Material eligibility

Initial supported classes: **new/unused, traceable, standardised, primarily non-structural** concrete paving blocks, bricks and ceramic tiles. No claim Terra can certify structural suitability, hazardousness, code compliance or guaranteed functional equivalence. Spec mismatches and missing grade/finish information block or flag recommendations.

## G. Project scope timeline

The chosen application architecture is **React + TypeScript + Tailwind CSS → FastAPI → independent Python processing/domain services → Python REST adapter → Firebase Data Connect / SQL Connect → Cloud SQL PostgreSQL**. All application operations use FastAPI. The backend owns intake, analysis, optimisation, transfers and carbon calculations; browser code renders their results. The adapter's authentication and connectivity require a proof before full integration. Node.js is limited to Firebase tooling or justified one-off utilities; there is no separate Node application backend.

Focus first on the **Option B seed foundation** for a working existing-looking app; then integration/API; then AI document parsing (Member 2 will provide raw test files later); then optimisation/ESG/demo. Hackathon first submission is expected 23 October 2026; prioritize reproducibility and credible evidence over production-level integrations.

These are future milestones, not authorization to start them. The completed review changed documentation only; the separately authorized local seed milestone is documented in LOCAL_DEVELOPMENT.md. Python hosting and public-demo access controls remain undecided.

## H. Non-goals

No structural engineering certification, contractors' ERP replacement, actual transportation operation, real SDP inventory access, live Pantas/ERP/BIM integration, full carbon LCA/credit issuance, paid infrastructure dependency, multi-user RBAC, real procurement pricing promises, or uncited Malaysian emission factors.
