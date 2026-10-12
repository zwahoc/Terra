# 09 — Architecture Update: Python/FastAPI-First Backend

**Project:** Terra — Intelligent Circular Construction  
**Decision status:** **CONFIRMED** by project owner  
**Effective:** 13 October 2026  
**Applies to:** Terra Codex Handoff v1.0 and subsequent implementation work  
**Purpose:** Resolve the previously undecided backend/integration architecture. **This is a decision record, not an instruction to start implementation.**

> **Precedence:** This document overrides conflicting backend, runtime integration, and seed-tooling preferences in `README.md`, `docs/04_FIREBASE_ARCHITECTURE.md`, `docs/07_DECISIONS_AND_SOURCES.md`, `docs/08_MODULE_INTERFACES.md`, and `prompts/CODEX_FIRST_TASK.md`. All domain, schema, seed, safety, and environmental requirements in those files remain in force unless explicitly amended below. `legacy/` is historical only.

## 1. Decision summary (what is now fixed)

| Area | Decision | Notes |
|---|---|---|
| Product | **Terra** | Never use CircularFlow for newly named resources. |
| Frontend | **React + TypeScript + Tailwind CSS** | React calls our own API for application operations. |
| Primary backend language | **Python** | One business-logic codebase for extraction, optimisation, carbon, and transfers. |
| Backend API framework | **FastAPI** | **Chosen**, not optional; Pydantic for request/response validation, OpenAPI for team integration. |
| Database | **Firebase SQL Connect + Cloud SQL PostgreSQL** | Keep PostgreSQL-backed relational entities and Firebase-managed GraphQL schema/connectors. |
| Backend-to-database integration | **Python adapter calling the official SQL Connect REST API**, subject to a real integration spike | Use a narrow repository/adapter interface; do not assume an untested Python Admin SDK or unrestricted arbitrary SQL. |
| Separate Node.js application/backend | **Not permitted in MVP architecture** | No Express, NestJS, or persistent Node adapter service unless the owner explicitly changes this decision. |
| Node.js usage | **Permitted for Firebase CLI/build tooling; optional for one-off admin seed tooling if essential** | This does **not** introduce a Node backend. Prefer Python seed tooling if REST integration proves sufficient. Document exceptions. |
| Application user model | **Single-user workflow; no app accounts, user/role/session/auth tables or login UI** | Do not mistake absence of app login for permission to expose public privileged operations. |
| Seed/database goal | **Option B: already populated, synthetic operating-system baseline** | The next separately requested implementation task is the seed/database foundation, not the entire app. |
| AI ingestion | Python parsing + optional LLM interpretation, later | Owner/Member 2 will supply raw CSV/XLSX/PDF construction documents separately. |
| Hosting | **Undecided** | Local development first; select a Python-capable host later with cost/security review. |

**Terminology:** Some Firebase sources use *Firebase Data Connect*; this project uses the current product naming *Firebase SQL Connect*. It is not Firestore or Firebase Realtime Database.

## 2. Target architecture

```text
                 React + TypeScript + Tailwind
            (dashboard, uploads, reviews, matching)
                             |
                             | HTTPS / JSON
                             v
                  FastAPI application (Python)
               + Pydantic DTOs + OpenAPI /docs
                             |
             +---------------+----------------+
             |               |                |
     AI Material           Circular         Carbon/Transfer
     Intelligence         Optimisation      and ESG modules
     (Python)             (Python)         (Python)
             |               |                |
             +---------------+----------------+
                             |
                 Domain services / repositories
                (framework-independent Python)
                             |
            Python SQL Connect adapter (HTTP + auth)
                             |
                 Firebase SQL Connect REST API
                             |
            Named GraphQL connector queries/mutations
                             |
                    Cloud SQL PostgreSQL
```

### Clear responsibilities

- **React** renders data, collects actions, and displays validation errors. Do not compute authoritative stock balances or carbon totals in the browser.
- **FastAPI** owns HTTP endpoints, request validation, error mapping, file intake, and orchestration of services. It must **not** contain all business rules in route handlers.
- **Python domain services** implement extraction/normalisation, stock/demand rules, material compatibility, optimisation, carbon arithmetic, status transitions, and ESG exports. They must be testable directly without an HTTP server or cloud connection.
- **Data adapter / repositories** abstract SQL Connect request/response shapes and persist/query business entities. Isolate Firebase specifics rather than spreading REST calls across services.
- **Firebase SQL Connect** stores relational data through a PostgreSQL-backed model, deployed GraphQL schema, and **predefined connector operations**. SQL Connect is the database access mechanism—not a replacement for our business API.

FastAPI is selected for **one consistent Python service and typed API contracts**, not because it is required to execute Python algorithms. It does not automatically provide free hosting, distributed job processing, security, or race-safe stock reservations.

## 3. Confirmed frontend ↔ backend communication

All **business/application operations** should use Terra's FastAPI interface, e.g.:

| Example operation (later MVP) | Owner/service |
|---|---|
| `GET /api/projects`, `GET /api/materials` | Catalog/query service |
| `GET /api/supply-offers`, `GET /api/demand-requests` | Supply/demand service |
| `POST /api/documents`, `PATCH /api/extracted-rows/{id}` | AI ingestion/review service |
| `POST /api/optimisation-runs` | Optimisation service |
| `POST /api/transfers/{id}/reserve` | Atomic transfer service |
| `POST /api/transfers/{id}/receive`, `/confirm-use` | Transfer service |
| `GET /api/dashboard/summary`, `/api/exports/impact` | Carbon/ESG reporting |

These are **proposed endpoint names**, not pre-existing APIs. `docs/08_MODULE_INTERFACES.md` remains the detailed interface baseline. The React application does **not** need the Firebase browser SDK for normal data access in this architecture. Firebase CLI / GraphQL tooling may still be necessary for schema management.

### Python code organisation (illustrative, not required filenames)

```text
backend/
  app/
    main.py                     # FastAPI app composition
    api/                        # thin routes; request/response DTOs
    schemas/                    # Pydantic contracts
    services/                   # use cases; domain rules
    domain/                     # pure matching/quantity/carbon logic
    repositories/               # DB-independent data access interfaces
    integrations/sql_connect/   # Python REST adapter + credentials
    config/                     # environment-driven settings
  tests/                        # pure unit, API, adapter, integration tests
```

Avoid introducing Celery/Redis/queues/microservices now. For the prototype, ordinary synchronous service calls are enough; add background work only if measured document processing or solver latency warrants it. FastAPI `async` does not make CPU-intensive parsing/optimisation faster on its own.

## 4. How Python accesses Firebase SQL Connect

**Selected first approach:** make server-to-server HTTPS requests to the **documented SQL Connect REST API** from Python (e.g. `httpx`), authenticate using approved Google credentials, call **named, deployed connector queries/mutations**, and map results to stable Python DTOs.

Official REST endpoints include:

```text
POST https://firebasedataconnect.googleapis.com/v1/
  projects/{project}/locations/{location}/services/{service}/
  connectors/{connector}:executeQuery

POST https://firebasedataconnect.googleapis.com/v1/
  projects/{project}/locations/{location}/services/{service}/
  connectors/{connector}:executeMutation
```

The connector request body contains a named `operationName` and `variables`. **This is not a generic raw SQL endpoint**. The GraphQL connector definitions need to be checked in with the schema and deployed to the matching service before operations can be executed.

**Important distinction:** Firebase officially documents a privileged **Node.js Admin SDK** for SQL Connect. That does **not** mean our backend must use Node.js. It also does **not** prove that Python can execute every privileged operation identically through REST. The actual IAM/OAuth authentication mode, operation authorization, REST responses, and emulator behavior must be verified in the integration spike; do not invent a Python SQL Connect Admin SDK.

### Required database integration spike — before binding the entire backend to Firebase

Codex should make the **smallest possible proof of integration**:

1. Define one lightweight model and one **named read connector** plus one **named write connector** following current Firebase documentation.
2. Configure the local SQL Connect emulator; establish a clean test database without chargeable cloud resources.
3. Write a minimal Python REST adapter with environment-based service identifiers and credentials. Verify correct request envelope, authentication, and response/error parsing. Make explicit whether local-emulator operation is supported via that route.
4. **Read one record**, **write one record**, then **read it back**; demonstrate idempotent behavior (or explicit conflict handling).
5. Where possible, test the same flow against an owner-provisioned Spark instance **only with owner approval**; distinguish emulator results from real cloud verification.
6. If the required write path or privileged permissions cannot safely work via Python REST, **stop, report the exact blocker, and propose a focused alternative**. Do not silently add a persistent Node backend or expose a public mutation.

A one-off **Node Admin SDK seed CLI** may be accepted as an explicitly documented tooling exception if needed to initialize/test fixtures. The production runtime still remains React → FastAPI (Python) → Firebase SQL Connect. Direct Cloud SQL PostgreSQL access is a separate option requiring network/permissions/provider capability review; **it is not the default fallback** and must not be assumed available on Spark.

**Seed-tooling decision:** the original handoff preferred Node Admin SDK seeding. The synchronised `prompts/CODEX_FIRST_TASK.md` now uses a **Python-first integration approach**. A Node **CLI** remains allowed if required and justified; a Node **web service** does not. This wording update preserves the confirmed architecture decision.

## 5. Security and deployment guardrails

- No application login/account model in MVP **does not mean public admin access is acceptable**.
- Do **not** expose credential-bearing server environment variables, Google access tokens, service-account keys or unrestricted mutations in React or GitHub.
- Do **not** mark write connectors `@auth(level: PUBLIC)` simply to work around backend credential issues. Restrict privileged operations according to verified Firebase authorization mechanisms and the actual hosting model.
- Use environment variables and, where available, Google **Application Default Credentials** / workload identity or comparable approved server-side credentials. Never hardcode credential JSON into source files.
- A local-only prototype can isolate privileged operations on the developer's machine; any publicly accessible demo requires a separately approved access-control/deployment plan, even with one operator.
- FastAPI has **no free cloud deployment guarantee**. Firebase Spark's SQL Connect trial does not include automatically hosting an arbitrary Python backend. Do not upgrade billing or provision paid resources without permission.
- Keep SQL Connect emulator use and cloud production access clearly separated via configuration. No committed production database dumps.

## 6. Atomic stock reservation remains non-negotiable

A transfer's reservation must atomically validate and update **both** stock and recipient incoming commitments. Do not implement this as loosely coupled `SELECT` then `UPDATE` requests vulnerable to double booking. `@transaction` and `@check` constructs may help, but **verify actual correctness under concurrency** and available connector capabilities rather than claiming transaction-safety from syntax alone.

Other business invariants stay unchanged:

1. BOQ ≠ purchase order ≠ on-hand inventory ≠ potential surplus ≠ confirmed surplus.
2. LLM interpretation **never** automatically certifies surplus, ownership, safety, or technical interchangeability.
3. Matching checks canonical material/specifications, units, dates, condition, and actual remaining stock.
4. Proposals and forecasts are **not** physical reservations or achieved reuse.
5. Receipt and **confirmed actual use** are different events; avoid double-counting history or alternate optimisation runs.
6. Factors are versioned, units/boundaries stated, and demo figures explicitly synthetic; avoided emissions are **not** official Scope 1/2/3 reductions, diverted-waste tonnage, or carbon credits.
7. No claim of a live integration with SDP procurement/BIM systems or Pantas; ESG export remains a proposed future exchange.

## 7. Scope of the next Codex implementation task remains narrow

**First milestone:** the agreed **Option B synthetic seed/database baseline**, not the entire frontend or an AI pipeline.

Expected work from `docs/03_SEED_DATABASE_SPEC.md` and `prompts/CODEX_FIRST_TASK.md`:

- Versioned `terra_seed.json` with **13 entity arrays**, realistic but entirely fictitious construction records and historical state.
- Firebase SQL Connect relational/GraphQL model plus explicitly defined connector operations.
- Repeatable, idempotent seed/reset/read-back workflow. Prefer Python when feasible; Node one-off admin CLI permitted with documented justification.
- Offline seed validator, data dictionary, reference tests, and local emulator instructions.
- Small Python REST integration proof (may be a standalone spike, **not** a full FastAPI API deployment); clearly report what was tested against emulator vs cloud.

**Out of scope until separately requested:** full API routes, hosted FastAPI service, React UI, actual file parsing, LLM calls, live SDP/Pantas integration, real carbon factors, carbon-credit systems, and cloud deployment/billing activation.

If the user asks Codex for **briefing only**, Codex must read, explain, and ask clarifying questions where needed, **without coding**.

## 8. Verification / definition of done for this architecture decision

- [ ] A single Python FastAPI runtime is the only planned backend application server.
- [ ] Firebase integration is isolated behind an adapter; no raw SQL Connect calls scattered across domain functions.
- [ ] The Python REST integration spike documents authentication, named operations, error handling and real observed read/write results.
- [ ] Local emulator tests distinguish observed success from untested cloud behavior.
- [ ] No public privileged database writes or leaked credentials.
- [ ] No auth/user tables introduced; single-operator status workflow stays intact.
- [ ] Existing seed, stock, quantity, carbon and audit tests remain unchanged in intent.
- [ ] New work does not accidentally create a second Node.js runtime backend.

## 9. Source-of-truth references

Official Firebase sources supporting the **existence** of the REST API and documented Node Admin SDK (not proof of successful project-specific integration):

- SQL Connect REST API overview: https://firebase.google.com/docs/reference/sql-connect/rest
- Named connector query: https://firebase.google.com/docs/reference/sql-connect/rest/v1/projects.locations.services.connectors/executeQuery
- Named connector mutation: https://firebase.google.com/docs/reference/sql-connect/rest/v1/projects.locations.services.connectors/executeMutation
- SQL Connect Admin SDK (Node.js): https://firebase.google.com/docs/sql-connect/admin-sdk
- Security and `@auth` behavior: https://firebase.google.com/docs/sql-connect/authorization-and-security
- Schema and connector management: https://firebase.google.com/docs/sql-connect/manage-schemas-and-connectors
- Firebase SQL Connect pricing: https://firebase.google.com/docs/sql-connect/pricing
- FastAPI official documentation: https://fastapi.tiangolo.com/

**Verification status after the authorized local seed milestone:** Python named administrative REST read/write/read-back and emulator routing have been tested successfully; see SEED_VALIDATION.md. Cloud credentials/IAM, production authorization and safe concurrent operational reservation implementation remain unverified. This decision records the chosen application architecture; local admin success does not establish production integration.
