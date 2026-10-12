# 04 — Firebase SQL Connect and Terra integration architecture

**Architecture synchronised:** 13 October 2026 with Document 09, Architecture Update v1.1. Official Firebase references were reviewed for this documentation task. At that review, no emulator, credentials, schema compilation or project-specific REST calls had been tested. Subsequent local-only results are in SEED_VALIDATION.md; cloud integration remains unverified. This describes the chosen target architecture, not an existing deployment.

## 1. Chosen provider and database layers

Terra uses **Firebase Data Connect / SQL Connect backed by Cloud SQL for PostgreSQL**. Current Firebase documentation uses SQL Connect; API hostnames, configuration directories and SDK identifiers can retain `dataconnect` or `data-connect`. Preserve documented identifiers. This is not Firestore, Realtime Database, Supabase or a standalone PostgreSQL deployment.

Three layers have different responsibilities:

1. PostgreSQL stores tables, constraints and data.
2. SQL Connect application schema uses GraphQL `.gql` declarations to map entities to PostgreSQL. Firebase tooling manages schema compatibility and migrations.
3. Connectors define named GraphQL queries/mutations exposed through the service. They are database operations behind Terra's API, not the application's HTTP business interface.

Ordinary SQL DDL alone does not create connector operations. Review generated migrations before applying them. Implementation references: [schema guide](https://firebase.google.com/docs/sql-connect/schemas-guide) and [schema/connector management](https://firebase.google.com/docs/sql-connect/manage-schemas-and-connectors).

## 2. Confirmed runtime and responsibility boundary

```text
React + TypeScript + Tailwind CSS
      | HTTPS / JSON, all application operations
      v
FastAPI application, Python
      | typed requests/responses; orchestration
      v
Framework-independent Python services
AI ingestion, material analysis, stock/demand, optimisation,
transfer lifecycle, carbon calculation and ESG export
      | repository interfaces
      v
Python SQL Connect REST adapter, server-side credentials
      | named connector operations; auth/connectivity proof required
      v
Firebase SQL Connect service
      | GraphQL application schema and connector operations
      v
Cloud SQL PostgreSQL
```

FastAPI is the chosen backend framework. Routes validate input and map errors; Python services implement the business rules and can be tested without HTTP or cloud access. Repositories expose operations such as `get_supply_snapshot()`, `persist_reviewed_row()`, `reserve_atomically()`, `fetch_factor_set()` and `record_confirmed_use()`. The adapter handles provider naming, credentials and responses.

React consumes FastAPI DTOs. It does not access Firebase directly for ordinary application reads/writes or compute authoritative stock/carbon figures. Offline JSON may support explicit mock adapters during development, but it is not a competing runtime database.

No persistent Node.js backend, Node adapter service, Express or NestJS application is planned. Node.js remains allowed for Firebase CLI/build tooling and justified one-off Admin utilities. Direct Cloud SQL access is not the default integration or fallback; changing that approach requires a separate decision.

## 3. Selected Python REST integration and required proof

The selected approach is a Python HTTP adapter using documented REST operations. Firebase documents named connector [executeQuery](https://firebase.google.com/docs/reference/sql-connect/rest/v1/projects.locations.services.connectors/executeQuery) and [executeMutation](https://firebase.google.com/docs/reference/sql-connect/rest/v1/projects.locations.services.connectors/executeMutation) methods. Their request body carries `operationName` and `variables`; responses can include GraphQL `errors` as well as `data`. The adapter must detect both HTTP and operation errors.

These methods execute predefined connector operations, not raw SQL. Cloud operations require the corresponding deployed connector definitions. Local definitions must be loaded by the emulator, with routing verified separately. The official methods list the OAuth `cloud-platform` scope; a scope alone does not establish the caller's IAM rights or bypass connector authorization.

Firebase separately documents an [administrative named-mutation method](https://firebase.google.com/docs/reference/sql-connect/rest/v1/projects.locations.services.connectors/impersonateMutation) that can impersonate auth context or skip `@auth`. Its existence is a validation item for the spike, not proof that ordinary `executeMutation` has Node Admin privileges or a decision to change Terra's selected interface. Do not introduce application user accounts to work around server authentication.

When the seed task is separately requested, prove the smallest possible integration:

1. Compile a minimal model and named read/write operations with explicit stable IDs.
2. Run a local SQL Connect emulator without cloud provisioning.
3. Configure the Python adapter with environment-based identifiers and a verified credential/authorization mode. Test the local HTTP path rather than assuming the Admin SDK emulator variable automatically configures Python.
4. Read a record, write/upsert it, read it back, and repeat without duplicate effects. Check error handling and denied writes as well as success.
5. Record observed emulator behavior separately from any later approved cloud test. Local success does not prove cloud IAM, hosting or connectivity.
6. If secure named-operation read/write access cannot work, report the exact blocker and a focused alternative. Do not silently add a Node service, direct SQL connection or public write connector.

A justified one-off [Node Admin SDK CLI](https://firebase.google.com/docs/sql-connect/admin-sdk) may initialize fixtures if Python cannot yet do so. That tooling exception does not prove the Python runtime adapter works. This proof is a standalone utility; the seed milestone does not require FastAPI endpoints.

## 4. Schema mapping requirements for the later seed task

- Seed JSON and Terra HTTP DTOs use `snake_case`; SQL Connect application fields use `camelCase`. The adapter/importer maps them explicitly.
- Use supported explicit string primary keys for IDs such as `SUP-001`. Verify key declarations and imported FK behavior; do not rely on implicit UUID defaults.
- Map objects such as `specifications`, `parsed_fields`, `payload` and `assumptions` using supported JSON types, or documented normalization where necessary. Do not invent unsupported scalars.
- Relations and generated FK names must compile under Firebase tooling. Document database-column mappings separately from connector/API field names.
- Use supported date/timestamp types; preserve instants and display Asia/Kuala_Lumpur time. Quantity calculations use exact values, with integer `pcs` in the starter catalogue.
- Keep the portable 13-array JSON contract stable. Provider-specific join tables do not create a second seed source of truth.

The logical contract is [Document 02](02_DATA_MODEL_CONTRACT.md). Verify current Firebase schema/directive syntax before emitting any `.gql`; the earlier review created no schema or migration; the separately authorized local schema results are in SEED_VALIDATION.md.

## 5. Local import and development workflow, later only

The next implementation task should validate the deterministic JSON offline first, then compile schema/connectors and use the [local emulator](https://firebase.google.com/docs/sql-connect/data-connect-emulator-suite) for import/read-back. Firebase documents a local PGlite database and [CLI emulator commands](https://firebase.google.com/docs/sql-connect/cli-reference). Confirm runtime versions and initialization flags during implementation; initialization must not provision cloud resources without approval.

Prefer Python importer/read-back tooling after the REST proof. If essential, document why a one-off Node Admin utility is needed and use supported [bulk operations](https://firebase.google.com/docs/sql-connect/data-seeding-bulk-operations). Re-import snapshot state rather than replaying events as new quantity deltas. Refuse to overwrite an actively modified demo without an explicit reset action. Keep destructive reset separate from dry-run validation.

Offline checks require no credentials. Do not claim emulator compilation/import has succeeded until the relevant checks have run. Cloud provisioning, migration, trial activation and billing changes require separate approval.

## 6. Atomic stock and demand updates

Reservation must atomically revalidate eligible stock and outstanding uncommitted demand, establish the hold and incoming commitment, update transfer state and append the audit event. Dispatch, receipt, use and cancellation also preserve their coupled invariants and replay safety.

Firebase documents transaction and check directives in its [mutation guide](https://firebase.google.com/docs/sql-connect/mutations-guide). These provide all-or-nothing operations and validation tools. Their presence alone does not demonstrate safe behavior under competing reservation requests. The later implementation must prove a supported conditional update, constraint/locking strategy or equivalent, and test both source-stock and recipient-demand contention. If the provider cannot support the required strategy, record a blocker. Seed snapshot consistency is not a substitute for that concurrency test.

## 7. Single-operator security and deployment

The prototype has no application accounts, login, sessions, roles or user-linked FKs. Google server credential authentication and connector authorization remain required integration concerns. Workflow approvals use confirmation statuses and audit labels; they do not establish security identities.

Keep tokens, keys, credentials and privileged writes server-side. Do not set unrestricted public write access to make the spike pass. Local development runs in a trusted environment. A public demo needs a separately approved access-control/deployment plan or a deliberately read-only mode. [Firebase security guidance](https://firebase.google.com/docs/sql-connect/authorization-and-security) informs the adapter proof; no hosting or public access strategy has been selected.

The documented `DATA_CONNECT_EMULATOR_HOST` setting routes Node Admin SDK calls locally. Python needs its own verified emulator configuration. Keep cloud and emulator configuration distinct and never commit service-account files or secrets.

## 8. Cost, hosting and remaining validation

[Firebase pricing](https://firebase.google.com/docs/sql-connect/pricing) describes a limited Spark trial, including a 90-day duration. This is not permanent free PostgreSQL or hosting for FastAPI. Check current availability, quotas, regions and costs before any later provisioning. Do not auto-upgrade billing.

Still unverified: Terra service/project identifiers, Python server authentication and connector permissions, emulator REST routing, complete schema mapping, race-safe reservation operations, Python hosting and public-demo controls. The selected architecture is fixed; these integration results are not. See [Document 07](07_DECISIONS_AND_SOURCES.md) for the open-item register and [Document 08](08_MODULE_INTERFACES.md) for future FastAPI contracts.
