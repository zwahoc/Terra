# Draft eligibility evaluator and quantity model

This draft is Member 3's first domain component. It evaluates one published supply
offer against one validated demand request. It reads snapshots and returns a
decision; it performs no database writes, reservation, HTTP request, carbon
calculation or allocation optimisation. The approved SRS governs business intent,
Document 09 governs architecture, and Documents 01/02/08 govern shared semantics.

Implementation: [eligibility.py](../backend/app/domain/eligibility.py).
Verification: [test_eligibility.py](../tests/test_eligibility.py).

## Simple explanation

Think of the evaluator as a checklist before offering one project's unused
materials to another project. It asks whether the material matches, the source
is confirmed and unused, the recipient still needs it, and delivery can happen
in time. It subtracts quantities already committed on both sides.

For SUP-003, 800 confirmed pieces minus 300 reserved leaves 500. DEM-003 needs
500, but already has 300 incoming, so it has room for only 200 more. This pair
can propose at most 200 pieces. Running the checklist does not reserve those 200.

A result is ELIGIBLE, INELIGIBLE, or REVIEW_REQUIRED. The latter means some
necessary evidence or planning input is absent. Only ELIGIBLE returns a positive
allocation cap. Bad balances raise ValueError rather than hiding overbooking.

## Detailed model

### Quantity inputs and conservation

SupplyQuantity accepts confirmed_quantity (nullable), reserved_active_quantity
and transferred_out_quantity. Its uncommitted_quantity is:

```text
confirmed_quantity - reserved_active_quantity - transferred_out_quantity
```

Null confirmation gives zero uncommitted quantity. Unconfirmed stock with holds
or dispatches is invalid. All quantities are nonnegative integer pcs, and holds
plus dispatches must not exceed confirmation. Floats and booleans are rejected.

All source counters are mandatory constructor arguments; none default to zero.

DemandQuantity accepts required_quantity, fulfilled_quantity and an explicit
incoming_committed_quantity. It exposes:

```text
remaining_unfulfilled_quantity = required_quantity - fulfilled_quantity
newly_allocatable_quantity = remaining_unfulfilled_quantity - incoming_committed_quantity
```

All demand counters are mandatory constructor arguments. Required quantity is
positive. Fulfilment plus outstanding commitments cannot
exceed it. A repository/read-model layer must calculate commitments from one
consistent snapshot, counting each transfer once. In the existing baseline:

- REQUESTED and APPROVED create no hold or incoming commitment.
- RESERVED, IN_TRANSIT, RECEIVED and partially REUSED retain the unfulfilled
  approved promise: approved_quantity minus actually_used_quantity.
- Pre-dispatch CANCELLED releases its commitment.
- Receipt alone never increases fulfilled_quantity.
- Positive use or a REUSED label alone does not resolve missing/unused promises.

The approved SRS requires explicit residual disposition and return handling.
Future resolved residuals must be incorporated by that read model. This evaluator
does not infer resolution from notes or silently adapt the seed status formula
into a general transfer lifecycle implementation.

### Eligibility inputs and rules

Supply and Demand contain IDs, project/material references, units, statuses,
date windows and the quantity objects. Material contains its canonical ID,
category, standard unit and specification mapping. All inputs must have passed
publication/provenance validation. This evaluator is not an intake/review gate.

The evaluator checks:

1. Different source and recipient projects.
2. CONFIRMED stock with positive uncommitted quantity.
3. UNUSED condition; unknown/recovered condition requires review.
4. A lot code or nonblank evidence reference as a prototype traceability hint.
   This is not verification of real evidence, ownership or engineering safety.
5. OPEN, confirmed outstanding demand with positive uncommitted need.
6. Matching canonical material ID, category and specifications. Distinct IDs
   are rejected even when names resemble each other. Alternative equivalence
   requires a separately designed reviewed catalogue relationship.
7. Exact pcs units on supply, demand and both material records. Conversions are
   unsupported in this draft.
8. Complete category-specific critical specifications and a feasible date window.

Conservative draft critical fields are material type, dimensions and intended
use; pavers add colour/finish, bricks add grade, tiles add thickness/colour/finish.
Callers can explicitly require additional fields, e.g. slip_rating for a floor
application, using extra_required_spec_fields. These are prototype completeness
checks and do not certify engineering suitability. The team must settle and
version the context-specific policy before broader catalogue use.

Known blocking reasons take precedence over review flags; all reasons are
retained in deterministic order. Invalid input relationships or contradictory
balances raise ValueError. Result reason codes are draft domain codes: existing
Document 08 codes are reused where applicable; new codes need shared DTO/error
mapping agreement before HTTP integration.

### Dates and future releases

planning_date and lead_time_days are explicit inputs. The approved demo policy
is one calendar day within the same township and two across different townships;
see [snapshot mapping and policy](OPTIMISATION_SNAPSHOT_MAPPING.md).
No wall clock or route speed is silently assumed. Unknown lead time produces REVIEW_REQUIRED.
An explicit zero is permitted only as a declared same-day planning assumption.

This draft treats available_until as the final dispatch date and needed_from
as the earliest permitted receipt date. Material may wait at source before
dispatch; early recipient storage is not assumed. With lead time L:

```text
earliest_dispatch = max(planning_date, available_from, needed_from - L)
earliest_delivery = earliest_dispatch + L
```

Dispatch must fall in the source window; delivery must fall in the recipient
window. This dispatch/receipt interpretation is an explicit draft assumption to
harmonise with Member 4's transfer/scheduling contract. Dates are calendar days;
business calendars, partial-day cutoffs and route capacity are not modelled.

Confirmed future supply can be ELIGIBLE for planning if it meets the deadline.
source_reservable_quantity_on_planning_date is still zero before release.
That field is a source balance estimate, not permission to reserve this pair.
A reservation command must recheck the whole pair and both balances atomically.

### Outputs

EligibilityResult contains pair IDs, compatibility_result, reason_codes,
max_allocatable_quantity, source and recipient balances, today's source balance,
earliest dispatch/delivery dates, planning date, lead time and extra required
fields. Noneligible caps are zero. For an eligible pair:

```text
max_allocatable_quantity = min(source_uncommitted, demand_newly_allocatable)
```

These are pair limits, not a multi-pair allocation plan. For example, two
candidates can each show a 100-pcs cap against SUP-005, which only has 100 total.
A later allocator must maintain shared temporary budgets and cannot add both
caps as executable allocations. No IDs, historical runs or proposals are written.

Carbon data is independent: missing mass/factors do not invalidate an otherwise
operationally eligible pair. Member 4 must supply a transparent complete or
incomplete environmental assessment for later strategy scoring.

## Example without Firebase or FastAPI

```python
from datetime import date
from backend.app.domain.eligibility import (
    Demand, DemandQuantity, Material, Supply, SupplyQuantity, evaluate_eligibility,
)
from backend.app.domain.lead_time import demo_township_lead_time_days

material = Material("MAT-002", "PAVING_BLOCK", "pcs", {
    "material_type": "concrete", "length_mm": 200, "width_mm": 100,
    "thickness_mm": 80, "colour": "grey", "finish": "smooth",
    "intended_use": "landscape paving",
})
supply = Supply(
    "SUP-003", "PRJ-001", "MAT-002", "pcs", "CONFIRMED", "UNUSED",
    date(2026, 9, 26), None, SupplyQuantity(800, 300, 0),
    batch_or_lot_code="DEMO-LOT-003",
)
demand = Demand(
    "DEM-003", "PRJ-004", "MAT-002", "pcs", "OPEN", True,
    date(2026, 9, 27), date(2026, 10, 30), DemandQuantity(500, 0, 300),
)
result = evaluate_eligibility(
    supply, demand, material, material,
    planning_date=date(2026, 10, 12),
    lead_time_days=demo_township_lead_time_days("Elmina", "Nilai Impian"),
)
assert result.compatibility_result == "ELIGIBLE"
assert result.max_allocatable_quantity == 200
```

## What is needed next

The evaluator uses only Python's standard library. The implemented
[snapshot mapper](OPTIMISATION_SNAPSHOT_MAPPING.md) uses the existing Pydantic
registry at its input boundary. Run from the repo root:

```bash
source .venv/bin/activate
python3 -m unittest tests.test_candidates tests.test_lead_time tests.test_snapshot_mapping tests.test_eligibility tests.test_seed -v
```

The tests adapt existing fixture records at the test boundary and exercise
commitments, partial reuse, status/condition/spec/unit/date failures, unknown
timing, future releases, invalid balances, deterministic output and no mutation.
They do not claim database concurrency or full optimisation acceptance.

Before integrating this into a working allocation engine:

1. Connect the implemented pure snapshot mapper to a repository that retrieves
   consistent record collections. The mapper validates publication provenance,
   reconciles counters, derives unresolved promises and converts dates. Database
   consistency and future residual-resolution/return semantics remain separate.
2. Harmonise the draft critical-specification and date-window policies with the
   team. The demo township lead-time policy is selected; replace it with agreed
   route-specific inputs when available and preserve the assumption version.
3. Use the implemented [candidate generator](OPTIMISATION_CANDIDATES.md), then add
   an allocator enforcing shared source/recipient budgets. MAX_REUSE is defined
   as allocated pcs; incomplete-carbon scoring policy still needs agreement.
4. Integrate Member 4's forecast interface and approved deterministic tie-breaks.
5. Add Pydantic HTTP DTO/error mapping, input snapshot hashing and named
   persistence operations for runs/proposals in a later integration task.
6. Member 4 must atomically revalidate reservation, lifecycle and residual writes.
   Pure eligibility tests cannot establish race-safe reservation correctness.

The seed, schemas, FastAPI routes and frontend remain unchanged. This draft
does not require OR-Tools, cloud setup or a running emulator.
