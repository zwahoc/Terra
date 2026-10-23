# 03 — Canonical demonstration seed

For ordinary fresh-clone setup, use the separate [integrated demo](DEMO_WORKSPACE.md). This document defines the unchanged canonical regression baseline. The two datasets are alternatives, not cumulative imports.

## Purpose and immutable boundary

`data/terra_seed.json` is the portable Option B demonstration baseline. It contains an operating system with historical/current examples, not empty database scaffolding and not actual SDP inventory. Its as-of date remains2026-10-12, timezone Asia/Kuala_Lumpur and currency MYR. Current operational data can differ after review/publication/transfers; that is not seed corruption.

The seed stays ordinary-unit JSON with strict original category/unit rules. The runtime adapts quantities into its marked Int64 encoding; do not rescale or rewrite the JSON file. Source files are not manufactured from metadata stubs. Fixture provenance remains truthful in storage, while model-facing local business context need not repeat synthetic labels.

## Collections and size contract

| Collection | Expected baseline size |
|---|---:|
| projects | 5 |
| materials | 20 |
| documents | 12–15 |
| extracted_rows | 40–60 |
| supply_offers | 20–25 |
| demand_requests | 20–25 |
| route_distances | 10 unordered project pairs |
| optimisation_runs | 3–5 |
| allocation_proposals | 10–15 |
| transfers | 5–8 |
| transfer_events | 15–25, complete valid history takes precedence over a count target |
| emission_factors | 6–10 |
| impact_assessments | 5–10 |

No user/role/account/carbon-credit/live-integration tables belong in the seed. Stable IDs/FKs, explicit nulls and no future completed events are required. Historical state/events must occur no later than the baseline; future availability/deadlines are not historical completion.

## Material and evidence coverage

The starter catalogue has paver, brick and tile specification combinations, including near-looking but incompatible products, aliases in raw descriptions and unknown mass/factor cases. Catalogue identity includes relevant specifications, not name alone. The application runtime supports broader reviewed materials without changing this fixture.

Documents are metadata-only: null file URI/hash, truthful simulated source status and synthetic locators. BOQ/PO/on-hand records do not automatically create confirmed surplus. Pending rows never create confirmed offers. Demo-reviewed extraction fields preserve raw/current values and identity decisions. Real private uploads remain separate from the seed.

## Required scenario coverage

| Scenario | Required distinction |
|---|---|
| Exact compatible material across projects | At least one feasible allocation |
| Alias description, same identity | Reuse canonical SKU without duplicate identity |
| Different grade/dimensions/finish | Ineligible/review-required rather than silent equivalence |
| One supply, multiple recipients | Combined live budgets stay within stock |
| Multiple sources/distances | Environmental comparison can distinguish routes |
| Potential/suspended supply | Not reservable |
| Release too late | Date infeasibility remains explicit |
| Active hold | Available quantity excludes reservation once |
| Used less than received | Only actual use counts; unused residual remains committed |
| Reserved/transit/received | Not yet achieved reuse |
| Expired/rejected/alternative proposal | No stock effect |
| Missing mass/route/factor/handling | Unknown net, not zero |
| BOQ/PO | Planned/ordered amount, not confirmed released stock |
| Fulfilled/cancelled demand | Not freshly allocatable |
| Competing objectives | Alternative plans are not summed as execution |

Source, recipient and transfer invariants are in [Document 01](01_BUSINESS_WORKFLOW.md); exact fields and actual fixture identities are in [Seed dictionary](SEED_DATA_DICTIONARY.md). Historical partial movements may exist in sample records; current operational controls still use full dispatch/full receipt.

## Generation and offline verification

```sh
npm run seed:validate
npm run seed -- --dry-run
npm run python -- scripts/generate_seed.py --check
npm run python -- scripts/generate_provider.py --check
```

`generate_seed.py --check` compares deterministic output without replacing the file. `generate_provider.py --check` validates the generated schema/operations against current registries/providers. Validators check IDs/FKs, counters/commitments, dates/states, factor arithmetic, event history, demonstration provenance and no duplicated achievement.

## Local import

On an explicitly new empty development emulator, run `npm run seed` then `npm run seed:verify`. The importer snapshots rather than replaying increments, refuses incompatible populated state and uses named local REST operations. Repeating unchanged import is idempotent. Seed verification is meaningful against the untouched baseline; it is expected to differ after ordinary operations.

Never reset/reseed to make a current owner workspace look like the seed. Normal restart reopens persistent data. Archives, guarded resets and workspace/source epochs are advanced maintenance operations in [Local development](LOCAL_DEVELOPMENT.md), not normal contributor startup or proof of cloud access.
