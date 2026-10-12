# Codex — First implementation instruction (copy and paste)

You are working in my **Terra** repository. Terra is an AI-assisted cross-project construction material reuse and carbon-aware optimisation prototype for the Sime Darby Property University Hackathon. I have added the **Terra_Codex_Handoff** documentation pack to the repository.

**Invoke this prompt only after the owner separately requests implementation.** Its presence in the repository does not authorize coding during documentation review or briefing. When invoked, the seed-only instruction below replaces the documentation-only boundary in AGENTS.md; its standing architecture and domain rules continue to apply.

**Before touching code:** read `AGENTS.md`, `README.md`, and every file in `docs/00`–`docs/09` in numeric order, reading complete contents. Inspect prompts/other instructions and `legacy/` only for context. Summarise the project/architecture, identify uncertainties in Document 07, then implement the **Option B populated synthetic database baseline**. Document 09 overrides conflicting architecture/integration/tooling guidance; the current Documents 00–08 supersede conflicting CircularFlow specifications.

The chosen application stack is React + TypeScript + Tailwind → FastAPI → independent Python processing/services/repositories → Python REST adapter → Firebase SQL Connect backed by Cloud SQL PostgreSQL. Application operations use FastAPI. This task proves a minimal standalone Python database path and creates the seed foundation; it does not build the API or frontend.

## Task scope

1. Create `terra_seed.json` matching the **exact 13 arrays and record targets** described in `docs/03_SEED_DATABASE_SPEC.md` and fields in `docs/02_DATA_MODEL_CONTRACT.md`. All data synthetic, deterministic, with as-of 2026-10-12, and no `users`, roles, login, auth or real construction file assets. Build intentional positive/negative domain scenarios and include all relationships.
2. Produce a usable Firebase **SQL Connect** GraphQL `.gql` schema and connector operations mapped to the relational entities. Use correct GraphQL identifier casing and stable string seed IDs. Do not assume ordinary PostgreSQL DDL alone is enough. Prefer local SQL Connect emulator and provider-supported Firebase tooling. Do not create or provision paid cloud resources without my explicit approval.
3. Make a minimal **Python REST read/write/read-back proof** through documented named SQL Connect operations. Verify authentication/connector authorization, emulator routing, request/response errors and replay behavior. Prefer Python for the repeatable, idempotent **local seed/import + verify** workflow when that proof succeeds, with `--dry-run` validation and explicit demo-reset behavior. A justified one-off Node Admin CLI is allowed if essential; document why and distinguish its results from Python integration. No persistent Node service or silent direct-SQL fallback. Existing runtime modifications must not be silently clobbered.
4. Create `terra_seed_validator.py` or a similarly strict offline validator (no cloud credentials required). Check FKs, duplicate IDs, statuses, dates, units, transfer event/order and counters, supply/demand commitments, dataset scenarios and carbon calculations. Supply automated tests and intentional negative tests.
5. Create a concise data dictionary/README: exact schema mapping and field types, setup commands, how to run emulator and seeder, expected counts, sample material records, scenario ID index, dashboard query examples, known limitations.
6. Check acceptance criteria A01–A21, A23–A26 in `docs/06_REQUIREMENTS_AND_TESTS.md` with actual test runs or accurately report blocks, separating offline/emulator/Python REST/cloud results. A25's adapter proof must not be marked passed because Node import works. A26's partial-use fixture must retain explicit residual and carbon-boundary limitations. Test A22, truly concurrent stock/demand reservation, may be deferred to the transfer-workflow task, but document the requirement and a concrete provider-supported plan.

## Constraints

- Single-user application only: **do not create account/user/role/session/auth tables or frontend login**. Simulated project confirmation statuses/events and audit labels are fine. Server credential authentication remains required; do not expose credentials or unrestricted writes publicly.
- Raw construction CSV/XLSX/PDF files are not provided; do not generate or falsely claim they exist. Populate `documents` as truthful metadata stubs and `extracted_rows` as explicitly simulated records. The owner (Member 2) will implement actual AI extraction later.
- Do **not** implement FastAPI endpoints/full API, LLM inference, raw parsing, React UI, transport booking, live ERP/Pantas access, certified material engineering verification or carbon credits. Do not provision cloud resources, deploy services or activate billing without explicit approval, including a no-cost trial.
- A BOQ/PO is not stock. Inventory is not confirmed surplus. Forecast is not reservable. Proposal is not reservation; receipt is not actual reuse. Prevent double counting across history and alternative optimisation runs.
- Carbon results: source/version/unit/boundary and synthetic flags mandatory; missing factor inputs must not silently become zero; dashboard actual results based only on confirmed used quantities.
- Keep file and project IDs stable, and ensure dates for completed historical events are on or before 2026-10-12.
- If some Firebase SQL Connect graph/model/mutation capability is not supported, explain the specific limitation, provide a tested alternative and **do not misrepresent unrun tests as passed**.
- If a safe Python named-operation write path cannot be proven, report the exact blocker and a focused alternative for review. Do not alter the confirmed runtime architecture. Continue independent offline work where useful.
- Resolve only routine fixture choices from the existing contracts. Flag unresolved partial-transfer closure and actual-use transport/handling boundaries for the owner; do not fabricate residual returns or silently prorate emissions. Use documented fixture assumptions and incomplete net estimates where policy remains undefined.

## Definition of done

A fresh checkout can inspect the portable JSON baseline, validate it offline, follow documented local Firebase setup, seed without duplicates, read back expected entities/metrics, and inspect deliberately rejected/incomplete cases. A minimal standalone Python REST proof records observed authentication/routing/read-write results or exact blockers. Report files changed, checks passed, unverified/blocked steps and manual local setup needs. Do not start the full application or cloud deployment automatically.
