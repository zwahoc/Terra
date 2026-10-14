# Optimisation candidate pairs

Member 3's candidate generator is the next pure Python step after
[snapshot mapping](OPTIMISATION_SNAPSHOT_MAPPING.md). It applies the existing
[eligibility evaluator](OPTIMISATION_ELIGIBILITY_DRAFT.md) to all cross-project
offer/request combinations. It performs no allocation, stock mutation, persistence,
carbon calculation or HTTP/database calls.

Implementation: [candidates.py](../backend/app/domain/candidates.py).
Tests: [test_candidates.py](../tests/test_candidates.py).

## Behaviour and contracts

generate_candidate_pairs(snapshot) accepts a mapped DomainSnapshot. Results are
ordered by supply_offer_id, then demand_request_id, with each pair evaluated once.
Same-project pairs are omitted because the MVP models cross-project reuse.
Other rejected candidates are retained to explain status, condition, stock,
recipient commitment, unit, specification and date restrictions.

The internal CandidatePairs result contains planning_date,
lead_time_policy_version and an immutable tuple of EligibilityResult objects.
Its eligible, review_required and ineligible properties group the existing
ELIGIBLE, REVIEW_REQUIRED and INELIGIBLE compatibility values. Only eligible
pairs have positive max_allocatable_quantity. This is not an HTTP response or
an allocation_proposals database row; it creates no run/proposal IDs, status
transitions or new persisted/API fields.

The demo-township-v1 policy uses one calendar day within the same township,
two across different townships. Unknown township returns unknown lead time and
requires review when no other blocker makes the pair ineligible. No wall clock
is used: planning_date comes from the snapshot. New candidate dates do not alter
historical trips or stored run/proposal results.

For now the evaluator's draft critical-specification rules apply. Additional
application-specific requirements, such as mandatory slip ratings, still need
an agreed policy before broader matching. Missing carbon data does not invalidate
operational eligibility; no environmental score is fabricated by this generator.

## Observed current baseline

The unchanged 2026-10-12 seed produces 388 cross-project pairs:

| Compatibility | Pairs |
|---|---:|
| ELIGIBLE | 15 |
| REVIEW_REQUIRED | 1 |
| INELIGIBLE | 372 |

The review pair is SUP-020 / DEM-019 because the supply condition is UNKNOWN.
All seeded townships differ, so eligible seed pairs use a two-day lead time and
have earliest delivery on 2026-10-14. These are newly computed planning dates,
not actual scheduled deliveries or a change to the historical seed snapshot.

Selected pair limits illustrate the inputs to the future allocator:

| Supply | Demand | Pair cap (pcs) | Constraint to retain across the plan |
|---|---|---:|---|
| SUP-003 | DEM-003 | 200 | Recipient already has 300 incoming |
| SUP-002 | DEM-021 | 500 | Shares recipient budget of 800 with SUP-022 |
| SUP-022 | DEM-021 | 350 | Combined pair caps of 850 cannot all be allocated |
| SUP-005 | DEM-005 | 100 | Shares source budget of 100 with DEM-007 |
| SUP-005 | DEM-007 | 100 | Combined pair caps of 200 exceed source stock |
| SUP-006 | DEM-006 | 300 | One source can serve this and DEM-022 |
| SUP-006 | DEM-022 | 400 | Combined 700 fits SUP-006's remaining stock |
| SUP-010 | DEM-009 | 150 | Operational match despite missing carbon data |

Pair caps are independent upper bounds. Do not sum them as a feasible plan, write
them as reservations, or report them as actual reuse. The downstream allocator must
deduct chosen quantities from temporary budgets for both source and recipient.
The selected MAX_REUSE objective will maximise total allocated pcs under those
constraints; this generator does not optimise the objective.

## Runnable example

With .venv activated, run the following Python from the repository root. The
caller loads the fixture; mapping and candidate generation themselves do no I/O.

```python
from datetime import date
from terra.validation import load
from backend.app.domain.snapshot_mapping import map_record_collections
from backend.app.domain.candidates import generate_candidate_pairs

records = load()
names = (
    "projects", "materials", "documents", "extracted_rows", "supply_offers",
    "demand_requests", "optimisation_runs", "allocation_proposals", "transfers",
    "route_distances",
)
snapshot = map_record_collections(
    as_of_date=date.fromisoformat(records["metadata"]["as_of_date"]),
    **{name: records[name] for name in names},
)
result = generate_candidate_pairs(snapshot)
print("Eligible:", len(result.eligible))
print("Review required:", len(result.review_required))
print("Ineligible:", len(result.ineligible))
for pair in result.eligible:
    print(pair.supply_offer_id, pair.demand_request_id,
          pair.max_allocatable_quantity, pair.earliest_delivery_date)
assert len(result.pairs) == 388
assert len(result.eligible) == 15
```

## Verification and limits

```bash
source .venv/bin/activate
python3 -m unittest tests.test_allocator tests.test_candidates tests.test_lead_time tests.test_snapshot_mapping tests.test_eligibility tests.test_seed -v
```

Tests cover exhaustive cross-project pairing, no duplicates, existing status
groups, shared source/recipient caps, partial-use commitments, depleted stock,
spec/date failures, potential/suspended/closed supply, review conditions, missing
carbon data, unknown/same-township timing, future confirmed release, deterministic
ordering, empty collections and no input mutation.

Candidate evaluation takes O(number of supplies * number of demands) time and
stores every evaluated result for explanation. This is deliberately simple for
the baseline; larger datasets may need indexed filtering or bounded explanations
while preserving rejection semantics. Consistent database retrieval, route-specific
timing, carbon scoring and reservations remain separate. The implemented
[MAX_REUSE allocator](OPTIMISATION_ALLOCATOR.md) consumes eligible pairs and
resolves their shared budgets without changing this generator's results.
