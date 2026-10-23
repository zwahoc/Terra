# Terra

**AI-assisted construction material reuse, from document intake to confirmed use.**

Terra helps construction teams identify unused materials at one project, match them with another project's requirements, and track their reuse. It combines AI document interpretation with human review, deterministic quantity calculations, allocation planning and traceable environmental estimates.

Built for the Sime Darby Property University Hackathon 2026, PLANET sustainability track, Terra is a local, single-operator prototype. It is not connected to live SDP inventory, procurement or Pantas systems.

## What the system does

- **Document ingestion:** reads supported construction documents, identifies project and material information, retrieves existing Terra context and proposes structured records.
- **Human review:** lets the operator inspect sources, correct values, resolve material identities, review conversions and approve each file. All approved files in a batch are published together.
- **Material reconciliation:** distinguishes physical stock, remaining local requirements, ordered supply, potential excess, released surplus and uncovered demand. Revised observations retain their history.
- **Automatic matching:** compares reuse, deadline and carbon objectives for eligible materials across projects. Recommendations do not reserve stock.
- **Transfer tracking:** combines transfer confirmation and reservation, then records full dispatch, full receipt and partial or repeated actual use. Cancellation is available before dispatch.
- **Environmental reporting:** calculates comparative carbon estimates from applicable factors, material weight, route distance and confirmed use, with a five-sheet Excel report, technical CSV/JSON exports and retained calculation evidence.

The application includes Home, Inventory, Matching, Approvals, Deliveries, Upload and Report pages. An ingestion comparison sandbox is also available for inspecting model outputs.

## Workflow

```text
Upload documents
    → AI classification, extraction and comparison with existing records
    → Human review and individual file approval
    → Atomic batch publication
    → Automatic material matching
    → Explicit transfer confirmation and reservation
    → Dispatch → Receipt → Actual use
    → Updated carbon report and export
```

Upload and analysis create provisional information. Only reviewed publication changes operational material records. Receipt and actual use are separate events; proposed or received quantities are not automatically counted as reused.

## Architecture

| Layer | Implementation |
|---|---|
| Frontend | React, TypeScript, Tailwind CSS and Vite |
| Application API | Python and FastAPI |
| Processing | Independent Python services for ingestion, reconciliation, calculations, allocation, transfers and reporting |
| Data access | Python adapter calling named Firebase SQL Connect REST operations |
| Local database | Firebase SQL Connect emulator with persistent local storage |
| AI integration | Server-side Gemini and DeepSeek REST adapters |

The target cloud architecture uses Firebase SQL Connect with Cloud SQL PostgreSQL. The checked-in runtime is configured for the local emulator. Cloud provisioning, production authentication and public deployment are not configured.

All application operations pass through FastAPI. The frontend does not access Firebase directly. Node.js is used for frontend and development tooling, not a separate application backend.

## System requirements

| Requirement | Details |
|---|---|
| Node.js and npm | Node.js **22.12 or newer**; npm available on `PATH` |
| Python | **3.11 or newer**, with `venv` and `pip` support |
| Git | Required to clone the repository |
| Operating system | Local development scripts support native Windows, macOS and Linux paths; use a writable local checkout |
| Browser | A current desktop browser |
| Internet | Required for dependency installation, the initial emulator download and enabled AI requests |
| AI credentials | Provider API keys are needed only for live document analysis |
| Available ports | `9399` for SQL Connect, `8000` for FastAPI and `5173` for Vite |

The Firebase CLI is installed from the root lockfile. A global Firebase CLI, a provisioned cloud project and cloud service-account credentials are not part of the local setup. Windows developers can use PowerShell and native Python; WSL is not required.

On Windows, enable the Python launcher `py` or add Python to `PATH`. On macOS/Linux, make `python3` available. Setup detects a suitable Python installation automatically.

## Setup

Run commands from the repository root unless a step says otherwise.

### 1. Clone the repository

```sh
git clone https://github.com/zwahoc/Terra.git
cd Terra
```

Check the installed tools:

```sh
node --version
npm --version
```

Check Python with `python3 --version` on macOS/Linux, or `py -3 --version` on Windows.

### 2. Install dependencies

```sh
npm ci
npm run setup
```

The first command installs root tooling, including the pinned Firebase CLI. The setup command creates the project `.venv`, installs Python development/backend dependencies and runs the frontend's locked npm installation.

You do not need to activate the virtual environment. The repository's Python launcher selects `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on macOS/Linux.

### 3. Create local configuration

If `.env` does not already exist, copy `.env.example` to `.env`. Do not overwrite an existing configuration.

macOS/Linux:

```sh
[ -f .env ] || cp .env.example .env
```

Windows PowerShell:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

The example disables outbound model calls:

```dotenv
TERRA_LLM_ENABLED=false
DEEPSEEK_API_KEY=
GEMINI_API_KEY=
TERRA_GEMINI_BILLING_MODE=FREE_TIER
TERRA_LLM_USD_TO_MYR=5
TERRA_GEMINI_MIN_INTERVAL_SECONDS=15
```

Enter credentials only in your local `.env`. Set `TERRA_LLM_ENABLED=true` when you are ready to send documents to the configured provider. Provider availability, charges and quotas depend on your account. Usage estimates in Terra are informational and do not enforce a spending cutoff or activate billing.

The current configured model identifiers are `deepseek-flash`, `gemini-3.8-flash` and `gemini-3.5-flash-lite`. They are configuration values, not a guarantee that every provider account can access them. DeepSeek requests use HIGH reasoning. Process environment variables override `.env` values.

### 4. Start the local database

Open **Terminal 1** at the repository root:

```sh
npm run emulator
```

Wait until the emulator reports it is ready. It loads the checked-in schema and connector operations for `demo-terra-local` on `127.0.0.1:9399`.

The database persists under `.local/sql-connect-data`. Keep this terminal running. A normal restart reopens this data directory; it does not require another seed import.

### 5. Initialise a new checkout with the integrated demo

For a **new, empty development database**, run this before starting FastAPI:

```sh
npm run demo:validate
npm run demo:seed -- --dry-run
npm run demo:seed
```

The integrated demo contains four fictional projects, eight specific materials across six material families, 11 supply offers, 11 demands, five transfers at different stages, complete illustrative carbon inputs and two actual-use reporting examples. It supports pieces, metres, kilograms, bags and square metres. Dates are relative to the installation day in Malaysia, so a fresh clone has current opportunities and one future opportunity.

The importer validates the data, installs it in one guarded transaction and reads it back. It refuses any existing business records, unpublished drafts or workspace identity. Re-running after installation reports **already installed** and preserves subsequent work; it never restores used stock or moves the dates forward. To reproduce a specific scenario date, use `npm run demo:seed -- --as-of 2026-10-24` on a new empty database.

**Skip this step when continuing an existing workspace.** Do not run either seed command on another developer's working database or use a reset to resolve an import refusal. The demo is authored public fixture data, not a copy of the owner's database. Private uploads, reviews, credentials, model preference and usage history are not included.

See [Demo dataset and walkthrough](docs/DEMO_WORKSPACE.md) for material identities, starting quantities and actions to try. The older immutable 12 October 2026 baseline remains available through `npm run seed`, with `seed:validate` and `seed:verify`, for regression work. Choose one dataset for an empty workspace; do not install both.

### 6. Start FastAPI

Open **Terminal 2** at the repository root:

```sh
npm run dev:backend
```

The API listens on `http://127.0.0.1:8000`. Interactive API documentation is available at:

[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

Database-dependent operations require the emulator to remain running. The backend also hosts the local background matching and impact-update worker.

### 7. Start the frontend

Open **Terminal 3** at the repository root:

```sh
npm run dev:frontend
```

Open [http://127.0.0.1:5173/](http://127.0.0.1:5173/).

Vite proxies `/api` requests to FastAPI on port `8000`. Keep all three terminals running while using the application.

### 8. Choose the primary AI model on a fresh installation

The ordinary Upload screen requires a saved primary-model choice. This choice is local and is not committed to Git.

1. Add the API keys for the providers you intend to evaluate and enable `TERRA_LLM_ENABLED` in `.env`.
2. Open the comparison sandbox at [http://127.0.0.1:5173/?sandbox=ingestion](http://127.0.0.1:5173/?sandbox=ingestion).
3. Create a batch, select a small document and save the upload.
4. Run the explicit model comparison. On a fresh installation this attempts the configured comparison models; missing credentials or unavailable slots can fail separately.
5. Inspect a model whose files and batch check completed successfully, then select **Use as primary model**. Failed models cannot be selected.
6. Return to the main app. Ordinary analysis now uses that saved model; it does not silently choose a substitute.

Live comparison sends document content to configured providers and can incur charges. No API key or AI request is required to browse sample data, test manual workflows or run the default automated tests.

### 9. Use the application

For a new document journey:

1. Open Upload and select the related files together.
2. Optionally choose a project hint or provide context, then start analysis.
3. Review the identified projects, materials, quantities and proposed changes. Correct disagreements and resolve any blocking questions.
4. Approve each included file or manual submission, then publish the approved batch.
5. Open Matching to compare current alternatives for a material.
6. Review a proposed transfer, confirm suitability and reserve it explicitly.
7. Use Deliveries for dispatch, full receipt and actual-use recording.
8. Open Report, select a project and download its Excel report. An all-projects export and technical CSV/JSON downloads are also available.

Analysis can take multiple provider calls. Failed files can be retried, skipped or replaced with reviewed manual information. Existing successful results and original sources are retained.

## Supported document preparation

Implemented readers handle PDF, supported raster images, DOCX, XLSX/XLSM, UTF-8 text and CSV/TSV. PDF processing includes local text extraction and page-image preparation; scanned content still depends on model interpretation. Word and spreadsheet readers preserve available paragraph, table and cell references.

Support depends on the actual file contents and provider path. Legacy binary DOC/XLS files, arbitrary extensions, password protection, embedded objects and spreadsheet formulas without cached values can require conversion or operator attention. There is no guarantee that any uploaded file can be interpreted correctly. Human verification remains required.

## Carbon inputs and interpretation

A complete estimate needs applicable production, freight and loading/unloading factors, a compatible material weight and a route distance. Missing inputs remain unknown rather than zero.

Material weight and route distance can be supplied through the explicit input-confirmation controls. The current UI does not author/import emission-factor datasets, and document ingestion does not automatically register those factors. Reference-factor setup is separate from file publication.

The Excel workbook contains Summary, Transfers, Carbon breakdown, Factors & evidence, and Needs attention. It reports the current cumulative position, counts each transfer once in the all-project view, separates material units and shows incomplete calculation coverage. Project reports include both supplied and received transfers, so separate project reports must not be summed.

Production avoidance uses the quantity actually used. Freight and handling reflect the quantity moved. Demonstration factors are labelled; comparative avoided-emissions estimates are not official inventory deductions, certified waste diversion or carbon credits.

## Restarting and preserving work

Stop the frontend and backend with `Ctrl+C`, then stop the emulator with `Ctrl+C`. To resume, start the emulator, backend and frontend using Steps 4, 6 and 7. Do not reseed after a routine restart.

These private paths are ignored by Git:

| Path | Contents |
|---|---|
| `.env` | Provider keys and local settings |
| `.local/sql-connect-data/` | Persistent local database |
| `.local/ingestion/` or the selected source namespace | Original uploads and draft checkpoints |
| `.local/ingestion-model-choice/` | Saved primary-model preference |
| Other `.local/` directories | Usage accounting, workspace selection, private archives and diagnostic evidence |

Preserve both database and source files. Database persistence is not a backup. The archive command creates a private verified snapshot without resetting the workspace:

```sh
npm run workspace:archive
```

Archive when application writes and analysis are idle. Reset, cutover and recovery procedures are documented separately in [Local development](docs/LOCAL_DEVELOPMENT.md); they are not normal setup steps.

## Development checks

```sh
npm test
npm run build:frontend
npm run python -- scripts/generate_seed.py --check
npm run demo:check
npm run python -- scripts/generate_provider.py --check
```

`npm test` runs tooling/client tests and the Python suite. SQL Connect integration tests are skipped unless invoked through their dedicated runners. Default tests use temporary/scripted fixtures, not live model generation.

For database integration testing:

```sh
npm run test:integration
```

This starts a disposable emulator on port `9499`, separate from the normal persistent database on `9399`. It refuses an occupied test port. Run the dedicated integration suites sequentially; do not set integration-test flags manually against a working database.

The GitHub Actions workflow checks dependency setup, tests, deterministic generated files, the frontend build and disposable-emulator integration on Windows, macOS and Linux. The presence of the workflow is not evidence that a particular commit has passed remotely.

## Troubleshooting

| Symptom | Check |
|---|---|
| Port `9399`, `8000` or `5173` is already in use | An earlier process may still be running. Check its terminal before starting a second instance; do not delete database files. |
| Current Terra data is unavailable | Confirm the emulator is ready and FastAPI is running; use Retry connection. |
| Frontend cannot reach `/api` | Confirm FastAPI is on `8000` and open the app through Vite on `5173`. |
| Analyse is disabled | Check local provider enablement, configured credentials, selected files and primary-model choice. |
| Provider returns quota, availability or transport errors | Inspect that provider's result. Account quotas and provider availability are separate from local setup. |
| Import refuses to overwrite local data | Preserve the workspace. The seed is not a migration or restart command. |
| `.venv` belongs to another OS | Recreate only the virtual environment and rerun `npm run setup`; preserve `.local` and `.env`. |
| Carbon estimate is unavailable | Inspect missing inputs, factor units, applicability and dates. A valid material match can exist without a complete carbon score. |

## Repository structure

```text
frontend/             React application and ingestion comparison sandbox
backend/app/          FastAPI routes, schemas, services and repositories
backend/app/prompts/  Trusted runtime prompt modules
terra/                Shared contracts, exact quantities and SQL Connect tooling
dataconnect/          Generated schema and named connector operations
data/                 Immutable canonical seed and integrated demo reference snapshot
scripts/              Setup, validation and isolated test runners
tests/                Python and JavaScript tests
docs/                 Requirements, architecture and technical documentation
```

## Documentation

- [Approved SRS](docs/TERRA_SRS_v1.0.md)
- [Business workflow and quantity rules](docs/01_BUSINESS_WORKFLOW.md)
- [Data model](docs/02_DATA_MODEL_CONTRACT.md)
- [Application architecture](docs/09_ARCHITECTURE_UPDATE.md)
- [AI ingestion, review and publication contract](docs/05_AI_INGESTION_CONTRACT.md)
- [Module interfaces](docs/08_MODULE_INTERFACES.md)
- [Local development and recovery details](docs/LOCAL_DEVELOPMENT.md)
- [Requirements and acceptance coverage](docs/06_REQUIREMENTS_AND_TESTS.md)

The SRS and approved domain contracts govern behaviour. Document 09 takes precedence where older architecture descriptions conflict. Dated implementation plans and historical proof notes describe development history, not additional installation steps.

## Prototype boundaries

Terra currently runs as a trusted local, single-operator application. Public hosting and production access controls need separate work. It does not certify engineering suitability, execute physical logistics, integrate with live ERP/Pantas services or issue carbon credits. AI outputs and environmental estimates require review appropriate to their intended use.
