# Integrated demo database

Use this dataset on a new empty local clone. It is a small connected operating example with current matching opportunities, delivery actions and a populated report. It contains no owner uploads, private responses or credentials. The [README setup](../README.md#setup) is the complete installation guide.

## Install once

Start `npm run emulator`, wait for readiness, then run before starting FastAPI:

```sh
npm run demo:validate
npm run demo:seed -- --dry-run
npm run demo:seed
```

No provider key or model call is required. Start FastAPI and Vite afterward. Background matching computes the current three alternatives; allow it to finish before opening a recommendation.

The setup defaults to today's date in Malaysia. Every scenario date moves by the same offset, including past events, project schedules, factor validity, availability and deadlines. `--as-of YYYY-MM-DD` selects a reproducible anchor on a fresh empty workspace. It does not change the application clock. Using a past anchor can intentionally produce expired opportunities.

The empty-only transaction refuses existing business records, unpublished batches and workspace identities. A saved bootstrap receipt makes repeated invocation a no-op that preserves subsequent changes. It does not refresh dates, recreate stock or reset a used demo. No reset option is provided. Choose this dataset or the older `npm run seed` canonical regression fixture, never both in the same workspace.

## Projects and catalogue

| Project | Code | Location | Role |
|---|---|---|---|
| Lakeview Gardens External Works | LG-EW-P1 | Shah Alam | Main source |
| Cedar Grove Community Park | CGP-LW-01 | Klang | Main recipient |
| Orchard Link Streetscape | OL-ST-01 | Shah Alam | Alternative source |
| Willow Lane Pocket Park | WL-PP-01 | Subang Jaya | Additional recipient |

Provider IDs are `PRJ-DEMO-001` through `004` in that order. They are fixture references for developers; use names in the interface.

The initial main source/recipient values below include the historical transfers. Newly allocatable need subtracts active incoming commitments as well as actual use. Released quantities are not a complete on-hand inventory ledger.

| Material / catalogue ID | Unit | Source declared release | Source currently unallocated | Recipient required | Recipient newly allocatable |
|---|---|---:|---:|---:|---:|
| Grey 200 × 100 × 60 mm paver / MAT-DEMO-001 | pcs | 500 | 400 | 300 | 200 |
| Grey 200 × 100 × 80 mm paver / MAT-DEMO-002 | pcs | 250 | 250, starts anchor + 5 days | 100 | 100 |
| Red clay brick, 215 × 102.5 × 65 mm, 20 MPa / MAT-DEMO-003 | pcs | 1,000 | 800 | 400 | 200 |
| uPVC drainage pipe, 110 mm SN8 / MAT-DEMO-004 | m | 144.5 | 120.5 | 96.5 | 72.5 |
| uPVC drainage pipe, 110 mm SN4 / MAT-DEMO-005 | m | 60 potential only | 0 reservable | 48 | 48 |
| Reinforcement bar, 12 mm B500B / MAT-DEMO-006 | kg | 1,500.5 | 1,400.5 | 750.5 | 650.5 |
| CEM I 42.5 N cement, sealed 50 kg bag / MAT-DEMO-007 | bag | 60 | 50 | 40 | 30 |
| Non-woven separation geotextile, 200 gsm / MAT-DEMO-008 | m² | 300 | 300 | 200 | 200 |

Orchard additionally releases 200 pavers, 300 bricks and 60 m SN8 pipe. Willow needs those same amounts. All current demands start before the anchor and end 30 days afterward. Releases end 60 days afterward. The 80 mm paver starts five days afterward and is visible as a future opportunity. SN4 potential stock cannot be reserved and cannot satisfy the SN8 identity. Paver thicknesses also remain separate.

There are 4 projects, 8 materials, 4 metadata-only registers, 22 reviewed fixture rows, 11 offers, 11 demands, 6 routes, one historical run, 5 selected historical proposals, 5 transfers, 24 events, 17 factors and 2 initial actual-use assessments. Automatic matching adds its own current generations, proposals and forecast assessments after startup.

## Existing deliveries and reporting

| Fixture transfer | Initial state | Quantity and next action |
|---|---|---|
| TRF-DEMO-001 | Reused | 100 pavers dispatched, received and used; completed example |
| TRF-DEMO-002 | Reserved | 200 bricks; dispatch, then receive, then confirm use |
| TRF-DEMO-003 | In transit | 24 m SN8 pipe; receive, then confirm use |
| TRF-DEMO-004 | Received | 10 cement bags; confirm actual use |
| TRF-DEMO-005 | Reused with unused remainder | 100 kg steel received, 50 kg used; another 50 kg can be used later |

These are authored fictional histories. They are not records of real approvals, inspections or logistics. Metadata registers have no file bytes or forged hashes. There are no seeded ingestion batches, AI responses, publication receipts or uploaded source files. Upload/manual review still creates its own genuine workflow and provenance.

Initial actual use is 100 pavers plus 50 kg steel, or 0.3 tonnes using the declared demo masses. The two illustrative net estimates total **160.95 kgCO₂e**: 72.25 from pavers and 88.70 from steel. Forecast benefits remain separate. Changes to actual use produce new assessment revisions rather than rewriting these histories.

## Try a complete workflow

1. Open Inventory and inspect the source/recipient quantities. The future paver and potential pipe illustrate availability restrictions.
2. Open Matching after its background calculation finishes. Choose the 60 mm paver and compare the three plans. Equal alternatives are valid; don't add them together.
3. Review a current proposed transfer. Confirm suitability and reserve a permitted quantity explicitly. Previewing a recommendation does not reserve it.
4. Open Deliveries, dispatch the entire reserved quantity, confirm full receipt, then record actual use. You can record part of received quantity and use the rest later.
5. Open Report. Wait for the automatic actual-impact update, inspect the calculation and export CSV. Only actual use adds production avoidance; moved quantity determines freight/handling.
6. To try a shorter path, use an existing reserved, in-transit or received example from the table above.
7. To test ingestion, upload your own document or create a manual submission against one of the named projects/materials. Review and publish it normally. Register stubs are not downloadable source documents or a complete physical stock ledger; do not assume their absence proves no stock or procurement elsewhere.

Repeated physical actions need distinct valid commands; retrying the same action is replay-safe. A reserved quantity change requires pre-dispatch cancellation and a fresh confirmation. No partial dispatch/receipt or post-dispatch cancellation is introduced by this dataset.

## Carbon assumptions and reproducibility

All weights, road distances and factors are explicitly fictional demonstrations, not verified product values. Routes are symmetric road estimates between every pair of projects. Each material has production and handling factors in its own catalogue unit; freight is 0.12 kgCO₂e/t-km. They use `demo-v1` and the application's existing calculation boundary. New material identities need their own applicable inputs; this setup does not make arbitrary uploaded materials carbon-complete.

`data/demo_workspace.json` is the deterministic reference at anchor 24 October 2026. `terra/demo_workspace.py::build_demo` generates installation-relative data. `npm run demo:check` checks the committed reference. The canonical `data/terra_seed.json` is unchanged and retains its strict original regression contract.

Tests validate date rebasing, exact mixed units, current matching/forecasts, metadata provenance, empty-only atomic import, unpublished-draft refusal, repeated setup preserving changed work, and confirmation → dispatch → receipt → repeated use → current export on disposable 9499. No cloud or live-provider acceptance is implied.
