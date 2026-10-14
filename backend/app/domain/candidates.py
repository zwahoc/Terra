"""Generate explained candidate pairs from prepared inputs; no allocation/I/O."""
from dataclasses import dataclass
from datetime import date

from .eligibility import EligibilityResult, evaluate_eligibility
from .lead_time import DEMO_LEAD_TIME_POLICY_VERSION
from .snapshot_mapping import DomainSnapshot


@dataclass(frozen=True)
class CandidatePairs:
    planning_date: date
    lead_time_policy_version: str
    pairs: tuple[EligibilityResult, ...]

    @property
    def eligible(self) -> tuple[EligibilityResult, ...]:
        return tuple(pair for pair in self.pairs if pair.compatibility_result == 'ELIGIBLE')

    @property
    def review_required(self) -> tuple[EligibilityResult, ...]:
        return tuple(pair for pair in self.pairs if pair.compatibility_result == 'REVIEW_REQUIRED')

    @property
    def ineligible(self) -> tuple[EligibilityResult, ...]:
        return tuple(pair for pair in self.pairs if pair.compatibility_result == 'INELIGIBLE')


def generate_candidate_pairs(snapshot: DomainSnapshot) -> CandidatePairs:
    """Evaluate each cross-project pair once, ordered by supply ID then demand ID.

    Retain unavailable, incompatible and review-required pairs for explanation;
    only same-project combinations are omitted. Pair quantity caps share the
    snapshot balances and cannot be summed as a feasible allocation plan.

    The explicit demo policy is 1 calendar day within a township and 2 across
    townships. Unknown township produces the evaluator's review result. Historical
    proposals/transfer dates are not regenerated or reinterpreted by this policy.
    """
    pairs = []
    for sid in sorted(snapshot.supplies):
        supply = snapshot.supplies[sid]
        for did in sorted(snapshot.demands):
            demand = snapshot.demands[did]
            if supply.source_project_id == demand.destination_project_id:
                continue
            pairs.append(evaluate_eligibility(
                supply, demand,
                snapshot.materials[supply.material_id],
                snapshot.materials[demand.material_id],
                planning_date=snapshot.as_of_date,
                lead_time_days=snapshot.demo_lead_time_days(sid, did),
            ))
    return CandidatePairs(snapshot.as_of_date, DEMO_LEAD_TIME_POLICY_VERSION, tuple(pairs))
