# 09 — Confirmed application architecture

**Decision:** React/FastAPI/Python with Firebase SQL Connect. Approved 13 October 2026; consolidated 24 October 2026 without changing the runtime decision. This document overrides conflicting older architecture descriptions. The SRS and domain contracts retain authority over business behaviour.

## Runtime

```text
React + TypeScript + Tailwind CSS
    ↓ HTTP/JSON through the application's API
FastAPI
    ↓ typed validation and orchestration
Framework-independent Python services
    ↓ repository interfaces
Python named-operation REST adapter
    ↓ Firebase SQL Connect schema/connectors
Local SQL Connect emulator
    or separately approved Cloud SQL PostgreSQL deployment
```

| Component | Responsibility |
|---|---|
| React/Vite | Forms, source/review display, navigation, progress and rendering returned quantities/results |
| FastAPI | Application HTTP contracts, request validation, local access guards and error envelopes |
| Python services | Document processing, controlled AI execution, reconciliation, calculations, publication, matching, transfer lifecycle, carbon and export |
| Repositories/adapter | Named SQL Connect reads/mutations, field mapping, exact wire quantities and provider errors |
| SQL Connect | Schema/relations, persisted records and guarded transactions |
| Local worker | Durable matching/actual-impact follow-up, without LLM calls |

All normal application reads/writes pass through FastAPI. React never uses privileged Firebase connectors directly and does not compute authoritative stock, allocations or carbon. Node.js is limited to frontend/Firebase tooling and justified one-off development utilities. No persistent Node backend, direct PostgreSQL application adapter or Supabase runtime is selected.

## Implemented local environment

- Frontend:127.0.0.1:5173; API:127.0.0.1:8000; persistent emulator:127.0.0.1:9399.
- The adapter executes named administrative SQL Connect REST operations against demo-terra-local only. Ordinary operations remain NO_ACCESS.
- Emulated data persists in ignored `.local/sql-connect-data`; original sources, checkpoints, usage accounting, archives and model preference remain private.
- AI credentials are loaded server-side. DeepSeek is the owner's selected model; fresh installations require an explicit primary choice. Comparison is deliberate, with isolated model proposals.
- Background matching and impact processing run inside the Python application lifecycle. No Redis, Celery, separate Node service or cloud queue is required by the current local implementation.

## Non-negotiable boundaries

1. Human review precedes operational publication; AI tools create proposals only.
2. Each file/manual submission has approval, and a complete approved batch publishes atomically.
3. Stock and recipient capacity are revalidated/reserved together. Dispatch, receipt, actual use and cancellation preserve their coupled invariants.
4. Exact quantity arithmetic uses Python Decimal/integer values; SQL typed quantities use the persisted millionths encoding. No binary Float stock authority.
5. Idempotency and source/revision/generation guards apply at transaction time; a frontend preview is not permission to use stale inputs.
6. Immutable source evidence, operator overlays, transfer events and carbon revisions remain traceable.
7. Missing carbon inputs remain unknown. Demonstration calculations are not official corporate deductions or carbon credits.
8. A local single-operator UI does not authorise public privileged access. No application accounts/roles are part of this prototype.

## Cloud and portability status

React and FastAPI remain local. The approved target permits a separately configured shared Firebase SQL Connect/Cloud SQL database for multiple local developer instances. Production IAM, authentication, connectivity, costs, migration and deployment must be explicitly validated; none is established by emulator success. No cloud resource or billing change is implied by setup commands.

Development scripts support Windows/macOS/Linux paths and CI defines a native matrix. Report actual native test execution separately from simulated path tests and local macOS proof. Performance targets in the SRS are acceptance targets, not benchmark guarantees.

## Source ownership

- `backend/app/main.py`: API composition and worker lifecycle.
- `backend/app/routes/`, `schemas/`, `services/`, `repositories/`: application boundary and processing.
- `backend/app/domain/`: deterministic eligibility, mapping, allocation and carbon logic.
- `backend/app/prompts/`: active trusted Markdown prompt modules; these are runtime assets.
- `terra/contract.py`, `quantities.py`, `local_adapter.py` and provider generators: shared/provider contracts.
- `dataconnect/`: generated schema/operations; `data/terra_seed.json`: unchanged portable demonstration baseline.

[README](../README.md) owns ordinary setup. [Document 04](04_FIREBASE_ARCHITECTURE.md) covers provider storage, [Document 08](08_MODULE_INTERFACES.md) application contracts, and [Document 07](07_DECISIONS_AND_SOURCES.md) current decisions and sources. Historical plans and handoff prompts are not runtime specifications.
