# Terra seed v1.0 validation evidence

Executed locally on 13 October 2026, Asia/Kuala_Lumpur. Dataset snapshot remains 2026-10-12 to preserve the agreed contract; the implementation request's preferred 13 October date was optional. No runtime clock is used to generate data.

## Observed checks

| Check | Result |
|---|---|
| Offline JSON/domain validation | Passed, all 13 arrays and metadata validated |
| Offline automated suite | 38 tests passed, including deliberate corruptions |
| Deterministic generator check | Checked-in JSON exactly equals generation output |
| Provider generation check | Checked-in schema/connectors match explicit field registry |
| Local emulator startup | Passed with CLI 15.33.0, emulator 3.4.22 and integrated PGlite |
| Fresh emulator schema/connectors | Compiled and loaded successfully |
| Python named administrative REST read/write/read-back | Passed without cloud credentials |
| All 13 named entity list queries | Passed; record counts and complete logical state matched JSON |
| Import repeated twice | Stable IDs/counts/quantities, no event or carbon replay |
| Explicit clear/reseed | Reproduced identical logical baseline |
| Changed runtime data | Default seed refused overwrite; explicit reset restored baseline |
| Invalid FK and enum writes | Rejected; baseline remained intact |
| Whole import rollback | Late invalid impact FK rolled back an earlier project edit and all preceding writes |
| Ordinary restricted query/mutation | Both returned 403; no PUBLIC writes enabled |
| Emulator automated suite | 10 tests passed, including a fresh start/stop via npm script |
| Clean Python virtual environment | Requirements installed; offline suite passed there |
| Cloud test/deployment | Not executed; no cloud project, credentials, deployment or provisioning |
| Concurrent operational reservation, A22 | Not implemented/executed; deferred to transfer workflow as permitted by Document 06 |

Commands used:

```sh
python3 scripts/validate_seed.py
python3 scripts/generate_seed.py --check
python3 scripts/generate_provider.py --check
python3 -m compileall -q terra scripts tests
.venv/bin/python -m unittest tests.test_seed -v
npm run test:integration
```

Manual local seed, repeat seed, verification and confirmed reset were also executed against the running emulator. Then it was stopped and the npm integration command started a fresh instance, reran all 10 integration checks and shut down successfully. Full HTTP DTO/FastAPI, real-file parsing, LLM and solver tests do not exist because those modules are outside this task.

## Baseline counts and results

| Entity | Rows |
|---|---:|
| projects | 5 |
| materials | 20 |
| documents | 15 |
| extracted_rows | 50 |
| supply_offers | 22 |
| demand_requests | 22 |
| route_distances | 10 |
| optimisation_runs | 4 |
| allocation_proposals | 15 |
| transfers | 8 |
| transfer_events | 31 |
| emission_factors | 8 |
| impact_assessments | 8 |

Catalogue has 8 pavers, 6 bricks and 6 ceramic tiles. Historical confirmed use totals 950 pcs and 2.375 t with known synthetic mass. Three distinct projects participate, counting both source and recipient. Complete actual-use net estimates total 291.04 kgCO2e; IMP-005 is separately incomplete, so this is not the net impact of all reuse. IMP-004 is an incomplete forecast. None of these values are actual SDP inventory or verified environmental performance.

All current source holds/dispatches reconcile to transfers. DEM-001 has 550 fulfilled and 50 unresolved incoming commitments, leaving zero newly allocatable quantity. The received-but-unused TRF-005 contributes zero achieved reuse. Cancelled TRF-008 released its 300-pcs reservation before dispatch. Competing strategy proposals remain outside stock and actual-impact totals.

## Acceptance traceability

| Document 06 criteria | Evidence |
|---|---|
| A01–A06 | Full baseline validation, FK/enum/spec/row checks, negative publication and potential-supply tests |
| A07–A09 | Derived stock/demand calculations, source overbooking and recipient commitment corruption tests; independent 1,000/400/200 and 600/200/300 arithmetic fixtures |
| A10–A12 | Received-without-use check, separate 600/580/570/550/500 partial-stage fixture, cancelled transfer history and zero active hold |
| A13–A14 | Fixed baseline, ordered events, no future historical records, date-incompatible fixture and future-date mutation test |
| A15–A18 | Near/long supplier comparison, 4.5/450 arithmetic, missing-factor/mass/handling tests and null net |
| A19 | Basis-specific unique outcomes, actual/forecast separation and repeated-outcome rejection |
| A20–A21 | Repeated transactional upserts and exact read-back through the real local emulator |
| A22 | Explicitly deferred; snapshot transaction success does not prove concurrent reservations |
| A23–A24 | Scenario-index ID resolution and synthetic metadata/file/factor assertions |
| A25 | Named Python REST reads, writes, read-back and denial/error paths against local emulator |
| A26 | Unresolved 50-pcs commitment retained; actual movement vs use distinguished; undefined partial-use handling produces null net |

The 31 events intentionally exceed the suggested 15–25 range to represent every lifecycle stage and two complete reuse histories. The contract permits this deviation in favor of consistency. No additional domain arrays or account tables were added.

## Integration limits and next-module readiness

Frontend developers can use named reads through the Python adapter or explicit offline mocks, then integrate through future FastAPI endpoints. AI developers have provenance/review/normalisation fixtures, but no raw test documents or parsers. Optimisation developers have specs, routes, snapshots, competing plans and negative candidates; no live solver exists. Carbon/transfer developers have versioned factors, stage quantities and audit histories; operational mutations, replay-safe concurrent commands and exception policies still need implementation.

Local administrative REST methods differ from the ordinary client execution path. Emulator success proves neither cloud IAM nor authentication. The adapter deliberately rejects cloud hosts; a future authenticated adapter must be designed and tested separately. Admin bulk-upsert operations are not safe business workflows merely because they are transactional. Offline validation guards seed import; production domain invariants must also be enforced inside the supported reservation/write strategy.

Reset is two local transactions: clear, then import. Stop other local writers first. A process interruption between them leaves an empty database, not a partially applied import. Rerun `seed` to recover. Use [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) for the exact reproduction and reset commands.
