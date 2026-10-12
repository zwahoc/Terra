# Terra local seed database

This implementation is local-only. It uses Firebase CLI 15.33.0, SQL Connect emulator 3.4.22 and the CLI's integrated PGlite engine. The local project is `demo-terra-local`; `us-central1` is a local resource-path identifier, not a provisioned cloud region. No Firebase login, cloud project, service-account file or credit card is needed.

## Reproduce after cloning

Use Node.js 22.12 or newer, npm, Python 3.11 or newer and a Unix-style shell. Tested on macOS with Node 22.23.2 and Python 3.14.6. The seed utility uses POSIX file locking; Windows users should use WSL. Dependency installation and the first emulator download need internet access; runtime database operations use loopback HTTP.

```sh
cd Terra
npm ci
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 scripts/seed_terra.py validate
python3 scripts/seed_terra.py seed --dry-run
python3 -m unittest tests.test_seed -v
npm run emulator
```

Keep that terminal open. In another terminal, from the repository root:

```sh
source .venv/bin/activate
python3 scripts/seed_terra.py seed
python3 scripts/seed_terra.py verify
python3 scripts/check_import.py
python3 scripts/seed_terra.py seed
```

The second seed command reports `unchanged`. Schema and connectors compile/load automatically when the emulator starts. Do not run `firebase init`, `firebase deploy`, Cloud SQL commands or Firebase cloud console flows to reproduce this baseline.

To stop the emulator, press Ctrl-C in its terminal. The database is deliberately ephemeral; recreate the same state by starting it again and running `seed`. Do not copy emulator database files between developers. The versioned [canonical JSON](../data/terra_seed.json) is the portable source of truth.

## Reset and integration tests

Reset discards all local state. Close any future application writers before resetting; the utility's file lock only coordinates tools in this checkout.

```sh
python3 scripts/seed_terra.py reset --confirm demo-terra-local
python3 scripts/seed_terra.py verify
```

Reset has an atomic clear operation followed by an atomic import operation. It is a development reset, not a single business transaction. An interruption between them leaves an empty database; a subsequent `seed` restores it. A malformed import rolls back the whole import, including coupled stock, demand, transfer and event records. The utility never replays event deltas.

Stop any manually running emulator before the isolated test command, which starts and stops a fresh instance:

```sh
npm run test:integration
```

The test suite explicitly opts into destructive reset of the local demo database. It checks named reads/writes, every entity count, repeat import, reset/reseed, changed-state refusal, ordinary-operation denial, FK/enum rejection and transactional rollback. Offline `unittest discover` skips emulator tests unless `TERRA_RUN_EMULATOR_TESTS=1` is set; a skip is not a passed integration check.

Port 9399 is the REST listener. The CLI's PGlite bridge uses local port 5432; emulator hub uses 4400/4500. If a port is occupied, stop the conflicting process or use a separate local environment. The Python adapter reads `DATA_CONNECT_EMULATOR_HOST` but refuses anything except `127.0.0.1:<port>` and the exact demo project ID. It disables proxies and redirects. It has no cloud adapter mode.

## Verified Python interface

[LocalDataConnect](../terra/local_adapter.py) calls named connector `impersonateQuery` and `impersonateMutation` endpoints on the emulator. Administrative context works locally without cloud credentials. The same operations are `@auth(level: NO_ACCESS)`; ordinary `executeQuery`/`executeMutation` return 403. No public mutation was enabled to make integration work.

Official references: [emulator](https://firebase.google.com/docs/sql-connect/data-connect-emulator-suite), [administrative named query](https://firebase.google.com/docs/reference/sql-connect/rest/v1/projects.locations.services.connectors/impersonateQuery), [administrative named mutation](https://firebase.google.com/docs/reference/sql-connect/rest/v1/projects.locations.services.connectors/impersonateMutation), [directive reference](https://firebase.google.com/docs/reference/sql-connect/gql/directive).

The local adapter is isolated so a future authenticated server adapter can replace it. These observed results do not establish cloud IAM, token refresh, connector deployment or production permissions. All eventual React operations still go through FastAPI. The separately authorized empty framework scaffolds are described in the root README; they do not expose database operations or implement application features.

`@allow` has a bounded `maxCount: 5000` for the administrative payloads, including nested snapshot JSON. The default limit rejected the historical snapshots during integration; this explicit bound was compiled and tested. Queries cap results at 1,000, which exceeds the baseline counts but is not production pagination.

## Contracts and limitations

- [Data dictionary](SEED_DATA_DICTIONARY.md), [scenario index](../data/SCENARIOS.md), [acceptance evidence](SEED_VALIDATION.md).
- `terra/contract.py` defines types and mappings. `data/terra_seed.json` defines baseline data. `generate_seed.py --check` and `generate_provider.py --check` detect drift; do not maintain independent runtime JSON copies.
- Quantities are integer `pcs`. Python uses Decimal for impact verification; Firebase Float columns store approximate factor/results values, compared with a documented 1e-8 kgCO2e tolerance. No finance or authoritative fractional stock arithmetic is implemented.
- Source holds, dispatched stock, incoming commitments and actual fulfilment reconcile to transfers. Requested/approved-only records do not hold stock or demand. Receipt is not fulfilment.
- Database FK/enum/unique/not-null constraints protect shape and relationships. Administrative upsert operations are not business lifecycle APIs. Domain stock/chronology/carbon checks run in the offline validator before the importer writes a snapshot. A future transfer API must enforce those rules at its own boundary and within concurrent database operations.
- Concurrent operational reservations and recipient contention, A22, remain unimplemented. Do not expose the admin importer as a transfer service. A future supported strategy must atomically check source availability and destination commitments, update both, write transfer/event state and reject stale/replayed commands. Test source and recipient races against the real connector strategy before enabling reservations.
- Partial-use residual closure, returned stock and transport/handling cost allocation remain open. This baseline retains residual incoming commitments and incomplete carbon estimates rather than invent a resolution.
- No solver, parsing/LLM pipeline, raw construction assets, public API, cloud resources, live Pantas connection, engineering certification or carbon-credit issuance was built.

For future cloud migration, choose project/service/region and approved credentials, re-check Firebase syntax and prices, validate the named-operation auth path, review schema migrations and public access controls, and run cloud/concurrency tests. `terra-not-provisioned` in YAML is only a placeholder; it does not identify an existing Cloud SQL instance. Cloud provisioning/deployment requires a separate authorized task.

## Empty framework development

Frontend and backend startup/build commands are in [README.md](../README.md#empty-application-frameworks). These scaffolds run independently of the emulator. Backend requirements are in `backend/requirements.txt`; seed requirements remain in `requirements-dev.txt`. The existing `terra/` database utilities remain separate from thin future FastAPI routes.
