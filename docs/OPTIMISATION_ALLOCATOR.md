# Allocation objectives and exact solver

`backend/app/domain/allocator.py` implements deterministic no-I/O allocation over a validated detached DomainSnapshot. It changes only local working budgets; proposals, reservations, fulfilment and transfers are saved by separate guarded services.

## Objective policies

| Objective | Primary goal | Remaining preferences |
|---|---|---|
| MAX_REUSE | Maximum comparable-unit material quantity | Earliest required_by, earliest feasible arrival, shorter applicable route, stable project/offer/demand IDs |
| EARLIEST_DEADLINE | Lexicographically maximise quantities served in the earliest deadline group, then later groups | Arrival, route and stable IDs within the ordered groups |
| MAX_NET_CO2E_AVOIDED | Maximum supplied exact linear net kgCO2e | Quantity, then deadline/arrival/route/stable ordering |

Deadline is recipient need-by timing, not expiry. Every objective preserves operational eligibility, pair caps and shared source/recipient budgets. A preference may not sacrifice the MAX_REUSE quantity optimum. Deadline groups are optimised together, not greedily favouring the first row. Carbon need not maximise volume when moving more material reduces its objective.

## Algorithms

MAX_REUSE computes a maximum flow, then fixes each ranked pair to the greatest feasible quantity while preserving that optimum. Feasibility checks/binary search prevent an early preferred edge from blocking a larger valid total.

Deadline/carbon strategies use best residual paths with lexicographic reward vectors and reverse edges to reroute earlier assignments. Fraction/Decimal scores preserve exact comparison without arbitrary floating weights or rounded priorities. Processing stops when no positive reward improvement remains.

Runtime amounts are handled through the exact quantity path, preserving supported fractional catalogue units and whole discrete counts. Do not read historical internal `per_piece` names as permission to combine unlike units. Automatic matching scopes each material separately; mixed-unit totals remain separate and are never displayed as one physical quantity.

## Carbon coefficient contract

LinearCarbonScores binds:

- allocation_snapshot_hash for mapped operational inputs;
- factor_dataset_version;
- full carbon_context_id including masses, routes, factor snapshots/boundary;
- net_kgco2e_per_piece map keyed by eligible source/recipient pair, interpreted per corresponding catalogue quantity;
- explicit linear_scaling_guaranteed over each pair's full cap.

The calculator establishes coefficients and full context; the allocator cannot certify omitted factor arithmetic. Unknown pair IDs, stale/mismatched hashes/context/version, nonlinear/fixed shared-trip costs and nonfinite coefficients are rejected. Missing scores are not zero.

Unscored pairs are excluded/flagged incomplete; negative-score pairs are excluded/listed; zero-score pairs can receive quantity under tie preferences. If eligible pairs exist but none can be scored, carbon_scoring_available=false and estimate remains unknown. If no eligible pair exists, an empty plan is a valid solver outcome. Reuse/deadline allocations do not depend on complete carbon, but their returned environmental estimates can be incomplete.

## Inputs, outputs and reproducibility

The plan retains objective/status/date, allocations, exact quantities/units, source and recipient remaining budgets, timing/route/reason metadata, missing-distance pairs and documented assumptions. Carbon plans additionally retain score-derived estimated total, unscored/negative pairs and completeness flags. A plan is not a final persisted actual-impact assessment.

allocation_snapshot_hash fingerprints the mapped planning inputs and eligibility policy. Persisted inputs_snapshot_hash covers the complete saved database context; carbon_context_id binds calculation inputs independently. Stable ordering makes equal input plans reproducible. Missing route distance remains unknown; distance tie-breaking cannot invent a road estimate.

The default lead-time policy is one day within the same township and two across townships. Earliest dispatch=max(planning_date, available_from, needed_from); add lead time and require arrival≤required_by. Source dispatch must be inside availability. Future recommendations are not early reservations.

## Scope and verification

Small exhaustive connection-pattern tests compare complete objective preference vectors, including rerouting, ties and positive/zero/negative/missing coefficients. Additional tests exercise fractions, eligibility budgets, context rejection, determinism and nonmutation. These establish exercised algorithms, not production-scale optimisation latency or cloud concurrency.

Sources: [allocator](../backend/app/domain/allocator.py), [candidates](OPTIMISATION_CANDIDATES.md), [mapping](OPTIMISATION_SNAPSHOT_MAPPING.md), [forecast](../backend/app/services/forecast_preview_service.py), [SRS](TERRA_SRS_v1.0.md).
