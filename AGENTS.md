# Instructions for Codex working on Terra

## Before changing the project

Read `README.md` and every `docs/00` through `docs/09` file in order. Treat them as the agreed product/domain contract. **`docs/09_ARCHITECTURE_UPDATE.md` is the latest confirmed architecture decision and overrides conflicting architecture, integration and seed-tooling guidance.** Inspect task prompts and other project instructions relevant to the request. Read `legacy/` only for lineage and examples; it contains outdated branding, role/account assumptions, and underspecified schema fields. Preserve historical content and flag unresolved domain contradictions rather than silently guessing.

## Current user request boundary

The local seed baseline and empty React/FastAPI scaffolds are completed and pushed. Native Windows/macOS development tooling has now been implemented, including portable locking, Python/environment launchers, setup commands, UTF-8 data I/O and compatibility tests. The current request authorizes committing and pushing these changes to `origin/main`. Preserve history; never force-push. No WSL requirement. Keep the React page blank and FastAPI free of business routes. Native OS verification must be reported accurately; simulated platform-path tests do not establish a successful Windows emulator run. No new feature implementation is authorized.

Keep the local database baseline intact. No Firebase Cloud project, Cloud SQL provisioning, billing, deployment or cloud service-account credentials. Do not add authentication, database access through HTTP routes, raw document assets/parsing, LLM calls, optimisation or carbon/transfer features. Python processing remains independent of FastAPI. Node.js is frontend/Firebase tooling only, never a separate application backend. Stored prompts remain reference material unless separately invoked.

## Confirmed application architecture

React, TypeScript and Tailwind CSS call Terra's FastAPI endpoints for all application operations. FastAPI validates HTTP requests and orchestrates framework-independent Python services for AI ingestion, material analysis, stock/demand calculation, optimisation, transfers, carbon and exports. Repositories isolate a Python adapter calling documented Firebase Data Connect / SQL Connect REST operations over the PostgreSQL-backed service. Authentication, connector authorization, emulator routing and read/write behavior require an integration proof; do not claim they already work.

No persistent Node.js application backend or adapter service is permitted. Node.js is limited to Firebase CLI/build tooling and justified one-off development utilities. Direct PostgreSQL access and Supabase are not the selected integration. No application accounts/login does not permit public privileged writes; keep server credentials private and require a separately agreed access plan for a public demo.

## Data and naming conventions

- Name = Terra; code/repo examples use `terra`, never `circularflow` for newly created resources.
- MVP = a single-app/single-operator workflow; no auth/users/roles tables and no user-linked FKs.
- Use stable **string primary keys** (`PRJ-001`, `MAT-001`, `SUP-001` etc.) throughout the *seed JSON*. Preserve explicit referential integrity. For SQL Connect map them to supported explicit string keys and field names; do not rely on implicit UUID generation when importing these IDs.
- Seed JSON and Terra HTTP DTO keys follow `snake_case`; SQL Connect `.gql` fields use `camelCase` and may be mapped to database columns using `@col` and explicit table naming. Verify mapping syntax at implementation time.
- Dates are ISO 8601; timestamps include `+08:00`; currency MYR; carbon in `kgCO2e`.
- All seed data is synthetic and deterministic; baseline `as_of_date` is `2026-10-12`, independently of documentation revision dates. Each run of the seeder must be idempotent.

## Inviolable domain rules

1. BOQ ≠ PO ≠ on-hand stock ≠ potential surplus ≠ confirmed transferable surplus.
2. Unreviewed extracted rows cannot automatically create confirmed offers.
3. Only `CONFIRMED` surplus with positive, truly reservable stock can be reserved.
4. A proposed allocation is **not** a reservation and is **not** completed reuse.
5. Material safety/suitability/ownership still require human confirmation in real use; prototype represents that via status, not fake engineering certification.
6. Units/specs/dates matter; text similarity alone does not constitute interchangeability.
7. Reservation, dispatch, receipt and actual use are distinct stages and quantities. Never double-reserve or double-count reused mass/emissions.
8. Perform coupled stock/status writes atomically; no loose read-then-update across concurrent requests.
9. All emission factors/assumptions must be versioned and visibly synthetic unless genuinely sourced.
10. Report avoided emissions separately from official GHG inventory, waste-diversion totals and carbon credits; no live Pantas claims.

## Implementation/reporting discipline

- Verify SQL Connect capabilities and syntax against current Firebase docs before emitting `.gql`; the backing PostgreSQL DDL and GraphQL API schema are different layers.
- Prefer a single seed source of truth in GitHub, deterministic import and `--dry-run` validation; never make the cloud database the sole copy.
- Use fixtures intentionally designed for negative tests; do not generate universally compatible supply/demand.
- For documentation work, re-read changed files and check terminology, local links and cross-document contracts. For implementation, run relevant tests. Explain verified vs unverified steps in the handoff, especially if a cloud Firebase project is not configured.
- Do not commit credentials, service-account files, `.env`, secrets, source procurement documents or personally identifying data.
