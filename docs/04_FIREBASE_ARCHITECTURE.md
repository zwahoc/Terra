# 04 — SQL Connect data access and local storage

Architecture authority is [Document 09](09_ARCHITECTURE_UPDATE.md). This document explains the implemented provider boundary, not a cloud deployment.

## Layers

1. PostgreSQL-backed SQL Connect stores relational entities and validated JSON payloads.
2. `dataconnect/schema/schema.gql` declares the provider schema.
3. `dataconnect/terra/operations.gql` declares named administrative queries/mutations.
4. `terra/local_adapter.py::LocalDataConnect` executes those operations through REST.
5. Python repositories/services enforce application semantics; FastAPI validates requests; React renders application DTOs.

The installed local emulator uses PGlite storage. The normal configuration binds to 127.0.0.1:9399 with private persistence under `.local/sql-connect-data`. It is not a direct PostgreSQL application connection. The target cloud service uses Cloud SQL PostgreSQL, but the current adapter refuses non-loopback endpoints and non-demo project identifiers.

## Provider definitions

Generate definitions through:

```sh
npm run python -- scripts/generate_provider.py --check
```

The generator uses `terra/contract.py` plus intake/publication/runtime/transfer/workspace provider modules. Do not hand-edit generated `.gql` to create a competing schema. Ordinary connector operations are NO_ACCESS; the trusted local server uses named administrative impersonateQuery/impersonateMutation. GraphQL operation errors are checked even on a successful HTTP response.

Field mapping is explicit: snake_case application fields ↔ camelCase provider fields. Typed operational quantities use Int64 millionths at the provider boundary; JSON evidence remains ordinary units. See [data contract](02_DATA_MODEL_CONTRACT.md).

## Transactions

OperationalVersion.GLOBAL serialises participating operational writers. Transactions compare expected revisions/current data and perform all coupled effects together. Named guards protect publication, reservation, dispatch, receipt, use, cancellation and assessment heads. Idempotency keys/fingerprints prevent changed-payload replay and duplicate physical effects.

Batch publication writes approved entity/contribution changes, supersession/stock scope, audit, receipt and durable matching handoff atomically. ConfirmTransferReservation reserves source and recipient together. ConfirmTransferUse saves physical use and its impact-refresh intent together. PersistCurrentActualImpact validates source/head/intent state before advancing the current revision. Query bracketing detects mixed snapshots; ordinary multiple reads are not transaction isolation.

## Storage and recovery

Database state and source files are different stores. Original uploads/checkpoints live in private ignored source namespaces, selected by `.local/workspace-state.json` or explicit configuration. SQL rows reference source metadata/hashes. Whole-source access checks integrity and does not trust a user filename as a filesystem path.

WorkspaceIdentity binds browser commands and matching generations to one dataset epoch. Private archives capture ordered table rows, source bytes, revisions, counts and checksums. Historical-analysis APIs are read-only and do not replay old operational publications into a new workspace.

Do not delete `.local/sql-connect-data`, switch source namespaces or reset a populated workspace during routine restart. Normal persistence is not a backup. Archive/recovery/cutover procedures are in [Local development](LOCAL_DEVELOPMENT.md).

## Security and scope

Provider keys/credentials remain server-side. Single operator does not mean publicly accessible privileged writes. Local host/origin/client checks are a development boundary, not an authentication design for a public deployment.

Cloud IAM, service-account access, migrations, paid provisioning, hosting and shared cloud acceptance require separate configuration and authorisation. Local emulator success does not prove those paths. Node.js is tooling only; no persistent Node application server, direct SQL access or Supabase fallback is selected.
