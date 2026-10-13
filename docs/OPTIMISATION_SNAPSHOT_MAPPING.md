# Optimisation snapshot mapping

Member 3's pure mapping function accepts existing record collections and returns
the inputs for the eligibility evaluator. It does not fetch records, write to the
database, reserve materials, run a solver or register FastAPI routes.

Implementation: [snapshot_mapping.py](../backend/app/domain/snapshot_mapping.py).
Tests: [test_snapshot_mapping.py](../tests/test_snapshot_mapping.py).
Evaluator: [eligibility draft](OPTIMISATION_ELIGIBILITY_DRAFT.md).
External fields: [data dictionary](SEED_DATA_DICTIONARY.md).

## Boundary and input contract

Call map_record_collections with an explicit Python as_of_date and these nine
collections, using their existing full snake_case records:

| Collection | Why it is needed |
|---|---|
| projects | Validate source, recipient and document project references |
| materials | Construct canonical material objects and resolve references |
| documents | Resolve linked extraction provenance to a project/source type |
| extracted_rows | Validate reviewed provenance of published offers/requests |
| supply_offers | Source status, availability, confirmation and counters |
| demand_requests | Recipient status, need window and fulfilment |
| optimisation_runs | Resolve the existing proposal-to-run relationship |
| allocation_proposals | Link transfers to supply and demand |
| transfers | Reconcile stock/use and derive unresolved incoming promises |

Lists, tuples and other iterables of record mappings are accepted. Records are
validated using terra.contract.MODELS, so field names, required fields, nullable
fields and enum values remain those of the shared dictionary. There are no
fixture count requirements, fixed baseline IDs or requirement to label every
record synthetic. Dates use YYYY-MM-DD and historical timestamps use +08:00.
Future availability/deadline dates are allowed; recorded timestamps after the
supplied snapshot date are rejected.

This is a current-state snapshot, not a historical optimisation input_snapshot.
Historical run snapshots do not contain the full provenance/transfer collections
needed here. Historical proposals are retained as history and do not consume
stock merely by being proposed or selected. Their original feasibility is not
re-evaluated against today's depleted supplies. This mapper checks their shape
and references; it is not a full historical solver/hash/audit validator.

The caller must provide a coherent, complete set of related records. A future
repository must retrieve that set consistently; the function cannot prove that
independently fetched collections share a database revision. Missing contributing
transfers normally cause reconciliation failure, but coordinated omissions or
stale counters cannot always be discovered without a repository snapshot guarantee.

## Mapping and validation

1. Validate shared record shapes, numeric/date fields and duplicate IDs.
2. Resolve foreign keys across the supplied collections.
3. For non-null origin_document_row_id, require ACCEPTED/CORRECTED review,
   matching project/material and a supported published source kind. BOQ/PO facts
   do not automatically become stock/demand. Null origins remain permitted for
   explicit manual records; no extraction row is automatically published.
4. Resolve each transfer through its proposal. Require selected eligible
   proposals, matching material/unit, distinct projects, valid stages/quantities,
   confirmation prerequisites and timestamp chronology. One transfer per proposal.
5. Recompute source holds, dispatched quantities and recipient actual fulfilment
   from transfers. Reject drift against cached offer/demand counters. Never repair
   the supplied records or silently clamp a negative balance.
6. Derive incoming_committed_quantity for each demand. RESERVED, IN_TRANSIT,
   RECEIVED and REUSED retain approved_quantity minus actually_used_quantity.
   REQUESTED/APPROVED and cancelled-before-dispatch transfers contribute zero.
7. Construct SupplyQuantity/DemandQuantity with every counter explicitly provided,
   then Supply/Demand/Material with Python dates and immutable material specs.

Origin validation checks the published-record contract, not actual ownership,
engineering suitability or the truth of evidence. Accepted inventory rows remain
provenance; the mapper preserves the separately published offer's status.
More advanced procurement reconciliation needs an agreed publication contract.

The current transfer structure has no structured residual-resolution or return
fields. Partial REUSED promises are conservatively retained. Notes are not parsed
as instructions to release commitments. Post-dispatch cancellation is rejected
with SnapshotMappingError; it does not restore stock. This implements the current
baseline safely, not the complete future SRS residual-disposition workflow.
Member 4's later structured resolution contract will require coordinated mapping
and test updates. Transfer events and return transactions are not consumed here.

## Output

DomainSnapshot contains as_of_date and read-only maps indexed by ID:

- materials: Material objects with detached immutable specification dictionaries.
- supplies: Supply objects, including validated source quantity models.
- demands: Demand objects, including derived incoming commitments.
- incoming_transfer_ids_by_demand: contributing transfer IDs for explanation.

These internal Python maps do not replace database tables or HTTP DTOs. Output
order is deterministic by ID. Input records are not mutated, and changes to the
input records after mapping cannot alter the returned material specifications.
On failure the function raises SnapshotMappingError and returns no partial result.
Future HTTP error translation remains at the API boundary.

## Runnable example from the existing baseline

Run this Python example from the repository root with .venv activated. Loading
the file is the caller's job; the mapper itself performs no file or network I/O.

```python
from datetime import date
from terra.validation import load
from backend.app.domain.snapshot_mapping import map_record_collections
from backend.app.domain.eligibility import evaluate_eligibility

records = load()
names = (
    "projects", "materials", "documents", "extracted_rows", "supply_offers",
    "demand_requests", "optimisation_runs", "allocation_proposals", "transfers",
)
snapshot = map_record_collections(
    as_of_date=date.fromisoformat(records["metadata"]["as_of_date"]),
    **{name: records[name] for name in names},
)
supply = snapshot.supplies["SUP-003"]
demand = snapshot.demands["DEM-003"]
result = evaluate_eligibility(
    supply, demand,
    snapshot.materials[supply.material_id], snapshot.materials[demand.material_id],
    planning_date=snapshot.as_of_date,
    lead_time_days=1,  # Explicit synthetic calendar-day assumption.
)
assert snapshot.incoming_transfer_ids_by_demand["DEM-003"] == ("TRF-003",)
assert demand.quantity.incoming_committed_quantity == 300
assert result.max_allocatable_quantity == 200
print(result)
```

## Verification and next boundary

```bash
source .venv/bin/activate
python3 -m unittest tests.test_snapshot_mapping tests.test_eligibility tests.test_seed -v
```

The mapper tests cover baseline-to-evaluator integration, lifecycle commitment
effects, unresolved partial use, duplicate/orphan records, contract shape errors,
review provenance, inconsistent counters, incomplete transfer input, overbooking,
future history, order independence and detached output. They use in-memory records
and require no emulator or cloud connection. The mapping uses the existing
Pydantic dependency through the shared contract registry; the evaluator remains
standard-library-only.

Next implement a multi-pair allocator over these prepared inputs, keeping shared
temporary source and recipient budgets. Database snapshot retrieval, reservation
concurrency, carbon scoring and general residual resolution remain separate work.
