# 07 — Decision log, provenance and unresolved implementation choices

## A. Confirmed project decisions through 2026-10-13

Document 09, effective 13 October 2026, is the authoritative architecture decision. Documents 00–08 and prompts have been synchronised to it. The documentation review did not implement or test the application/database. The subsequent authorized local seed results are in SEED_VALIDATION.md; no application server was built.

| Topic | Decision | Replaces / affects |
|---|---|---|
| Name | **Terra** | All new documents/code use Terra; old title CircularFlow is historical only. |
| Data approach | **Option B**: pre-populated operating system baseline | Not a bare empty catalogue. |
| User model | **Single user, no users/roles/auth tables** | Legacy multi-role requirements are superseded. |
| Database | **Firebase SQL Connect / PostgreSQL**, local emulator first | Earlier generic PostgreSQL/Supabase assumptions revised. |
| Frontend/API | **React + TypeScript + Tailwind CSS → FastAPI** for all application operations | No direct Firebase browser data path or optional backend framework. |
| Business processing | Framework-independent **Python** services for ingestion, analysis, optimisation, transfers and carbon | FastAPI routes validate/orchestrate; services can be tested directly. |
| Database adapter | **Python REST adapter** executing documented named SQL Connect operations, subject to proof | No assumed Python Admin SDK parity, Node runtime bridge or direct SQL fallback. |
| Node.js | Firebase CLI/build tooling and justified one-off Admin utilities only | No persistent Node.js application backend. Prefer Python seeding after proof. |
| Hosting/security | Python hosting and public-demo controls undecided; credentials server-side | No app accounts does not mean public privileged access. |
| Source of truth | Versioned portable synthetic JSON + generated/mapped DB schema | Runtime DB changes must not rewrite seed fixture. |
| Seed first | Yes | Raw PDF/CSV/XLSX construction test documents come later from Member 2. |
| Material scope | New/unused non-structural pavers, bricks, tiles | No uncertified structural material auto-approval. |
| AI | Interpretation, parsing, normalization, uncertain suggestions | LLM does **not** physically confirm stock or own quantity arithmetic. |
| Matching | Deterministic constraints + optimiser | LLM similarity insufficient for technical compatibility. |
| Carbon | Transparent comparative estimates, explicit incomplete-data status | Never automatically claim corporate emissions deductions, carbon credits or waste-diversion tonnage. |
| ESG/Pantas | Future reviewed CSV/JSON exchange only | No live Pantas API, credentials or schema known. |
| Historical records | Seed contains real-looking but **synthetic** history dated before as-of | Enables operational dashboard without fake SDP figures. |

## B. Source file provenance

The owner supplied these **legacy v0.1 project files** on 12 October 2026:

- `legacy/CircularFlow_Data_Model_v0.1.md` — original 12-entity proposal, FK/source types, conservation rules and sample DTOs.
- `legacy/CircularFlow_Requirements_v0.1.md` — original FR-01 to FR-24, P1/P2, NFR and acceptance checks. It still assumes multiple actors/user-role considerations; these are **no longer MVP requirements**.
- `legacy/CircularFlow_Example_Scenario_v0.1.json` — **four projects, one paving-block specification**, two supplies, two demands, 4 route distances, two illustrative emission factors and one proposed plan; explicitly synthetic. It is a regression example, **not** the final required 5-project seed or a completed transfer.

`docs/00`–`docs/08` are **design synthesis** informed by those files and the owner's explicit subsequent decisions, now synchronised with Architecture Update v1.1 in Document 09. They are not copied from SDP or Firebase's internal schema. The legacy Markdown has archival notices; its original bodies and the legacy JSON are preserved. `MANIFEST.sha256` remains the original handoff inventory, not checksums of this updated documentation.

### Changes to old model specifically worth noticing

1. Added `route_distances` as first-class array/table, since legacy JSON had them but 12-entity document did not.
2. Chose stable **string** IDs for the JSON instead of old draft UUID fields, as explicitly agreed for seed/import readability.
3. Added `dispatched_quantity` and active `reserved_quantity` at transfer level for correct stock conservation; old transfer example had only approved/received/used, insufficient to reconcile dispatch.
4. Added demand `is_outstanding_need_confirmed` and recipient **active incoming commitment** semantics; a BOQ entry is not automatically open demand.
5. Made `documents` stubs truthful: no actual files or file hashes, extracted rows synthetic, until raw docs supplied.
6. Replaced project-approver/auth user identities with demo confirmation statuses and `actor_label` only.
7. Added consistent baseline date to avoid future completed transactions.
8. Added explicit `INSUFFICIENT_DATA` environmental state and strategy alternative non-additivity.

## C. External technical references (official)

**Firebase SQL Connect (formerly Firebase Data Connect):**

- Product and quickstart: https://firebase.google.com/docs/sql-connect/quickstart
- Architecture and schema/connector management: https://firebase.google.com/docs/sql-connect/manage-schemas-and-connectors
- Schemas and `@table`/`@ref`: https://firebase.google.com/docs/sql-connect/schemas-guide
- `@transaction` and `@check`: https://firebase.google.com/docs/sql-connect/mutations-guide
- Data seeding / bulk: https://firebase.google.com/docs/sql-connect/data-seeding-bulk-operations
- Node Admin SDK: https://firebase.google.com/docs/sql-connect/admin-sdk
- REST named query: https://firebase.google.com/docs/reference/sql-connect/rest/v1/projects.locations.services.connectors/executeQuery
- REST named mutation: https://firebase.google.com/docs/reference/sql-connect/rest/v1/projects.locations.services.connectors/executeMutation
- Administrative named mutation, distinct authorization semantics to validate: https://firebase.google.com/docs/reference/sql-connect/rest/v1/projects.locations.services.connectors/impersonateMutation
- Local emulator: https://firebase.google.com/docs/sql-connect/data-connect-emulator-suite
- CLI and emulator: https://firebase.google.com/docs/sql-connect/cli-reference
- Free trial and region/pricing caveats: https://firebase.google.com/docs/sql-connect/pricing
- Security: https://firebase.google.com/docs/sql-connect/authorization-and-security
- FastAPI and typed HTTP contracts: https://fastapi.tiangolo.com/

The REST, schema, mutation, Admin SDK, emulator and pricing references were reviewed on 13 October 2026 for documentation accuracy. They establish available provider mechanisms, not successful Terra integration. The runtime remains Python REST through a repository boundary; administrative REST authorization must not be inferred from ordinary named execution. Construction/environmental links below remain research references, not approved project data or factors.

**Construction technical reference points (not SDP's internal data):**

- buildingSMART IFC: https://github.com/buildingSMART/IFC4.x-specification-models
- OpenConstructionEstimate: https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR
- Caltrans cost/bid item resource: https://sv08data.dot.ca.gov/

**Environmental reference points (not auto-approved factors for Malaysia):**

- ÖKOBAUDAT download catalog: https://www.oekobaudat.de/en/service/downloads.html
- UK government GHG conversion factors: https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025
- GHG Protocol avoided-emissions reporting guidance: https://ghgprotocol.org/estimating-and-reporting-avoided-emissions
- Pantas case study (existing SDP ESG context, not Terra integration): https://pantas.com/case-studies/sime-darby-property

## D. Open questions: do not pretend they have been answered

- No real **Firebase Cloud project**, Cloud SQL instance or cloud credentials are configured. Local identifiers and emulator configuration now exist for demo-terra-local/terra-local/terra. See LOCAL_DEVELOPMENT.md; cloud provisioning remains outside the authorized scope.
- **Selected Python REST integration:** local named administrative operations, loopback routing and response/error handling are now verified, as recorded in SEED_VALIDATION.md. Production server credentials, IAM permissions and connector authorization remain unproven. Ordinary `executeQuery`/`executeMutation` must not be assumed to bypass `@auth` like privileged Admin tooling. Administrative named-operation REST methods are documented, but their fit and permissions need a spike before any interface adjustment. No silent Node runtime bridge or direct-SQL fallback.
- No real **SDP project inventory**, material release permission, contractor data, Pantas API, procurement systems or BIM layouts have been given.
- No accepted Malaysia-specific embodied material emission factors, geographic transport factors or approved lifecycle boundaries are available. Initial seed factors stay **synthetic**.
- Availability windows, transfer lead times, loss/damage, returned stock and pricing are simplified. Extend only when needed and document assumptions.
- No public demo security/auth strategy has been agreed beyond "single user; no auth UI". Do not publicly expose privileged Admin SDK or unrestricted mutations.
- **Partial-transfer closure:** positive actual use can be less than receipt/approval, but no structured residual-resolution field or complete discrepancy policy is defined. Remaining promises persist until explicitly resolved; a status change alone cannot release them or restore dispatched stock. The seed must explain residual dispositions in notes/events, and flag any required policy choice. Post-dispatch cancellation/returns and demand cancellation with active transfers require a fuller later contract.
- **Actual-use carbon boundary:** production substitution uses actual used quantity; transport/handling reflects physical movement. For partial use, the allocation of full-trip emissions and treatment of damaged/unused residuals need agreement. Seed forecasts can use the stated equal-quantity formula; partial-use net stays incomplete if its boundary is undefined. No silent cost proration or waste-diversion claim.
- **Impact recalculation revisions:** the relationship map permits multiple assessments, but revision IDs/order and authoritative dashboard selection are unspecified. The baseline uses one assessment per entity/basis; settle revision handling before live recalculation.
- **Future real ingestion:** `review_mode` values currently describe demo review, even in a conceptual real-row example. Define real review modes and any richer inventory/procurement reconciliation contract before implementing real-file processing. Reviewed BOQ/PO/on-hand extraction rows currently retain those facts without separate ledgers.
- **Solver policy:** OR-Tools is optional, and precise tie-breaking, lead times and handling assumptions remain to be documented with a deterministic baseline. Missing factors cannot silently score as zero under a carbon objective.

The local proof and schema mapping passed for the seed milestone; cloud REST/authentication remains an integration gate, not a reason to change the chosen stack. Partial closure and carbon-cost boundaries need a decision before implementing general exception handling; they do not prevent offline catalogue/scenario design. Record fixture assumptions and incomplete assessments explicitly. Hosting, live data/factors, real ingestion and public access controls can wait for their respective milestones.

## E. Product claim guardrails for future README/demo

**Safe:** "Terra proposes an AI-assisted cross-project surplus reuse and carbon-aware matching workflow demonstrated with synthetic Malaysian construction-style data."

**Unsafe:** "SDP has no material reuse system", "Terra integrates directly with Pantas", "These are actual SDP site inventories", "Every transfer automatically earns carbon credits", "Every tonne of transferred material equals one tonne of officially diverted waste", "Our illustrative emission factors are certified for Malaysian construction".
