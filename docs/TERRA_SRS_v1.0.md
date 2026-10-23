# Terra — Software requirements specification

**Approved baseline:** v1.0,13 October 2026. **Consolidation:**24 October 2026, incorporating approved ingestion, exact-runtime, transfer and interface amendments without adding product scope. Original requirement IDs remain stable. This is a team prototype specification, not an official SDP specification.

The SRS defines product requirements. Documents 00-08 define the associated domain/interface details; Document 09 is the architecture authority. Implementation history and agent permission diaries are not additional product requirements.

## Purpose and objectives

Terra connects unused construction materials at source projects with compatible needs at recipient projects. It supports document interpretation, human verification, quantity/eligibility checks, allocation alternatives, physical-use tracking and traceable environmental comparison. No claim is made that SDP lacks an existing platform or that Terra can access its inventory. Live ERP/Pantas integration is not implemented.

| ID | Objective |
|---|---|
| OBJ-01 | Improve visibility of unused material and outstanding cross-project demand. |
| OBJ-02 | Reduce manual processing of differently formatted construction documents. |
| OBJ-03 | Identify and optimise feasible reuse opportunities subject to technical and operational constraints. |
| OBJ-04 | Evaluate estimated environmental outcomes under clearly disclosed assumptions. |
| OBJ-05 | Track the chain from proposal to reservation, transport, receipt and actual reuse. |
| OBJ-06 | Export traceable information to support internal ESG review and a possible future approved Pantas exchange. |

## Scope and architecture

One operator manages all projects. No application users, login, roles or sessions are part of the prototype. Confirmation labels are workflow evidence, not independent corporate signatures. Server/database credentials and access protection are separate requirements.

React/TypeScript/Tailwind calls FastAPI; framework-independent Python services own processing/business rules; repositories use a Python named SQL Connect REST adapter. Development uses the local persistent emulator. A shared Cloud SQL-backed service is a separately approved target, not a configured production deployment. No persistent Node application backend or direct PostgreSQL/Supabase replacement is selected.

Included capabilities are project/material catalogue, supported document/manual intake, review, atomic batch publication, stock/local-need/release/demand analysis, three-objective matching, combined individual confirmation/reservation, full dispatch/receipt, repeated actual use, current carbon revisions and CSV/JSON export. The first integrated local version exists; this is not a claim that every acceptance scenario passed.

Excluded scope includes live ERP/BIM/Pantas integration, engineering certification, real logistics/payments, price/financial-savings tracking, full LCA, official inventory deduction, carbon credits, enterprise identity, public hosting and expanded condition/partial-shipment/return management. Unknown physical discrepancies remain explicit rather than falsely recorded as full receipt or reuse.

## Terms

| Term | Meaning |
|---|---|
| Planned requirement/BOQ | Planned work/material amount; not physical stock or confirmed demand by itself |
| Purchase order | Ordered supply; not proof of delivery |
| On-hand stock | Physical material observed at a source/time/scope |
| Remaining local requirement | Unfinished local need before applying stock |
| Outstanding demand | Uncovered need, already net of applicable stock; still subject to fulfilment/incoming commitments |
| Potential surplus | Possible excess; not reservable |
| Confirmed surplus | Identified unused/owned/traceable material explicitly released, subject to eligibility |
| Proposal | Deterministic recommended allocation; no hold or physical event |
| Transfer | Explicitly confirmed/reserved movement and later physical stages |
| Actual use | Recipient-confirmed use, counted once |
| Environmental estimate | Comparative calculation with factors/boundary, not a credit or official GHG deduction |

## Functional requirements

P0-SEED denotes the canonical demonstration foundation; P0-MVP denotes the complete local prototype requirement. Future/optional labels do not authorise new work.

| ID | Priority | Requirement |
|---|---|---|
| SRS-FR-01 | P0-SEED | Store stable project identifiers, names, locations/townships and lifecycle/status fields. |
| SRS-FR-02 | P0-SEED | Store canonical material categories, critical specifications, explicit base unit and defensible unit mass when available. |
| SRS-FR-03 | P0-MVP | Browse and filter projects, materials, surplus and demand through FastAPI-backed UI views. |
| SRS-FR-04 | P0-MVP | LLM-led broad intake including spreadsheets, Word, PDFs/scans and images where readers/model support them; optional preprocessing, no forced templates or arbitrary row cap; explicit failures for unsupported content. |
| SRS-FR-05 | P0-MVP | Classify source type as BOQ, purchase order, inventory, demand or other. |
| SRS-FR-06 | P0-MVP | Extract raw descriptions, quantity, unit, dates, technical properties and page/sheet/row references. |
| SRS-FR-07 | P0-MVP | Suggest canonical mappings or new material drafts through controlled tools; operator reviews entries inside document review. Registration may extend beyond seed categories; suitability is not automatic. |
| SRS-FR-08 | P0-SEED + MVP | Preserve original content, normalised fields, source provenance, uncertainty, source type and review information. |
| SRS-FR-09 | P0-MVP | All items accepted/corrected or explicitly excluded; direct overrides without written reasons and deliberate bulk acceptance. Per-file approval/audit; only fully resolved approved batch publishes atomically. Flag assumptions/conflicts for confirmation. |
| SRS-FR-10 | P0-SEED + MVP | Reject automatic publishing of unreviewed BOQ/PO/inventory rows as confirmed surplus; prevent reprocessing from duplicating operational quantities. |
| SRS-FR-11 | P0-SEED + MVP | Keep BOQ requirements, POs, recorded stock, potential surplus, confirmed surplus and outstanding demand semantically separate. |
| SRS-FR-12 | P0-MVP | Calculate possible excess stock **only where complete, validated stock and remaining-project-need inputs exist**. |
| SRS-FR-13 | P0-SEED + MVP | Maintain separate `POTENTIAL` and `CONFIRMED` states; source-project release confirmation remains a deliberate action. |
| SRS-FR-14 | P0-SEED + MVP | Calculate newly allocatable demand after subtracting fulfilled quantity and active incoming commitments; do not infer all BOQ quantities remain needed. |
| SRS-FR-15 | P0-SEED + MVP | Never reserve potential, suspended or unverified supply. |
| SRS-FR-16 | P0-MVP | Check material/specification, condition, measurement-unit and date compatibility before suggesting an eligible match. |
| SRS-FR-17 | P0-MVP | Expose rejection or `REVIEW_REQUIRED` explanations when compatibility cannot be established. |
| SRS-FR-18 | P0-MVP | Produce feasible proposals without exceeding confirmed supply or uncommitted demand. |
| SRS-FR-19 | P0-MVP | Allocate one source to multiple demand projects when valid; allow partial fulfilment. |
| SRS-FR-20 | P0-MVP | Compare at least reuse-maximising and carbon-aware optimisation objectives on the same input snapshot. |
| SRS-FR-21 | P0-SEED + MVP | Retain optimisation run objective, assumptions, input/factor version, plan and reason codes; proposed plans never reserve stock automatically. |
| SRS-FR-22 | P0-SEED | Store factor value, unit, applicability, provenance, geography, calculation boundary, dataset version and synthetic/verified status. |
| SRS-FR-23 | P0-MVP | Calculate estimated avoided production only against a justified equivalent-new-material baseline. |
| SRS-FR-24 | P0-MVP | Calculate added transport from **actual transported mass**, route length and suitable tonne-km factor where available. |
| SRS-FR-25 | P0-MVP | Derive net avoided CO₂e only when required baseline, transport and handling/processing inputs exist; otherwise mark `INSUFFICIENT_DATA`. |
| SRS-FR-26 | P0-MVP | Compare carbon outcomes across feasible plans; negative or incomplete outcomes are valid. |
| SRS-FR-27 | P0-MVP | Distinguish forecast proposal assessments from actual-use assessments and support versioned revisions. |
| SRS-FR-28 | P0-MVP | Create a transfer from a currently eligible selected proposal through explicit combined confirmation/reservation; retain legacy request compatibility. |
| SRS-FR-29 | P0-MVP | Capture simulated source/destination confirmation states without user accounts. |
| SRS-FR-30 | P0-MVP | Atomically reserve quantities on both supply and demand sides, rechecking current eligibility and balances. |
| SRS-FR-31 | P0-MVP | Track dispatched quantity and timestamp separately from approved/reserved amounts. |
| SRS-FR-32 | P0-MVP | Track received quantity and timestamp separately from dispatch. |
| SRS-FR-33 | P0-MVP | Record actual reuse separately from receipt; allow later additional-use confirmation of valid remaining material. |
| SRS-FR-34 | P0-MVP | Keep chronological append-only-style operational events and corrections. |
| SRS-FR-35 | P0-MVP | Preserve cancellation/residual/discrepancy integrity; current operations support pre-dispatch cancellation and repeated use, with partial-delivery/return/damage/discard resolution deferred. |
| SRS-FR-36 | P0-MVP | Display inventory, confirmed reservable surplus, potential surplus and outstanding demand with appropriate unit grouping. |
| SRS-FR-37 | P0-MVP | Display allocation proposals and transfer event/status history separately from actual reuse. |
| SRS-FR-38 | P0-MVP | Calculate confirmed actual reuse from valid completed-use records without double counting. |
| SRS-FR-39 | P0-MVP | Present carbon assessments, factor/source caveats, assumptions and incomplete flags; distinguish forecasts and actual outcomes. |
| SRS-FR-40 | P0-MVP | Export traceable CSV/JSON reuse and environmental summaries for internal review and potential future approved Pantas integration. |

## Binding workflow clarifications

### Document interpretation and review

- Operators upload files blindly or with a project hint; both multi-file and multi-project evidence are supported. Unknown identity remains provisional, not forced into the hint.
- LLM-led interpretation uses controlled Terra read/proposal tools and trusted classification/family prompts. Services/preliminaries remain source coverage; they are not forced into material requirements. Grounded implied materials carry inference explanation; unknown quantities are not copied from work measurements.
- Saved extraction is reconciled in a separate read-only stage against fresh stored records, then batch-cross-checked. Models and temporary proposals remain isolated. Ordinary analysis uses the explicit saved primary; comparison is deliberate.
- DeepSeek uses HIGH reasoning. Account usage is tracked without a spending cutoff. Provider dashboards are billing authority; no automatic provider substitution or repeated uncertain paid request is implied.
- Every included item must be resolved. One explicit prepared file approval may accept all displayed supported recommendations/identities/conversions and applicable stock/release acknowledgements. It is not confidence-based auto-approval. Operator changes need no written reason; exclusion is a valid resolution.
- Original sources/model output and operator overlays remain separate. Whole-source viewing is sufficient; no compulsory chat, excerpts, external product lookup or fixed document template is required.
- Manual information has operator provenance and independent approval. Failed files must succeed, be explicitly skipped or be replaced by reviewed manual information before the whole approved batch can publish.
- Added files/retries preserve compatible completed work and operator edits, with affected approvals revalidated. Published evidence is read-only; corrections use new evidence. Unsupported/ambiguous/truncated candidates never publish partially.

### Quantity and identity rules

Use exact validated quantities, explicit units and product-specific confirmed conversions; preserve originals and reject unsupported precision/discrete fractions without rounding. The canonical13-array seed remains unchanged with baseline 2026-10-12; current runtime uses open-ended category/unit strings and Int64 millionths.

Observations use ADD, exact-predecessor REPLACE or HISTORY_ONLY, with excluded values omitted. Preserve project/document/material scope and superseded history. Stock-based calculations require complete non-overlapping input acknowledgement. Confirmed surplus is part of stock; direct net demand is not reduced by stock twice. Valid unrelated facts can publish when a surplus/demand calculation is unavailable.

Shared published/operator-reviewed catalogue identity and consistent specifications/units establish the material boundary. Unfamiliar category labels do not invoke a hardcoded whitelist or family-specific checklist. Distinct IDs are not automatically equivalent. Known conflicts, traceability, release, condition, suitability, budgets and timing remain guarded; no engineering certification is inferred.

### Matching and transfer rules

Matching follows committed relevant changes across all projects for affected materials. Draft uploads/edits do not invoke it. A newer dependency/day makes old recommendations unusable without invalidating existing transfers. Future opportunities remain visible, but can confirm only when current guards permit.

MAX_REUSE maximises comparable-unit quantity, then required-by deadline, earliest feasible arrival, shorter applicable route and stable IDs. EARLIEST_DEADLINE maximises deadline groups lexicographically. Carbon maximises valid linear net benefit, with quantity and the documented tie ordering afterward. Unknown/negative scores may exclude pairs from carbon allocation without excluding an otherwise eligible reuse/deadline pair. Equal plans are valid; alternative plans are not summed.

Choose a starting plan, then confirm transfers individually. The normal transition is:

```text
current proposal → explicit confirmation + atomic reservation → RESERVED
→ full dispatch → IN_TRANSIT → full receipt → RECEIVED
→ positive actual-use increments → REUSED
```

REQUESTED/APPROVED are historical compatibility states, not a normal approved-but-unreserved stage. Reductions before confirmation require fresh checks/forecast. A reserved quantity change requires pre-dispatch cancel/release/fresh confirmation, never in-place amendment. No reject/dismiss/snooze feature is selected.

Full receipt is required by this version. Received-but-unused quantities remain committed to the recipient and can be used later; no automatic return/re-offer occurs. Post-dispatch cancellation, shortage, partial shipment, return/damage/discard processing are deferred. Original OD-01 discrepancy examples remain integrity requirements for retained evidence and future resolution, not permission to create false full receipts now.

For confirmed offerQ, active hold R and dispatched D: available=max(0,Q-R-D), withR+D≤Q. For demand N, used fulfilment F and active incoming C: newly allocatable=max(0,N-F-C), with F+C≤N. Used≤received≤dispatched≤approved≤proposed. Every coupled effect is atomic/replay-safe.

### Carbon and current reporting

Production avoidance uses used quantity; freight and combined handling use moved quantity. Factor selection checks material/category/general specificity, dimensions, version, valid date, mode and boundary. Missing/ambiguous/incompatible inputs leave unknown components/net, not zero. Production/processing accept a compatible per-catalogue-unit or explicit mass basis; freight uses tonne-km.

Recalculations preserve immutable assessment revisions and advance one current head per scope. Saved use/applicable confirmed corrections enqueue durable impact work atomically. Physical use stays saved when calculation fails; pending/failed scopes exclude stale current figures. A completed calculation can still have insufficient data. No forecast+actual double counting or repeated physical-use command occurs on retry.

Demonstration factors remain labelled. Material weight and route estimates need explicit confirmation/basis; factor dataset preparation is separate from document ingestion. No official GHG inventory deduction, verified diversion, carbon-credit issuance or live Pantas exchange follows from a reuse entry.

## Nonfunctional requirements

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

### Performance targets

Dashboard/listing 2 s, small CSV/XLSX extraction 30 s, selected text PDF 45 s, baseline optimisation 10 s and confirmation/reservation 2 s are initial representative-environment targets, not measured SLAs or universal file limits. The owner accepts longer complete model processing with truthful progress. Measure preparation, provider latency and batch work separately; never truncate evidence or publish early to meet a target.

## Business rules

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
| SRS-BR-15 | MAX_REUSE preserves maximum quantity, then prioritises earliest demand deadline, earliest feasible delivery, shorter route and stable ID; see the allocation policy below. |
| SRS-BR-16 | App is local/single-user; shared cloud data requires separately configured and approved access. |

SRS-BR-09 preserves discrepancy/residual integrity, with active exception processing limited to the current full dispatch/full receipt and pre-dispatch cancellation contract. SRS-BR-11's authoritative revision selection uses current validated source/head/intent state; no additional routine manual calculation click is required after confirmed use.

## Acceptance scenarios

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
| SRS-AT-15 | Maximum-quantity feasible allocations | Earlier demand deadline, then earlier feasible delivery, shorter distance and stable ID decides order without reducing the maximum quantity. |
| SRS-AT-16 | Re-upload same source row / repeated action | No duplicate published supply, reservations, events or impact. |
| SRS-AT-17 | Dashboard forecast and actual assessment | Never sums both as actual achievement. |
| SRS-AT-18 | Local development fresh checkout | Can initialise emulator and load reproducible seed without cloud credentials. |
| SRS-AT-19 | Local frontend and FastAPI; integrated shared cloud database | Local apps use approved server-side connection and see the same persisted records, after separate cloud configuration. |
| SRS-AT-20 | Representative local environment and sample data | Evaluate five performance targets, record observed measurements and any failed target. |
| SRS-AT-21 | Completed scenario | Operator can demonstrate upload → review → surplus/demand → optimisation → compare → reserve → dispatch → receive → reuse → export. |

These are acceptance criteria, not a claim that every listed case has run. SRS-AT-09 covers retained/future discrepancy integrity; the current UI does not create partial receipts. SRS-AT-19 requires separately approved cloud work. Test commands, evidence boundaries and deferred coverage are in [Document 06](06_REQUIREMENTS_AND_TESTS.md).

## Approved decision traceability

The original OD-01–OD-08 identifiers remain traceable with current approved clarifications:

| ID | Current interpretation |
|---|---|
| OD-01 | Preserve receiver residuals and discrepancies; later positive use is implemented, return/damage/discard and partial shipment processing are deferred. |
| OD-02 | Used quantity for production substitution, full moved quantity for transport/handling. |
| OD-03 | Immutable assessment revisions and one authoritative current head, refreshed automatically after applicable confirmed changes. |
| OD-04 | Human review; supported recommendations accepted by one explicit file approval, never AI confidence. |
| OD-05 | MAX_REUSE deadline precedes delivery, route and stable IDs after maximising quantity. |
| OD-06 | Local single-operator application; public hosting/access is not configured. |
| OD-07 | Persistent local SQL Connect emulator; shared cloud database requires explicit configuration/approval. |
| OD-08 | Representative performance targets with truthful actual measurements and accepted long model processing. |

## Data, interfaces and change control

Core entities remain projects, materials, documents, extracted rows, supply offers, demand requests, route distances, optimisation runs, allocation proposals, transfers/events, emission factors and impact assessments. Runtime adds provisional batch/revisions, immutable source contributions/supersession/stock scopes, transaction guards, matching generations, impact heads/intents and workspace identity. No account/role tables are introduced. [Document 02](02_DATA_MODEL_CONTRACT.md) contains fields and provider distinctions.

All application operations use the FastAPI boundary, with runtime schemas and OpenAPI as the implemented transport reference. Named connector operations remain server-side. Exports preserve source, material, projects, quantity/unit, factor/boundary and current assessment provenance; proposed Pantas-ready exchange is not actual integration.

Requirements change only through explicit owner/team decisions. Consolidation removes obsolete execution narration while preserving stable IDs, normative safety rules, known exclusions and supersession. Unresolved implementation/acceptance limitations must be reported, not silently filled by assumptions. The canonical seed and stored owner records are never rewritten as part of documentation maintenance.
