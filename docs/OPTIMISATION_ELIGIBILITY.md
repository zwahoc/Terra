# Reviewed-catalogue eligibility and quantity checks

`backend/app/domain/eligibility.py` evaluates one source/recipient pair from published validated snapshots. It performs no read/write, allocation, reservation, engineering certification or carbon calculation. Its current policy is `reviewed-catalogue-identity-v2`.

## Material boundary

A specific published catalogue ID already represents the operator-reviewed material/specification identity. The evaluator requires matching identity and consistent snapshot category/specifications/unit. It does not repeat a preset family whitelist or demand hardcoded paver/brick/tile fields merely because a category name is unfamiliar.

Relevant known conflicts remain blocked. Different IDs are not automatically equivalent even if names look similar. Explicit `extra_required_spec_fields` supplied by a caller remain context requirements, separate from removed family defaults. Positive numeric millimetre strings are validated where such explicit fields are requested; ambiguous/unit-bearing values stay unresolved. Review is not independent technical certification.

## Source conditions

- Source and recipient projects must differ.
- Offer is CONFIRMED, with UNUSED condition and positive confirmed uncommitted quantity.
- Traceability and required confirmation evidence remain applicable; missing evidence is not invented.
- Identity/specification/unit snapshots agree with the referenced catalogue.
- Availability and recipient timing permit dispatch/arrival. Potential/suspended/closed supply is not reservable.

For confirmed quantity Q, active reservedR and dispatched D, uncommitted=Q-R-D with 0≤R+D≤Q. Reservable_on(date) is zero before/after its valid window or without confirmed unused status. A future opportunity may be planned but not confirmed before its allowed start.

## Recipient conditions

Demand is OPEN and outstanding need is explicitly confirmed. Required quantityN is positive; actually fulfilledF and active incoming C are nonnegative with F+C≤N. Newly allocatable=N-F-C. Closed/cancelled/fulfilled demand cannot create extra capacity. A cancelled demand with unresolved incoming commitments is invalid.

Active incoming starts with reservation and includes promised units through dispatch/receipt/partial use. It is not released by a status label or repeated alternative proposal. Missing amounts remain unknown rather than zero.

## Timing and cap

Earliest dispatch/reservation=max(planning_date, source.available_from, demand.needed_from). Add the supplied lead time, require arrival≤required_by and dispatch≤available_until where set. The current documented township policy supplies one day same-township/two days different-township; unknown lead-time context remains a guard rather than a fabricated route duration. Route kilometres affect carbon/tie-breaking, not an invented travel-speed calculation.

For an eligible pair, max_allocatable_quantity=min(source uncommitted, recipient newly allocatable). Pair caps are not additive across competing pairs; the allocator must enforce common budgets.

## Outputs and integrity

EligibilityResult includes source/demand IDs, ELIGIBLE/REVIEW_REQUIRED/INELIGIBLE, reason_codes, cap, source/demand budget observations, reservable_on_planning_date, earliest dispatch/arrival, planning date, lead time and explicit extra-field requirements. Ineligible/review-required results have zero executable allocation cap. Known blockers take precedence over review flags.

Pure eligibility is a snapshot decision. Confirmation must revalidate current dependencies, date, source/recipient capacity and suitability atomically. Historical transfers use saved provenance; today's depleted supply does not retroactively invalidate a legitimate past movement.

[Implementation](../backend/app/domain/eligibility.py), [tests](../tests/test_eligibility.py), [reviewed identity regressions](../tests/test_reviewed_catalogue_matching.py), [workflow](01_BUSINESS_WORKFLOW.md), [candidate construction](OPTIMISATION_CANDIDATES.md).
