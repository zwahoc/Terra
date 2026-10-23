# Working on Terra

## Read before changing the project

Read `README.md`, Documents `docs/00` through `docs/09` in order, then `docs/TERRA_SRS_v1.0.md`. The SRS and approved domain contracts define behaviour. `docs/09_ARCHITECTURE_UPDATE.md` is the architecture authority where older descriptions conflict. Inspect the relevant code and active prompts before editing. Do not infer current requirements from old plans, fixture narratives or archived discussions.

## Architecture

- React/TypeScript/Tailwind → FastAPI → independent Python services/repositories → Python named SQL Connect REST operations.
- No persistent Node application backend, browser Firebase/admin access, direct PostgreSQL application connection or Supabase replacement.
- Runtime prompts are `backend/app/prompts/**/*.md`. They are required source assets, not disposable documentation.
- Generate SQL Connect definitions through `scripts/generate_provider.py`; do not maintain hand-edited schema/operation forks.
- Operational quantities use exact Decimal/integer values and SQL Int64 millionths under the persisted QuantityEncoding marker. Never initialise that encoding over populated legacy quantities or use Float stock arithmetic.

## Domain safeguards

- AI reads Terra context and creates provisional project/material proposals. No AI approval, publication, transfer or arbitrary SQL/web tools.
- Preserve source files, original model responses and operator overlays separately. Manual entries never claim document provenance.
- Each included file/manual submission must be resolved and explicitly approved; publish the complete batch separately and atomically. Prepared recommendations are not human confirmation.
- Keep stock, local requirement, orders, receipt, potential/confirmed surplus and net demand distinct. Surplus is part of stock; explicit net demand is not reduced by stock twice.
- Catalogue families/specification attributes are open-ended. Shared reviewed identity and consistent specs/units matter; no hardcoded family whitelist or silent cross-ID equivalence.
- Matching follows committed relevant changes across all projects for affected materials. Stale recommendations cannot confirm; actual reservations/events survive recommendation replacement.
- Confirm/reserve each transfer in one atomic operation. Full dispatch and full receipt remain distinct from positive partial/repeated actual use. Change reserved quantities only by pre-dispatch cancel/release/fresh confirmation. No dismissal or partial shipment/return workflow is selected.
- Actual-use production avoidance uses used quantity; freight/handling use moved quantity. Preserve immutable current-assessment revisions and unknown inputs. No official emissions deduction, verified diversion or carbon-credit claim.

## Preserve the owner's workspace

Normal services use 9399/8000/5173. Do not stop/restart them during an owner recording or test unless requested. Do not reset/reseed, delete `.local/sql-connect-data`, restore historical publications or change workspace/source identity without explicit direction.

Preserve publications, working reviews, original uploads/checkpoints, usage accounting, model preference, credentials, canonical seed and private archives. Empty-looking data is not authorisation to seed. Current source/model/test data may evolve as the owner works; never overwrite it with a stale documented snapshot.

Keep DeepSeek primary and HIGH reasoning unless the owner changes that choice. No unrequested live model call, automatic fallback, billing activation, cloud action, commit or push. Local demonstration-factor setup is not permission to create inventory, demand, approval or transfer facts. Never expose `.env`, private sources, local database or diagnostic captures in Git.

## Testing

Use scripted/in-memory providers and temporary files for ordinary tests. Database mutation tests use the dedicated disposable 9499 runners; never point destructive tests at9399. Do not enable integration-test flags manually against an active workspace. During owner recording, avoid builds/source edits that trigger reloads and avoid resource-intensive suites unless agreed.

Run focused checks appropriate to the change, plus the frontend build for UI changes. Use seed/provider generator `--check` for contract edits. Distinguish scripted/emulator/native/cloud evidence; skipped tests are not passed integration proof. Check final links and fixtures after documentation moves.

## Interface direction

Desktop is the priority. Preserve the earlier Terra forest/sage/ochre theme, graphical summaries/charts and expanding animated sidebar while retaining clearer controls, fresh sidebar entry, explicit resume/back context, exact-item handoffs and readable evidence. Do not launch a full redesign or spend time on mobile without a new request. Backend business changes are not implied by visual work.

## Repository maintenance and new clones

Keep current requirements, API references and setup instructions concise. Archive superseded plans/handoffs and task artifacts privately before removal; verify links and extract any test fixtures first. Documentation work alone does not authorise application changes, service restarts or operational mutations.

New clones may deliberately install the separate public integrated demo with `npm run demo:seed` on an empty emulator. Preserve its atomic empty-workspace guard, exact encoding, workspace epoch and bootstrap receipt. Repeating setup must preserve later work, never replenish stock or rebase existing dates. The canonical regression seed remains unchanged. Never export owner uploads, reviews, SQL data, credentials or model settings as a public seed.
