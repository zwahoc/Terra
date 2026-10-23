# Optimisation snapshot mapping

`backend/app/domain/snapshot_mapping.py::map_record_collections` maps supplied complete record collections into immutable DomainSnapshot inputs. It performs no I/O or operational writes. The caller owns consistent retrieval; unrelated independently read collections are not automatically one transaction snapshot.

## Collections and validation

Inputs include projects, materials, documents, extracted_rows, supply_offers, demand_requests, optimisation_runs, allocation_proposals, transfers and route_distances, plus the planning date. Carbon factors/complete environmental context are managed by the forecast calculator separately. Runtime shapes use `RUNTIME_MODELS`; canonical seed count/category restrictions are not imposed on arbitrary current data.

The mapper:

1. Validates field shapes, exact nonnegative quantities, unit aliases, strict dates/timestamps and unique stable IDs.
2. Resolves required relationships across all supplied records.
3. For a non-null origin row, requires accepted/corrected source evidence with matching material/project and compatible information kind. BOQ/PO origin is not automatically released stock or uncovered demand. Explicit manual null origins remain supported.
4. Validates each transfer through a selected eligible proposal, different source/recipient projects and consistent identity/unit.
5. Checks used≤received≤dispatched≤approved≤proposed, reserved+dispatched≤approved, confirmations, state-specific counters and chronological request/receipt/use timestamps.
6. Reconciles source active holds/dispatched amounts and recipient fulfilment/incoming commitments across every contributing transfer.
7. Constructs immutable materials/supplies/demands, project township lookup, incoming transfer membership and route lookup without mutating source collections.

Future availability/deadlines are allowed; recorded events after the supplied snapshot date are not. Null confirmation/mass/evidence is not converted into certainty. Registered historical JSON identities are handled by their upstream compatibility boundary, not silently promoted by the mapper.

## Physical state and budgets

RESERVED holds positive stock with no dispatch; IN_TRANSIT records issued stock; RECEIVED has arrival and zero use; REUSED has positive cumulative use with received remainder still committed. CANCELLED cannot have dispatch or surviving holds in this version. REQUESTED/APPROVED remain unreserved historical states.

Incoming commitments begin at reservation and remain until used or valid cancellation. An unused received balance is not released just because status=REUSED. Partial historical discrepancy records need preserved provenance and explicit current policy; mapping does not implement a return/restock workflow.

Historical unexecuted proposals do not consume source/demand budgets. They are shape/reference-checked, not rerun against today's stock to invalidate the past. Historical input_snapshot and allocation_snapshot_hash have different roles from a complete coherent current operational snapshot.

## Routes and lead time

The documented fixture route lookup is symmetric over a canonical unordered project pair. It preserves route ID, exact distance and synthetic status. Ambiguous/missing route distance remains unknown; the mapper does not invent one.

Township-based lead time is one day same-township and two across townships, separately documented as an internal assumption. Route km is a carbon/tie input; it is not converted to duration by assumed driving speed.

## Consistency and hashing

Services page required collections under OperationalVersion bracketing. A revision crossing the read rejects the mixed snapshot. Matched scope dependencies include workspace identity, material/specifications, quantities/commitments, projects, routes/factors, day and policy version. Current generation commits compare expected source/scope state again.

Mapped allocation hash is not the persisted full database input hash, and neither replaces carbon_context_id. Missing contributing transfers normally break reconciliation, but a pure mapper cannot detect every coordinated omission. Repository/transaction guards remain necessary.

Sources: [mapper](../backend/app/domain/snapshot_mapping.py), [matching service](../backend/app/services/matching_service.py), [forecast calculator](../backend/app/services/forecast_preview_service.py), [data model](02_DATA_MODEL_CONTRACT.md).
