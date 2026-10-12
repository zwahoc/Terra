# Terra project handoff and documentation

**Prepared:** 12 October 2026; architecture update 13 October 2026 (Asia/Kuala_Lumpur)  
**Documentation synchronised:** 13 October 2026 against Architecture Update v1.1, Document 09.  
**Project:** Terra — Intelligent Circular Construction  
**Context:** Sime Darby Property University Hackathon 2026, PLANET sustainability track  
**Status:** Validated local Option B seed foundation plus empty React and FastAPI scaffolds; no business features or real SDP records.

## Purpose

Terra helps an operator identify compatible unused construction materials across projects, compare reuse and carbon outcomes, and track transfers through confirmed actual use. This repository currently contains the product, domain and implementation contracts. The owner has authorized the local Option B seed foundation. The canonical baseline and emulator tooling now exist. Empty frontend/backend framework scaffolds have also been authorized; business features remain separate work. The owner will supply actual raw construction-document test files later; those are **out of scope for the seed task**.

## Read order for Codex

1. [`AGENTS.md`](AGENTS.md): standing working rules and document precedence.
2. [`docs/00_PRODUCT_BRIEF.md`](docs/00_PRODUCT_BRIEF.md): purpose, scope, non-goals and modules.
3. [`docs/01_BUSINESS_WORKFLOW.md`](docs/01_BUSINESS_WORKFLOW.md): domain semantics, business lifecycle and worked example.
4. [`docs/02_DATA_MODEL_CONTRACT.md`](docs/02_DATA_MODEL_CONTRACT.md): logical relational entities, fields and relationships.
5. [`docs/03_SEED_DATABASE_SPEC.md`](docs/03_SEED_DATABASE_SPEC.md): Option B record counts, scenarios, consistency and fixtures.
6. [`docs/04_FIREBASE_ARCHITECTURE.md`](docs/04_FIREBASE_ARCHITECTURE.md): Firebase SQL Connect integration constraints and development workflow.
7. [`docs/05_AI_INGESTION_CONTRACT.md`](docs/05_AI_INGESTION_CONTRACT.md): future Member 2 document/LLM component boundaries.
8. [`docs/06_REQUIREMENTS_AND_TESTS.md`](docs/06_REQUIREMENTS_AND_TESTS.md): verifiable functional requirements.
9. [`docs/07_DECISIONS_AND_SOURCES.md`](docs/07_DECISIONS_AND_SOURCES.md): settled decisions, provenance, old-to-new mapping, open questions.
10. [`docs/08_MODULE_INTERFACES.md`](docs/08_MODULE_INTERFACES.md): module responsibilities, HTTP contracts and DTOs.
11. [`docs/09_ARCHITECTURE_UPDATE.md`](docs/09_ARCHITECTURE_UPDATE.md): **latest confirmed FastAPI/Python backend decision; supersedes conflicting architecture guidance**.
12. [`prompts/CODEX_BRIEFING_ONLY.md`](prompts/CODEX_BRIEFING_ONLY.md): optional read-and-recap prompt **without coding or editing**.
13. [`prompts/CODEX_FIRST_TASK.md`](prompts/CODEX_FIRST_TASK.md): separate copy/paste instruction to implement the seed baseline later.

`AGENTS.md` holds standing instructions; this README provides navigation; Documents 00–08 hold detailed current specifications; Document 09 records the authoritative architecture decision; prompts describe separately invoked tasks. The three original **CircularFlow v0.1** sources are archived in [`legacy/`](legacy/). Their historical schema, account model, routes and scenario do not define current implementation requirements. Document 09 wins on architecture; Documents 00–08 supersede conflicting legacy domain specifications.

`MANIFEST.sha256` is retained as the original handoff checksum inventory. It predates Document 09 and these edits, so it does not verify the current active documentation. The legacy JSON remains unchanged; archival notices identify the superseded Markdown sources.

## Settled decisions (do not reinterpret)

- Product name: **Terra**, **not CircularFlow**.
- One app, **one operator** for MVP. **No `users`, `roles`, `sessions`, login, or application-account model**. Server/database authentication remains required.
- Frontend: **React + TypeScript + Tailwind CSS**. All application reads and writes go through **Python + FastAPI**. Independent Python services own business logic; repositories use a **Python REST adapter** for **Firebase Data Connect / SQL Connect backed by Cloud SQL PostgreSQL**. Named administrative Python REST operations work on the local SQL Connect emulator; production authentication/connectivity remains to be verified.
- No persistent Node backend. Node.js may support Firebase CLI/build tooling or a justified one-off Admin seed utility. Prefer Python seeding once REST read/write access is proven. Direct PostgreSQL access is not the selected fallback.
- No login does not mean public admin access. Keep database credentials server-side; public deployment access controls and Python hosting remain undecided.
- Seed style: **Option B — pre-populated operating system** including existing historical records and current open cases.
- The seed milestone is complete. The current framework scaffold keeps the React page blank and FastAPI free of application routes; feature implementation remains separate.
- Seed records are **entirely synthetic**; township names and document terminology can resemble real Malaysia, but no real SDP project inventory is asserted.
- No raw construction PDFs/CSVs/XLSXs yet. `documents` and `extracted_rows` are explicitly simulated metadata/results **without pretend source files**.
- Baseline date: **2026-10-12**, local time UTC+08:00. Never date a completed historical transfer after that baseline.
- Preserve compatibility for a future AI extraction + human review flow; **LLM interprets documents, deterministic code computes quantities and determines eligibility**.

## Local seed foundation

The populated baseline is [data/terra_seed.json](data/terra_seed.json). Local configuration, explicit string-key schema, named administrative connectors, Python REST adapter, importer/reset, offline validator and automated tests are included.

Read [local development commands](docs/LOCAL_DEVELOPMENT.md), [data dictionary](docs/SEED_DATA_DICTIONARY.md), [scenario index](data/SCENARIOS.md) and [validation evidence](docs/SEED_VALIDATION.md). The detailed Documents 00–09 remain the product/domain/architecture contract; these implementation documents describe the observed local baseline.

```sh
npm ci
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 scripts/seed_terra.py seed --dry-run
python3 -m unittest tests.test_seed -v
npm run emulator
```

In another terminal, activate `.venv`, then run `python3 scripts/seed_terra.py seed` and `python3 scripts/seed_terra.py verify`. Stop the emulator with Ctrl-C. Restart/reseed restores the deterministic baseline. `npm run test:integration` starts/stops a separate ephemeral emulator; first stop any manually running instance.

Python named administrative REST reads/writes are verified locally without cloud credentials. Ordinary client execution rejects the restricted operations. The adapter only accepts IPv4 loopback and `demo-terra-local`; cloud authentication and deployment remain unverified. The baseline uses 31 audit events to preserve complete histories, an allowed deviation from the suggested range. Concurrent operational reservation APIs are a future task, not a claim made by successful snapshot import.

## Empty application frameworks

[frontend/](frontend/) contains React + TypeScript, Vite build/dev tooling and Tailwind CSS. `App.tsx` returns null, so the page is intentionally blank. [backend/app/main.py](backend/app/main.py) creates the FastAPI app, with empty folders for future routes, DTOs, domain services, repositories and integrations. Only FastAPI's built-in documentation/OpenAPI routes exist. There are no database calls or frontend/backend requests yet.

From the repository root, install dependencies:

```sh
npm --prefix frontend ci
.venv/bin/python -m pip install -r backend/requirements.txt
```

Create `.venv` with `python3 -m venv .venv` first if needed. Node.js 22.12 or newer is required for the frontend tooling. Run each server in its own terminal:

```sh
npm run dev:frontend
npm run dev:backend
```

Frontend: http://127.0.0.1:5173. FastAPI docs: http://127.0.0.1:8000/docs; `/openapi.json` has an empty `paths` object, and `/` returns 404 because no business routes are registered. Both dev servers bind to loopback. Stop each with Ctrl-C. Neither needs the Firebase emulator to start.

```sh
npm run build:frontend
```

This checks TypeScript and builds into ignored `frontend/dist`. Tailwind follows the [official Vite plugin setup](https://tailwindcss.com/docs/installation/using-vite); backend composition follows [FastAPI's entry-point pattern](https://fastapi.tiangolo.com/tutorial/first-steps/). These are empty local scaffolds, not a deployment or completed product UI/API.

## Important environmental statement

Estimated avoided greenhouse-gas emissions are **comparative scenario estimates**, not verified Scope 1/2/3 deductions, issued carbon credits, or a confirmed Pantas API integration. Use explicit factor assumptions; represent missing factors as missing, not zero.
