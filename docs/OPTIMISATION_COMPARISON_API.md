# Optimisation comparison and saving

Implemented 17 October 2026 for the local emulator. No cloud provisioning.

## Additions found after merging main

Member 1 added frontend/API integration, destination-scoped matching, persisted
single-objective runs, a proposal approval/request endpoint, and delivery UI.
Those paths are retained. This change fills shared comparison and linked
assessment persistence gaps rather than replacing Member 1's UI.

## Reservation policy

Member 3 now follows Member 4: reservation cannot happen before needed_from.
The earliest planned reservation/dispatch is
max(planning_date, source.available_from, demand.needed_from). Delivery adds the
explicit demo lead time and must meet required_by; dispatch must meet the source
window. A 20 October-only demand with two-day lead time is ineligible. A 20–22
October window can dispatch on the 20th and receive on the 22nd. Proposals do
not guarantee that future stock remains reservable; Member 4 rechecks atomically.

## Compare without saving

`POST /api/optimisation-comparisons/preview`

```json
{
  "planning_date": "2026-10-12",
  "factor_dataset_version": "demo-v1",
  "destination_project_id": "PRJ-001"
}
```

The destination scope is optional. Use the baseline date only for untouched
seed data; after runtime writes, use a planning date covering those timestamps.
The service retrieves one snapshot and creates one ForecastPreviewCalculator.
Both MAX_REUSE and MAX_NET_CO2E_AVOIDED use its identical planning balances and
carbon context. Each alternative includes its own plan and quantity-matched
Member 4 forecasts. Plans are alternatives, never added together as reuse.

Response follows `{data, meta, error}`. `data.alternatives` contains the two
existing preview DTOs, with shared allocation_snapshot_hash/carbon_context_id.
Decimal preview values remain JSON strings. No records are saved.

## Save both alternatives atomically

`POST /api/optimisation-comparisons`

```json
{
  "planning_date": "2026-10-12",
  "factor_dataset_version": "demo-v1",
  "destination_project_id": "PRJ-001",
  "idempotency_key": "comparison-demo-001",
  "actor_label": "Demo operator"
}
```

This computes both alternatives from one newly retrieved snapshot and saves in
one named transaction: two optimisation_runs, their allocation_proposals,
initial PROPOSAL_FORECAST impact_assessments, current revision heads, and replay
operation records. Failure rolls back all of these writes. No stock, demand,
transfer or reservation is changed.

Each run preserves the same input_snapshot and canonical inputs_snapshot_hash,
including source supply/demand records, materials, routes, emission factors,
projects, reviewed provenance and transfer/proposal commitment context. The
snapshot omits recursively nested prior-run snapshots and unrelated assessment
history. The mapped allocation hash is retained separately in assumptions.
Selection scope and factor version are part of the saved snapshot.

`data.alternatives` contains `{run, proposals, assessments}` per alternative,
plus replay information. `data.replayed` identifies a retry. Reusing a key with
changed date, factor version, destination or actor returns HTTP 409. Identical
retries return saved results without recalculating against newer inventory.

Comparison proposals start as PROPOSED. Each initial assessment links to its
actual proposal ID and matching quantity; incomplete components remain null and
retain INSUFFICIENT_DATA. Heads start at revision 1 and identify these initial
results. Provider Float storage is retained; preview Decimal precision is
converted at the persistence boundary. Alternative carbon totals must not be summed.

These APIs compute on the current snapshot at request time. Saving is not an
acceptance of a previously displayed browser preview. Clients must display the
returned saved plan, and should warn when its snapshot hash differs from the
preview. Binding a save to a previously displayed context is deferred with the
broader forecast/date consistency issue.

## Existing single-run path

`POST /api/optimisation-runs` retains Member 1's request fields, 201 response and
SELECTED proposals for its explicitly chosen single plan. It now also saves
initial linked assessments/heads and complete planning inputs atomically.
`GET /api/optimisation-runs/{run_id}` returns run, proposals and assessment
revisions. Use Member 4's current-only assessment endpoint for authoritative
current revision selection after recalculation; run reads retain revision history.

## Select one proposal and create its request

Existing endpoint: `POST /api/allocation-proposals/{proposal_id}/approve`.

```json
{
  "idempotency_key": "select-proposal-demo-001",
  "actor_label": "Demo operator",
  "evidence_ref": "Synthetic operator review"
}
```

An eligible PROPOSED or SELECTED proposal is conditionally set to SELECTED in
the same transaction that creates its REQUESTED transfer, REQUESTED event,
retry record and empty actual-impact revision head. The schema's unique
proposal-to-transfer relationship prevents duplicate requests. Rejected,
expired or noneligible proposals cannot be selected through this action.

This retains Member 1's current UI: a requested transfer carries the reviewed
proposal quantity and simulated confirmations, but all reserved/dispatched/
received/used quantities remain zero. Reservation still establishes stock and
incoming commitments later through Member 4's guarded workflow. Selecting
proposals from different alternatives does not certify them as a combined
optimal plan; shared capacities are enforced again at reservation.

## Deferred issues and remaining UI integration

- Discrepancy 2 stays open: later saved-assessment recalculation reads live
  inputs and uses proposal.created_at. Initial optimisation forecasts retain
  their planning-date inputs/provenance; this does not harmonise later revisions
  or bind separately issued preview/save requests to one context.
- Discrepancy 3 stays open: partial-use handling remains unknown, residuals stay
  committed, and processing/net remain incomplete where required.
- Member 1's existing single-run save/request UI is preserved. Wiring the new
  paired comparison response into that UI remains a frontend integration task.
- New-demand commitment-balance initialisation remains publication integration.

Tests: `tests/test_optimisation_comparison.py`, existing run/request tests, and
the guarded isolated emulator suite (`npm run test:integration`). Do not run
destructive tests against a manually running demo emulator.

Verified on 17 October 2026 in WSL Ubuntu/Python 3.12: offline discovery ran 223
tests successfully (204 passed, 19 guarded emulator tests skipped). The separate
fresh-emulator run then passed all 19 integration tests, including new paired
persistence, explicit selection, head creation, retry and rollback checks.
This verifies the local SQL Connect emulator path, not native Windows/macOS
execution, cloud IAM or production connectivity. The isolated emulator was
stopped after testing; the canonical seed JSON was not edited.

The multi-record operations follow Firebase's documented transaction model:
[SQL Connect mutations](https://firebase.google.com/docs/sql-connect/mutations-guide).
