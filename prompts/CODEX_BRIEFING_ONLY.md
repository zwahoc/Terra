# Codex — Read and understand Terra (NO coding yet)

I'm developing **Terra**, an AI-assisted construction material reuse and carbon-aware optimisation prototype for the Sime Darby Property University Hackathon.

I've placed a detailed handoff pack in this repository. **Do not modify files or start implementation yet.** Your task is to understand the system so that we can work from the same agreed requirements.

Read in order:

1. `AGENTS.md` and `README.md`.
2. Every file `docs/00_PRODUCT_BRIEF.md` through `docs/09_ARCHITECTURE_UPDATE.md`, in numeric order, reading complete contents.
3. All prompts and additional project instructions; do not execute a stored implementation prompt during briefing.
4. Everything in `legacy/` as historical sources only. Document 09 overrides conflicting architecture/integration/tooling guidance; Documents 00–08 supersede conflicting legacy specifications.

Then give me a **structured understanding report** covering:

- Terra's real business problem, intended impact, core features and what is only an unverified hypothesis.
- The entire workflow, from document extraction/review to confirmed reuse and ESG export.
- The distinction between BOQ, PO, on-hand inventory, potential surplus, confirmed surplus, outstanding demand, proposals, reservations, receipt and actual reuse.
- The 13 seed-database arrays, their relationships, important enum/status transitions, source/demand conservation constraints and baseline as-of date.
- The four system modules and their integration boundaries, especially AI Material Intelligence (Member 2).
- The confirmed React/TypeScript/Tailwind → FastAPI → independent Python services/repositories → Python REST adapter → Firebase Data Connect / SQL Connect → PostgreSQL architecture, and the distinction between GraphQL schema/connectors and SQL storage.
- Why all application operations use FastAPI, how processing remains testable without HTTP, and why the Python authentication/read-write/emulator proof is still required. Node.js may support Firebase tooling or justified one-off utilities; no persistent Node backend or assumed direct-SQL fallback.
- How offline/emulator-first seeding can be built later with Python preferred after the proof, and what remains unverified.
- The seed dataset's intended positive/negative fixtures, environmental-factor handling, and what should count on the dashboard.
- Settled decisions: Terra, Option B, FastAPI, single operator without app accounts/login/roles, no raw construction files yet. Explain required server/database credentials separately, public-demo controls still undecided, and external integrations we **cannot** claim exist.
- Any important contradictions, missing facts, risky assumptions or technical questions to confirm before coding. Separate **blockers** from nice-to-have suggestions.

**Stop after that report. Do not generate the seed data, install packages, initialize Firebase, provision cloud services, or write code until I give you a new explicit task.**
