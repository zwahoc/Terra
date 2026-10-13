# Terra local development on Windows and macOS

The development tooling targets native Windows, macOS and Linux. WSL is not required. React/FastAPI remain local and empty; the database baseline runs through Firebase CLI 15.33.0, SQL Connect emulator 3.4.22 and its integrated PGlite engine. `demo-terra-local` is a local demo ID. No Firebase login, cloud credentials, Cloud SQL provisioning or credit card is required.

## Prerequisites

Install Node.js 22.12 or newer and Python 3.11 or newer. On Windows, install native Python with the `py` launcher or add Python to PATH. Use PowerShell or Command Prompt. On macOS/Linux, use your normal terminal. Verify `node --version` and `npm --version` work. Python version lookup is automatic during setup.

Dependency installation and the first emulator download need internet access. Database runtime traffic stays on loopback HTTP. Use a local writable checkout and recreate `.venv` per machine; do not copy it between operating systems or commit it.

## One setup flow for both platforms

From the repository root:

```sh
npm ci
npm run setup
npm run seed:validate
npm test
```

`setup` finds a suitable native Python, creates `.venv` when absent, installs `requirements-dev.txt` and `backend/requirements.txt`, then runs the frontend's locked npm installation. It can be rerun to refresh dependencies. It installs into the project environment, not global Python. `npm ci` at the root installs the pinned Firebase CLI.

No activation command is needed. The launcher uses `.venv/Scripts/python.exe` on Windows and `.venv/bin/python` on macOS/Linux. It passes arguments directly, preserves failure exit codes and enables UTF-8; shell environment-assignment syntax is not used. This Node utility is development tooling, not an application backend.

## Local database startup and seeding

In one terminal:

```sh
npm run emulator
```

Schema and connectors compile/load automatically. Keep it running. In another terminal at the same repository:

```sh
npm run seed -- --dry-run
npm run seed
npm run seed:verify
npm run seed
```

Dry-run is offline and makes no HTTP calls. The repeated seed reports `unchanged`. Verification compares every entity and quantity to [data/terra_seed.json](../data/terra_seed.json), which remains the portable source of truth. Stop the emulator with Ctrl-C. Its database is ephemeral; restart and seed to restore the baseline. Do not run Firebase init/deploy or cloud console flows for local setup.

## Framework startup

After setup, use two terminals:

```sh
npm run dev:frontend
```

```sh
npm run dev:backend
```

React serves a blank page at `http://127.0.0.1:5173`. FastAPI docs are at `http://127.0.0.1:8000/docs`; its OpenAPI `paths` object is empty and `/` returns 404. Both bind to loopback and start without the emulator. Stop each with Ctrl-C.

```sh
npm run build:frontend
```

This runs TypeScript validation and creates an ignored `frontend/dist` build. No database/client integration, business endpoints or UI features were added.

## Reset and integration tests

Reset discards local runtime edits. Close other local writers first. Confirm the exact demo project ID:

```sh
npm run seed:reset -- --confirm demo-terra-local
npm run seed:verify
```

A cross-platform [filelock](https://py-filelock.readthedocs.io/en/latest/) lock excludes simultaneous seed/reset processes in the same checkout. It fails promptly on contention and releases on normal exit or owner-process termination. This local tool lock is not the future database reservation strategy; it does not coordinate application writers or other checkouts.

Reset uses one atomic clear operation followed by one atomic import. An interruption between them leaves an empty database; rerun `npm run seed`. A malformed import rolls back the whole import, including stock/demand/transfer/event state. Imports never replay quantity deltas.

Stop any manually running emulator before:

```sh
npm run test:integration
```

This command starts a fresh demo emulator, sets test opt-in from Python instead of shell syntax, runs 10 destructive integration checks, and shuts down. It verifies all named entity reads, Python write/read-back, idempotency, reset/reseed, changed-state refusal, client denial, FK/enum rejection and transaction rollback. The runner refuses execution without the demo emulator context. `npm test` runs Node launcher tests and Python offline/lock/text tests; the 10 emulator tests are skipped there and run separately by `test:integration`.

For other Python commands, use the portable wrapper:

```sh
npm run python -- scripts/generate_seed.py --check
npm run python -- scripts/generate_provider.py --check
npm run python -- -m pip check
```

JSON and schema file reads/writes explicitly use UTF-8. Generated files use LF newlines; native paths and checkout folders containing spaces are supported. Seed content, IDs and snapshot date remain unchanged.

## Troubleshooting

- If PowerShell blocks `npm.ps1`, use `npm.cmd` in place of `npm`, for example `npm.cmd run setup`. There is no need to change system execution policy or use WSL.
- If setup cannot find Python, install Python 3.11+ and reopen the terminal so PATH is refreshed. Windows setup tries `py -3`, then `python`, then `python3`; macOS/Linux try `python3`, then `python`.
- If `.venv` belongs to another OS or is incomplete, remove only that disposable directory and rerun setup. The script refuses to silently overwrite it. Do not delete source/seed files.
- A missing dependency after pulling changes is handled by rerunning `npm run setup`. A missing `.venv` yields that same instruction.
- Loopback ports 5173 and 8000 serve the frameworks. The emulator uses 9399, with the CLI's PGlite bridge on 5432 and emulator hub on 4400/4500. Stop a conflicting local process; do not expose services on all interfaces as a workaround.
- The Python adapter accepts only `127.0.0.1:<port>` through `DATA_CONNECT_EMULATOR_HOST` and the exact demo project. It disables proxies and redirects. These guards remain intact; no cloud mode or credentials were added.
- The lock file may remain under ignored `.local`; it does not mean an OS lock is still held. Stop the active owner instead of deleting a live lock file.

## Verified interface and compatibility evidence

[LocalDataConnect](../terra/local_adapter.py) calls named administrative `impersonateQuery`/`impersonateMutation` on the emulator. Ordinary `executeQuery`/`executeMutation` still reject the same `NO_ACCESS` operations. No public writes were enabled. Official references: [emulator](https://firebase.google.com/docs/sql-connect/data-connect-emulator-suite), [administrative query](https://firebase.google.com/docs/reference/sql-connect/rest/v1/projects.locations.services.connectors/impersonateQuery), [administrative mutation](https://firebase.google.com/docs/reference/sql-connect/rest/v1/projects.locations.services.connectors/impersonateMutation).

See [SEED_VALIDATION.md](SEED_VALIDATION.md) for dated checks and limitations. The [CI matrix](../.github/workflows/local-development.yml) tests Windows, macOS and Linux in checkout paths containing spaces. Adding the workflow is not evidence of executed native Windows tests. At this local revision, macOS results and simulated Windows path/import regressions are verified; native Windows/Linux jobs still require execution after the changes reach GitHub.

The bounded admin payload limit is 5,000 and baseline list limit is 1,000. Quantities remain integer pcs, with Decimal arithmetic verification and a 1e-8 kgCO2e tolerance for stored Float results. FK/enum/unique/not-null constraints and offline validation protect seed shape and relationships. Bulk admin upserts are not business lifecycle APIs.

Concurrent operational reservations, actual parsers/LLMs, solver, carbon/transfer services, receiver residuals, revision handling, public hosting and live Pantas/SDP integration remain outside this tooling change. Application operations will go through FastAPI. Future shared cloud database configuration needs separately approved identifiers, authentication, costs and reviewed migrations. Emulator success is not proof of cloud IAM or production connectivity.

Field meanings and fixtures: [data dictionary](SEED_DATA_DICTIONARY.md), [scenario index](../data/SCENARIOS.md), [architecture decision](09_ARCHITECTURE_UPDATE.md), [approved SRS](TERRA_SRS_v1.0.md).
