# Allocation objectives

## Objective selector and agreed policies (14 October 2026)

`allocate(snapshot, objective=...)` selects one of the existing dictionary values:

| Objective | Primary optimisation | Secondary preference |
|---|---|---|
| MAX_REUSE | Maximum total allocated pcs | Earliest deadline, delivery, distance, stable IDs |
| EARLIEST_DEADLINE | Maximum pcs in the earliest required_by group, then each later group | Delivery, distance, stable IDs within the ordered deadline groups |
| MAX_NET_CO2E_AVOIDED | Maximum total Member 4 linear net kgCO2e | Maximum pcs, then deadline, delivery, distance, stable IDs |

The user confirmed these deadline and carbon policies on 14 October 2026.
Demands sharing a deadline are optimised together; this does not count fully
fulfilled requests or greedily favour the first demand record. Every strategy
keeps eligibility, integer quantity caps and shared supply/demand budgets.
`allocate_max_reuse(snapshot)` remains supported with its existing behaviour.
These are internal Python interfaces; HTTP routes, persisted DTOs and seed data
are unchanged. This document records the implementation policy, not leader
approval of a new SRS revision.

### Carbon input boundary

Member 4 supplies `LinearCarbonScores` with finite Decimal net kgCO2e/pcs values,
an explicit linear-scaling guarantee, mapped allocation snapshot hash, factor
dataset version and a full carbon-context ID. The shared orchestration caller
provides the expected factor version and context ID independently. Unknown or
noneligible score pair IDs, stale snapshots, context/version mismatches and
nonlinear inputs are rejected. The coefficient must apply over the entire pair
quantity cap. Fixed/shared truck costs are outside this model.

`allocation_snapshot_hash(snapshot)` fingerprints mapped planning inputs. It is
not the persisted `inputs_snapshot_hash` for the complete database snapshot.
Member 4/shared orchestration must bind the full material masses, factors,
boundaries and assumptions to `carbon_context_id`; the allocator cannot verify
those missing full-context records or factor arithmetic itself.

Missing/None coefficients exclude pairs from carbon allocation and populate
`unscored_pairs` plus `incomplete_carbon`. Negative coefficients are excluded and
listed separately in `negative_carbon_pairs`. Zero scores are valid and can
receive pieces under the quantity tie-break. If eligible pairs exist but none
has a score, `carbon_scoring_available=False`, the plan is empty and the estimate
is None. This is a successful solver execution with unavailable scoring, not a
fabricated zero or a new persistent solver-status enum. With no eligible pairs,
an empty carbon plan is valid with a zero estimate.

`estimated_net_avoided_kgco2e` is the score-derived total for selected allocations,
not a persisted final impact assessment. When unscored pairs were excluded it
is an optimum over scored pairs only. Member 4 still owns final forecasts and
component totals for every alternative plan. MAX_REUSE and EARLIEST_DEADLINE
have no carbon estimate until those final assessments are supplied.

```python
from decimal import Decimal
from backend.app.domain.allocator import (
    allocate, allocation_snapshot_hash, LinearCarbonScores,
)

deadline_plan = allocate(snapshot, objective="EARLIEST_DEADLINE")

# Illustrative supplied values, not Member 3 factor calculations.
# Shared orchestration establishes these expected identifiers first.
factor_version = "demo-v1"
context_id = "frozen-full-carbon-context-1"
scores = LinearCarbonScores(
    allocation_snapshot_hash=allocation_snapshot_hash(snapshot),
    factor_dataset_version=factor_version,
    carbon_context_id=context_id,
    net_kgco2e_per_piece={
        ("SUP-003", "DEM-003"): Decimal("0.9040416"),
    },
    linear_scaling_guaranteed=True,
)
carbon_plan = allocate(
    snapshot, objective="MAX_NET_CO2E_AVOIDED", carbon_scores=scores,
    factor_dataset_version=factor_version, carbon_context_id=context_id,
)
# Other eligible pairs have missing scores and are explicitly excluded/flagged.
```

### Exact deadline/carbon solver and verification

The new strategies use successive best residual paths with lexicographic reward
vectors. Carbon rewards contain net benefit, quantity, then ranked-pair quantities.
Deadline rewards contain quantities for each deadline group, then ranked-pair
quantities. Reverse edges permit rerouting earlier choices. The solver stops
when no positive-reward path remains; carbon does not force maximum volume.
Fractions preserve supplied Decimal scores exactly without rounded comparisons
or arbitrary weighted approximations. Like the existing solver, this is for the
demo baseline: vector size and runtime increase with eligible pair count.

`tests/test_allocation_objectives.py` compares both complete preference vectors
against exhaustive feasible allocations for all 16 small connection patterns,
including mixed positive/zero/negative coefficients and equal-carbon ties.
It also checks missing scoring, exact arithmetic, rerouting, context rejection,
nonmutation, determinism and the unchanged seed quantity baseline.

## Existing MAX_REUSE implementation

Member 3's allocator creates an exact maximum-quantity proposed plan from the
[mapped snapshot](OPTIMISATION_SNAPSHOT_MAPPING.md) and existing
[candidate rules](OPTIMISATION_CANDIDATES.md). It uses only eligible cross-project
pairs. It does not reserve stock, fulfil demand, create transfers or write data.

Implementation: [allocator.py](../backend/app/domain/allocator.py).
Tests: [test_allocator.py](../tests/test_allocator.py).
Benchmark: [benchmark_optimisation.py](../scripts/benchmark_optimisation.py).

## Simple explanation

The candidate generator tells us which pairs can work. The allocator chooses
quantities across those pairs while keeping shared budgets for every source and
recipient. MAX_REUSE means the largest total allocated pcs, including partial
fulfilment and one-to-many/many-to-one plans. Each piece contributes one to this
objective, regardless of material mass. No carbon score or fairness quota is
silently added to the objective.

It first finds the maximum possible total. It then favours earlier demand
deadlines, earlier delivery, shorter distance and stable IDs without reducing
that total. A locally preferred
pair may receive nothing if using it would prevent the maximum quantity.

For example, A has 100 pieces for X or Y and B has 100 for X only. Both demands
need 100. Taking A->X first would leave Y unserved. The exact allocator instead
finds A->Y 100 plus B->X 100, even if A->X has the best route preference.

## Quantity constraints and exact preference policy

For each source, sum(proposed_quantity) <= uncommitted source stock.
For each recipient, sum(proposed_quantity) <= newly allocatable demand.
Each pair also respects its max_allocatable_quantity. All quantities are integers;
noneligible pairs receive no proposal. Input balances remain unchanged.

The approved secondary policy prioritises individual pairs, not the sum of plan
distances or delivery dates. Following the latest user-requested priority
amendment (recorded in SRS Section 12.1), eligible pairs are ranked by:

1. Earliest demand deadline, the existing demand_requests.required_by field.
2. Earliest feasible delivery date, using the explicit demo lead-time policy.
3. Route distance where the comparison is available.
4. Source project ID, destination project ID, supply ID and demand ID.

Deadline priority applies among maximum-quantity plans; it does not allow a late
delivery or reduce the primary quantity optimum. required_by is the required
receipt deadline, not a material shelf-life expiry date. PlannedAllocation now
includes required_by for explanation. This remains the MAX_REUSE objective with
an urgency tie-break, not the separately named EARLIEST_DEADLINE strategy.

After fixing the maximum total F, the allocator maximises the first pair's
quantity while retaining F, fixes that quantity, and repeats for the next pair.
This produces the lexicographically greatest quantity vector in the ranked pair
order among maximum-quantity plans. Thus preferences are exact rather than just
the order of an arbitrary greedy traversal. Fallback offer/request IDs distinguish
multiple pairs with the same project IDs.

Routes are read from the existing route_distances records. The baseline's explicit
symmetric demo assumption permits lookup by an unordered project pair. Decimal
distance comparisons avoid rounding route values into fictitious integer km.
This is not a live routing service or a calculation of actual trip duration.

Missing distance does not exclude an eligible pair. ROUTE_DISTANCE_MISSING flags
that pair. Within an equal-deadline/equal-delivery group, if any distance is unknown, the whole
group uses stable IDs and allocations carry DISTANCE_TIE_BREAK_UNAVAILABLE. This
explicit fallback avoids assigning unknown distance a fake zero/infinite value
or using an inconsistent comparator between known and unknown routes. Known route
values remain visible. The fallback does not reduce the maximum quantity.

## Algorithm

The implementation uses a standard-library integer residual-network maximum-flow
algorithm (Edmonds-Karp): source -> supply -> eligible pair -> demand -> sink.
Source/demand arc capacities enforce shared budgets; candidate arc capacities
enforce pair limits. Reverse arcs allow earlier assignments to be rerouted.

For each ranked pair, repeated maximum-flow checks find the greatest fixed pair
quantity that still permits the remaining maximum total. Binary search begins at
a known feasible flow on that edge. For this integer flow network the feasible
edge quantities form an interval, allowing an exact search without per-piece
iteration. Later pairs cannot change earlier fixed quantities.

No additional solver dependency is introduced. Google OR-Tools maximum-flow and
minimum-cost-flow APIs were considered during design; the baseline implementation
keeps the same graph structure and explicit lexicographic policy in pure Python.
The independent tests enumerate all feasible allocations for 16 small connection
patterns and compare both maximum totals and the complete preference vector.

The algorithm is deliberately for the prototype baseline. Preference refinement
can require multiple flow solves per eligible pair. Its runtime scales beyond
candidate generation; benchmark before extending to large datasets. OR-Tools or
another equivalent exact solver can replace this implementation later while
retaining the domain contracts and objective/preference tests.

## Internal result and integration boundary

AllocationPlan contains objective=MAX_REUSE, solver_status=SUCCEEDED, planning
date, total_proposed_quantity, proposed allocations, remaining planning balances,
missing-distance pair IDs and explicit algorithm/timing/tie-break assumptions.
An empty feasible plan is SUCCEEDED with quantity zero. It is not INFEASIBLE
merely because some or all demands cannot be served. Invalid snapshots should be
rejected by the mapper; internal loss of the optimum raises an error, not a
misleading success.

Each PlannedAllocation contains existing supply/demand/material IDs, integer
proposed_quantity, pcs, ELIGIBLE compatibility and PROPOSED status, plus timing,
route and explanation information. These are internal objects, not the full
allocation_proposals table or a new public HTTP DTO. Run/proposal ID generation,
snapshot hashes, created_at, persisted reason codes and the Document 08 response
envelope belong to the later service/API/persistence boundary. New allocator
reason codes remain draft until coordinated with that boundary.

The remaining source values describe uncommitted balances, not certification or
permission to reserve suspended/future stock. Reservations must revalidate
eligibility and current balances atomically through Member 4's workflow.

## Runnable example

Run this Python from the repository root with .venv activated:

```python
from datetime import date
from terra.validation import load
from backend.app.domain.snapshot_mapping import map_record_collections
from backend.app.domain.allocator import allocate_max_reuse

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
plan = allocate_max_reuse(snapshot)
print(plan.objective, plan.solver_status, plan.total_proposed_quantity)
for allocation in plan.allocations:
    print(allocation.supply_offer_id, allocation.demand_request_id,
          allocation.proposed_quantity, allocation.distance_km)
assert plan.total_proposed_quantity == 4480
assert len(plan.allocations) == 14
```

The unchanged baseline produces 4,480 proposed pieces in 14 allocations. Examples:

| Pair | Proposed pcs | Explanation |
|---|---:|---|
| SUP-003 -> DEM-003 | 200 | Existing recipient commitment leaves only 200 |
| SUP-002 -> DEM-021 | 500 | Earlier tied delivery, shorter 45-km route |
| SUP-022 -> DEM-021 | 300 | Remaining recipient budget after the 500 |
| SUP-005 -> DEM-005 | 100 | Equal timing/route; stable request ID preference |
| SUP-006 -> DEM-006 | 300 | One source serves two recipients |
| SUP-006 -> DEM-022 | 400 | Uses the same source's remaining budget |

The plan does not add anything to DEM-001's unresolved incoming promise. It does
not allocate SUP-020's unknown-condition stock. Missing carbon data for an
operational match does not block this quantity-only objective.

## Verification and local benchmark

```bash
python3 -m unittest tests.test_allocator tests.test_candidates tests.test_lead_time tests.test_snapshot_mapping tests.test_eligibility tests.test_seed -v
python3 scripts/benchmark_optimisation.py --runs 5
```

Tests cover source/recipient budgets, partial fulfilment, one-to-many allocation,
greedy traps, exhaustive small-graph optimality, deadline/delivery/distance/ID priorities,
missing-route fallback, empty plans, unresolved commitments, determinism and
no mutation. The existing domain/seed regressions also pass.

Observed on local WSL2 x86_64, Linux 5.15.153.1, glibc 2.35, Python 3.12.15:
five runs of JSON reading + mapping + candidate generation + MAX_REUSE allocation
had median 0.0150 s and maximum 0.0433 s for 22 supplies/22 demands after the
deadline-first amendment. Module imports
occur before the timer. These measurements are below the 10-second baseline
target for this pure flow, but do not establish full API/database/carbon performance
or guarantees for larger datasets. The command reports environment and timings
so teammates can reproduce it on their machines.

Next: connect Member 4's actual scoring/final-assessment service to the agreed
linear input boundary, then create/persist reproducible run/proposal DTOs through
the shared repository and FastAPI. No database, API, seed or README changes were
made by the objective implementation.
