# Candidate pair construction

`backend/app/domain/candidates.py::generate_candidate_pairs` builds evaluated source/recipient pairs from a validated DomainSnapshot. It is deterministic, read-only and independent of Firebase/FastAPI.

## Inputs and policy

Catalogue identity is specific and reviewed upstream. Candidate construction does not infer cross-ID equivalence, require a category whitelist or certify suitability. For each relevant source/recipient it calls [eligibility](OPTIMISATION_ELIGIBILITY.md) with current material snapshots, date, quantities and the documented township lead time.

Only confirmed unused traceable supply and confirmed open recipient need can yield an eligible positive-cap pair. Self-project transfer, conflicts, incomparable units, insufficient budgets and impossible/unknown timing retain their reasons; no speculative factor or conversion makes a pair eligible.

Current runtime supports catalogue-unit exact quantities. A pair cap is the lesser source and recipient uncommitted capacity, not an independent budget to be added across all recipients. Later [allocation](OPTIMISATION_ALLOCATOR.md) enforces shared capacities and chooses quantities. Carbon calculation is separate and cannot make an operationally invalid pair eligible.

## Timing

Earliest dispatch/reservation=max(planning date, source available_from, recipient needed_from). Arrival adds one day in the same township or two across townships under the internal prototype policy. Dispatch must fit source availability and arrival meet the need-by deadline. A future feasible pair can appear as an opportunity, but actual confirmation still validates the current allowed date.

No straight-line distance, speed-based duration or lead-time override is inferred. Documented lead-time assumptions remain part of saved policy provenance even though routine UI hints need not repeat them.

## Result and use

The result retains evaluated pairs/reasons and eligible pairs, grouped coverage and lead-time policy identity. Stable IDs/order make repeated same-input construction reproducible. Empty candidates are a valid result; the caller must not invent a rejection cause that was not returned.

Pure candidate construction does not write a run/proposal, select an objective, reserve stock, create recipient commitments or claim actual reuse. Only current server-generated generations can proceed through explicit combined confirmation; stale snapshot eligibility is not operational authority.

Sources: [candidate implementation](../backend/app/domain/candidates.py), [mapped snapshot](OPTIMISATION_SNAPSHOT_MAPPING.md), [eligibility tests](../tests/test_eligibility.py), [matching API](OPTIMISATION_COMPARISON_API.md).
