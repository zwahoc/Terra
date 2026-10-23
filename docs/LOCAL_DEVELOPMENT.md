# Local development and data maintenance

The [root README](../README.md) owns prerequisites, install, configuration, three-terminal startup, primary-model selection and ordinary usage. This guide covers advanced configuration, verification, persistence and recovery. No command here is permission to reset a populated owner workspace.

## Runtime boundaries

| Service | Normal endpoint | Persistence |
|---|---|---|
| SQL Connect emulator | 127.0.0.1:9399, demo-terra-local | `.local/sql-connect-data` |
| FastAPI | 127.0.0.1:8000 | Named local REST operations plus private source/config files |
| Vite | 127.0.0.1:5173 | Browser browsing preferences only; proxies /api to 8000 |
| Disposable integration emulator | 127.0.0.1:9499 | Separate test configuration, never normal dataDir |

The adapter refuses non-loopback/cloud endpoints. No application login, global privileged connector exposure, separate Node server or direct PostgreSQL application path is configured. Schema/connector operations are generated source; ordinary operations remain NO_ACCESS.

## Configuration

| Setting | Purpose |
|---|---|
| DEEPSEEK_API_KEY / GEMINI_API_KEY | Private server credentials, never browser DTOs |
| TERRA_LLM_ENABLED | Explicit outbound model enablement; template defaults false |
| TERRA_GEMINI_BILLING_MODE | FREE_TIER/PAID estimate basis, not account activation |
| TERRA_LLM_USD_TO_MYR | Planning conversion for estimates, minimum 5 |
| TERRA_GEMINI_MIN_INTERVAL_SECONDS | Per-model generation pacing, default 15 |
| DATA_CONNECT_EMULATOR_HOST | Explicit loopback adapter host:port; normal127.0.0.1:9399 |
| TERRA_AUTOMATCH_ENABLED | Worker switch; process environment0 disables it for isolated fixtures |
| TERRA_INGESTION_DIR | Explicit private source root override |
| TERRA_WORKSPACE_STATE | Private workspace-state manifest override |
| TERRA_BACKEND_PORT | Vite's loopback proxy target, default 8000; set in its process environment for isolated frontends |

Model settings merge root `.env` with process environment taking precedence. Worker/proxy/source overrides are read from their process environments; do not assume every override is loaded from `.env`. `SourceStore` resolves the selected private namespace, otherwise `.local/ingestion`. Primary preference lives in `.local/ingestion-model-choice`. Usage is tracked without a hard spending stop; uncertain calls remain distinguishable from billed usage. Provider dashboards are authoritative.

Configured slots/identifiers and HIGH DeepSeek handling are in `analysis_settings.py`; no automatic fallback occurs. A fresh checkout needs its own keys/enablement and a complete current-run primary choice through the sandbox. Do not copy another machine's private database/preference to claim fresh-provider acceptance.

## Dependency/tooling model

Root `npm ci` installs pinned Firebase tooling. `npm run setup` discovers native Python >=3.11, creates `.venv`, installs Python requirements and performs frontend `npm ci`. The launcher uses native Windows/macOS/Linux venv paths without shell activation, enables UTF-8 and propagates failure exit codes. Recreate only `.venv` when switching OS; never delete `.local` or `.env` to fix a Python environment.

The current SQL Connect emulator uses downloaded native local storage; normal setup does not provision Cloud SQL or a cloud service account. First downloads/install need internet. Native-platform CI configuration exists; do not claim a new Windows/Linux browser/emulator proof without an actual run.

## Safe checks

```sh
npm test
npm run build:frontend
npm run seed:validate
npm run demo:check
npm run python -- scripts/generate_seed.py --check
npm run python -- scripts/generate_provider.py --check
```

Default tests use temporary/scripted fixtures and skip separately enabled SQL integration cases. They do not make live model requests. Build output is ignored under frontend/dist and does not host the Python API/database by itself.

Database tests use dedicated runners:

```sh
npm run test:integration
npm run test:checkpoint-a
npm run test:checkpoint-b
npm run test:checkpoint-c
```

These retained command names select different transaction suites; they are not contributor implementation phases. They use disposable 9499, refuse an occupied test port, disable model calls and use independent test sources. Run sequentially. Never set destructive integration flags manually against 9399 or run a test's clear/import functions against an owner workspace.

During recording, avoid source edits that trigger hot reload, service restarts, test emulators/large suites and any operational mutation not performed by the operator. Read-only source/Git/documentation checks need no app interruption.

## Fresh-clone demo data

The normal new-clone path is `demo:validate`, `demo:seed -- --dry-run`, then `demo:seed` while only the empty emulator is running. It installs authored public fixture data, not an exported owner database. See [Demo workspace](DEMO_WORKSPACE.md) for dates, IDs, quantities and a short walkthrough.

The generator keeps `data/demo_workspace.json` as a deterministic reference snapshot. `npm run demo:check` verifies that snapshot. Import generates the same scenario relative to the selected installation date; it does not load the old canonical fixture or silently rebase existing records on startup. The stored bootstrap receipt records the anchor, fingerprint and fresh workspace epoch. Re-running preserves subsequent work, even if quantities have changed.

`ImportDemoWorkspace` serializes on the operational version, checks every business/draft/runtime table is empty, requires the exact quantity encoding and atomically installs data, commitment balances, impact heads, workspace identity and receipt. The CLI has no reset option. Import into a nonempty workspace is refused. Install before FastAPI so no background writer races initial setup; a concurrent committed write also causes transaction refusal.

The current demo has metadata-only registers and fictional transfer history. It does not manufacture uploaded files, model responses, review approvals or a complete physical-stock observation ledger. Upload/manual review remains a separate live workflow. All factors, masses and route distances are illustrative assumptions.

## Quantities and generators

The canonical seed is ordinary-unit JSON with baseline 2026-10-12. Current SQL typed quantities are Int64 millionths under QuantityEncoding.version=millionths-v1. The adapter scales typed variables/results only; JSON source evidence/snapshots remain ordinary units. No marker means legacy whole quantities. Initialising a marker over populated legacy rows corrupts interpretation and is forbidden.

New registrations permit open-ended categories/units through current runtime validators. Whole counts apply to discrete units; other exact fractions support six decimal places/range without rounding. Authoritative stock, demand, allocation and carbon arithmetic stay in Python.

`terra/contract.py` and the intake/publication/runtime/transfer/workspace provider modules generate `.gql`. Use `--check` to verify without rewriting files. For an authorised schema change, regenerate intentionally, review the diff, compile/test on disposable services and distinguish local proof from cloud migration acceptance.

## Persistence and backups

Root firebase.json explicitly selects `.local/sql-connect-data`. Normal Ctrl-C stop/start with the same command reopens it. Do not run two emulators against one directory, delete pg17 subdirectories, reseed to recover a stopped server or treat persistence as a backup.

An intact working session depends on:

- SQL operational/intake/revision/publication rows and their encoding/workspace markers.
- Original source bytes and hash metadata.
- Private source namespace selection, checkpoints, archives, usage accounting and model preference.
- Credentials/configuration, held separately from shared source.

Create a verified private archive while application writes/analysis are idle:

```sh
npm run workspace:archive
```

The archive stores ordered scalar table rows, schema field metadata, counts/checksums, encoding, current batch payloads and copied original/checkpoint bytes. It validates operational revision and draft heads before reporting success. `.local/workspace-archives` is private and ignored. A changing workspace causes archive validation to fail, not a valid concurrent snapshot. Do not publish backups or credentials to Git.

## Guarded reset and recovery

A seed import is for a new empty development database or an unchanged canonical baseline. `npm run seed:verify` is expected to differ after ordinary document operations. The refusal to overwrite is a safety guard, not an instruction to reset.

Two different maintenance tools exist:

- `seed:reset` clears/reimports baseline operational entities. It is destructive and is not a complete current-intake/source migration/recovery process.
- `workspace:cutover` requires a verified matching archive and explicit project confirmation; it checks operational/draft heads, resets active workspace state, imports/verifies the canonical seed and creates a fresh workspace/source identity. Writers must be stopped for this separately authorised operation.

Never run either during ordinary startup or recording. Inspect each CLI's `--help` and the archive/target before an explicitly requested maintenance operation. No destructive one-line reset is part of normal setup.

If SQL is unavailable, return an explicit unavailable state; checkpoints are not a live database fallback. An absent SQL draft with intact source/checkpoints may return DRAFT_RESTORE_REQUIRED and allow explicit draft restore through the existing API/UI. Restore refreshes context and invalidates old approval authority; it cannot recreate a prior operational publication merely because a JSON checkpoint exists.

A publication recovery requires verified prior business state, source integrity and truthful recovery provenance. Do not invent a lost original request key/guard or automatically restore other batches. Historical archives remain read-only via `/api/history`; old publication flags/IDs are not live stock in a new workspace.

## Background matching and impact

The local worker coalesces relevant changed material scopes after committed publication/input/transfer changes. It computes reuse/deadline/carbon alternatives on consistent current inputs. Failed scopes remain visible and require explicit retry; old generations cannot execute. History-only changes need no matching. Publication remains committed while handoff retries.

Use/applicable confirmed corrections enqueue durable actual-impact intents in the same transaction. Current assessment persistence guards source/head/token state. Pending/failed updates exclude stale actual figures from current lists/exports, while physical use remains saved. Retrying impact never repeats a use increment. A completed intent can validly report insufficient data.

Factor data are separate reference setup. The UI confirms weight/distance/master corrections; uploading a factor table does not author an emission-factor dataset. Factors need compatible catalogue/mass units, version, valid date, lifecycle boundary and transport mode. Demonstration values stay labelled. A local fixture calculation is not achieved reuse or a verified environmental claim.

## Capacity and known limitations

Workspace/publication reads reject their explicit collection limits instead of returning incomplete authoritative snapshots. Transaction/list/provider context/byte/decoder/time/resource constraints remain. Document page/item coverage is not semantic accuracy. Project/material association, dates, conversions, inferred amounts or quantity-free shared context can still require human correction/exclusion.

Cloud IAM/provisioning/access, public hosting, native accessibility, hard-crash/engine-upgrade persistence, representative large/scanned/Office semantics, production catalogue indexing and expanded physical exception workflows require separate verification. Commands and tests prove only their actual scope. [Document 06](06_REQUIREMENTS_AND_TESTS.md) tracks acceptance coverage; [Document 05](05_AI_INGESTION_CONTRACT.md) defines human authority.
