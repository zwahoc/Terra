"""Exact quantity, deadline and supplied-linear-carbon allocation; no I/O/writes."""
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping
from fractions import Fraction
from dataclasses import fields, is_dataclass
import hashlib
import json

from .candidates import generate_candidate_pairs
from .eligibility import EligibilityResult
from .snapshot_mapping import DomainSnapshot


@dataclass(frozen=True)
class PlannedAllocation:
    supply_offer_id: str
    demand_request_id: str
    material_id: str
    proposed_quantity: int
    unit: str
    earliest_dispatch_date: date
    earliest_delivery_date: date
    required_by: date
    distance_km: Decimal | None
    route_distance_id: str | None
    reason_codes: tuple[str, ...]
    compatibility_result: str = 'ELIGIBLE'
    status: str = 'PROPOSED'


@dataclass(frozen=True)
class AllocationPlan:
    objective: str
    solver_status: str
    planning_date: date
    total_proposed_quantity: int
    allocations: tuple[PlannedAllocation, ...]
    remaining_uncommitted_quantity_by_supply: Mapping[str, int]
    remaining_newly_allocatable_quantity_by_demand: Mapping[str, int]
    missing_distance_pairs: tuple[tuple[str, str], ...]
    assumptions: Mapping[str, object]
    estimated_net_avoided_kgco2e: Decimal | None = None
    incomplete_carbon: bool = False
    unscored_pairs: tuple[tuple[str, str], ...] = ()
    negative_carbon_pairs: tuple[tuple[str, str], ...] = ()
    carbon_scoring_available: bool | None = None


def allocation_snapshot_hash(snapshot: DomainSnapshot) -> str:
    """Fingerprint mapped allocation inputs, not the full database/carbon context."""
    def canonical(value):
        if is_dataclass(value):
            return {f.name: canonical(getattr(value, f.name)) for f in fields(value)}
        if isinstance(value, Mapping):
            return [[canonical(k), canonical(v)] for k, v in sorted(value.items())]
        if isinstance(value, (tuple, list)):
            return [canonical(v) for v in value]
        if isinstance(value, (date, Decimal)):
            return str(value)
        return value
    return hashlib.sha256(json.dumps(canonical(snapshot), sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class LinearCarbonScores:
    """Member 4 guarantees score(q)=q*coefficient over each eligible pair's cap.

    Context ID binds full material/factor/boundary inputs outside DomainSnapshot.
    Missing/None coefficients represent unavailable assessments, never zero.
    """
    allocation_snapshot_hash: str
    factor_dataset_version: str
    carbon_context_id: str
    net_kgco2e_per_piece: Mapping[tuple[str, str], Decimal | None]
    linear_scaling_guaranteed: bool

    def __post_init__(self):
        for value in (self.allocation_snapshot_hash, self.factor_dataset_version, self.carbon_context_id):
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Carbon snapshot, factor version and context IDs are required')
        if self.linear_scaling_guaranteed is not True:
            raise ValueError('Carbon scoring must explicitly guarantee linear scaling')
        values = dict(self.net_kgco2e_per_piece)
        for pair, coefficient in values.items():
            if (not isinstance(pair, tuple) or len(pair) != 2
                    or any(not isinstance(v, str) or not v for v in pair)):
                raise ValueError('Carbon scores require supply/demand ID pairs')
            if coefficient is not None and (not isinstance(coefficient, Decimal)
                                            or not coefficient.is_finite()):
                raise ValueError('Carbon coefficients must be finite Decimal values or None')
        object.__setattr__(self, 'net_kgco2e_per_piece', MappingProxyType(values))


def _pair_id(pair: EligibilityResult) -> tuple[str, str]:
    return pair.supply_offer_id, pair.demand_request_id


def _maximum_flow(supplies, demands, pairs):
    """Edmonds-Karp residual flow; integer capacities and deterministic BFS."""
    source, sink = ('source',), ('sink',)
    adjacency = defaultdict(list)
    capacity = {}

    def arc(a, b, cap):
        adjacency[a].append(b)
        adjacency[b].append(a)
        capacity[a, b] = cap
        capacity[b, a] = 0

    for sid in sorted(supplies):
        arc(source, ('supply', sid), supplies[sid])
    for pair in pairs:
        arc(('supply', pair.supply_offer_id), ('demand', pair.demand_request_id),
            pair.max_allocatable_quantity)
    for did in sorted(demands):
        arc(('demand', did), sink, demands[did])
    total = 0
    while True:
        parents = {source: None}
        queue = deque([source])
        while queue and sink not in parents:
            node = queue.popleft()
            for other in adjacency[node]:
                if other not in parents and capacity[node, other] > 0:
                    parents[other] = node
                    queue.append(other)
        if sink not in parents:
            break
        path, node = [], sink
        while parents[node] is not None:
            previous = parents[node]
            path.append((previous, node))
            node = previous
        amount = min(capacity[a, b] for a, b in path)
        for a, b in path:
            capacity[a, b] -= amount
            capacity[b, a] += amount
        total += amount
    flows = {_pair_id(pair): capacity[('demand', pair.demand_request_id),
                                     ('supply', pair.supply_offer_id)] for pair in pairs}
    return total, flows


def _rank_pairs(snapshot, pairs):
    """Rank deadline/delivery groups; missing distance uses IDs for the group.

    Skipping the distance comparison for a whole tied group gives a transitive,
    deterministic order without pretending unknown km is zero or infinity.
    """
    groups = defaultdict(list)
    distances = {}
    for pair in pairs:
        route_key = tuple(sorted((snapshot.supplies[pair.supply_offer_id].source_project_id,
                                  snapshot.demands[pair.demand_request_id].destination_project_id)))
        distances[_pair_id(pair)] = snapshot.route_distances.get(route_key)
        groups[(snapshot.demands[pair.demand_request_id].required_by,
                pair.earliest_delivery_date)].append(pair)

    def stable_ids(pair):
        return (snapshot.supplies[pair.supply_offer_id].source_project_id,
                snapshot.demands[pair.demand_request_id].destination_project_id,
                pair.supply_offer_id, pair.demand_request_id)

    ranked, distance_fallback = [], set()
    for deadline_delivery in sorted(groups):
        group = groups[deadline_delivery]
        if any(distances[_pair_id(pair)] is None for pair in group):
            ranked.extend(sorted(group, key=stable_ids))
            distance_fallback.update(_pair_id(pair) for pair in group)
        else:
            ranked.extend(sorted(group, key=lambda pair: (distances[_pair_id(pair)].distance_km,
                                                          stable_ids(pair))))
    return ranked, distances, distance_fallback


def allocate_max_reuse(snapshot: DomainSnapshot) -> AllocationPlan:
    """Maximise pcs, then maximise each ranked pair quantity at that same total.

    First compute maximum flow F. For each preferred pair, find the greatest
    quantity that can be fixed while the remaining graph still completes F.
    Binary search starts at a known feasible flow on that edge. Thus preferences
    cannot sacrifice quantity, unlike greedy first-match assignment.

    Generates candidates once for this plan. The only budgets changed are local
    dictionaries; no source holds, fulfilment, proposals or transfers are written.
    """
    candidates = generate_candidate_pairs(snapshot)
    ranked, routes, fallback = _rank_pairs(snapshot, candidates.eligible)
    supplies = {sid: s.quantity.uncommitted_quantity for sid, s in snapshot.supplies.items()}
    demands = {did: (d.quantity.newly_allocatable_quantity
                     if d.request_status == 'OPEN' and d.is_outstanding_need_confirmed else 0)
               for did, d in snapshot.demands.items()}
    optimum, _ = _maximum_flow(supplies, demands, ranked)
    outstanding = optimum
    allocations = []
    for index, pair in enumerate(ranked):
        if outstanding == 0:
            break
        current = ranked[index:]
        remaining = ranked[index + 1:]
        feasible_total, feasible_flows = _maximum_flow(supplies, demands, current)
        if feasible_total != outstanding:
            raise RuntimeError('Allocator lost the quantity optimum')
        sid, did = _pair_id(pair)
        low = feasible_flows[sid, did]
        high = min(pair.max_allocatable_quantity, supplies[sid], demands[did], outstanding)
        while low < high:
            quantity = (low + high + 1) // 2
            next_supplies, next_demands = dict(supplies), dict(demands)
            next_supplies[sid] -= quantity
            next_demands[did] -= quantity
            possible, _ = _maximum_flow(next_supplies, next_demands, remaining)
            if possible >= outstanding - quantity:
                low = quantity
            else:
                high = quantity - 1
        quantity = low
        supplies[sid] -= quantity
        demands[did] -= quantity
        outstanding -= quantity
        if quantity:
            route = routes[sid, did]
            reasons = pair.reason_codes + ('MAX_REUSE_QUANTITY_OPTIMUM', 'PAIR_PRIORITY_TIE_BREAK')
            if route is None:
                reasons += ('ROUTE_DISTANCE_MISSING',)
            if (sid, did) in fallback:
                reasons += ('DISTANCE_TIE_BREAK_UNAVAILABLE',)
            allocations.append(PlannedAllocation(
                sid, did, snapshot.supplies[sid].material_id, quantity, 'pcs',
                pair.earliest_dispatch_date, pair.earliest_delivery_date,
                snapshot.demands[did].required_by,
                route.distance_km if route else None, route.id if route else None, reasons,
            ))
    if outstanding:
        raise RuntimeError('Allocator failed to distribute maximum flow')
    return AllocationPlan(
        'MAX_REUSE', 'SUCCEEDED', snapshot.as_of_date, optimum, tuple(allocations),
        MappingProxyType(dict(sorted(supplies.items()))),
        MappingProxyType(dict(sorted(demands.items()))),
        tuple(sorted(pid for pid, route in routes.items() if route is None)),
        MappingProxyType({
            'algorithm_version': 'max-flow-lexicographic-pairs-v1',
            'quantity_unit': 'pcs',
            'reservation_timing_policy': 'reserve_and_dispatch_on_or_after_needed_from',
            'lead_time_policy_version': candidates.lead_time_policy_version,
            'lead_time_is_synthetic': True,
            'symmetric_demo_route_lookup': True,
            'tie_break_order': ('required_by', 'earliest_delivery', 'distance_km', 'source_project_id',
                                'destination_project_id', 'supply_offer_id', 'demand_request_id'),
            'missing_distance_policy': 'stable_ids_for_entire_equal_deadline_delivery_group',
        }),
    )


def _lexicographic_flow(supplies, demands, pairs, rewards):
    """Exact variable-volume maximum-reward flow with tuple-valued costs.

    Successive best residual paths preserve optimality at each flow volume.
    Reverse edges can reroute prior assignments. Stop when no positive reward
    path remains, so negative carbon is never forced to maximise volume.
    Fraction arithmetic avoids floating point/Decimal-context scoring errors.
    """
    source, sink = ('source',), ('sink',)
    nodes, edges = {source, sink}, []
    zero = tuple(Fraction(0) for _ in next(iter(rewards.values()), (0,)))

    def arc(a, b, capacity, reward):
        index = len(edges)
        edges.extend([[a, b, capacity, reward], [b, a, 0, tuple(-v for v in reward)]])
        nodes.update((a, b))
        return index

    for sid in sorted(supplies):
        arc(source, ('supply', sid), supplies[sid], zero)
    pair_edges = {}
    for pair in pairs:
        pair_edges[_pair_id(pair)] = arc(('supply', pair.supply_offer_id),
                                         ('demand', pair.demand_request_id),
                                         pair.max_allocatable_quantity, rewards[_pair_id(pair)])
    for did in sorted(demands):
        arc(('demand', did), sink, demands[did], zero)
    while True:
        distances, parents = {source: zero}, {}
        # Bellman-Ford longest paths in the residual graph; no positive cycles
        # exist after a best-path augmentation from an optimal flow.
        for _ in range(len(nodes) - 1):
            changed = False
            for index, (a, b, capacity, reward) in enumerate(edges):
                if capacity <= 0 or a not in distances or b == source or a == sink:
                    continue
                value = tuple(x + y for x, y in zip(distances[a], reward))
                if b not in distances or value > distances[b]:
                    distances[b], parents[b] = value, index
                    changed = True
            if not changed:
                break
        if sink not in distances or distances[sink] <= zero:
            break
        path, node = [], sink
        while node != source:
            index = parents[node]
            path.append(index)
            node = edges[index][0]
        quantity = min(edges[index][2] for index in path)
        for index in path:
            edges[index][2] -= quantity
            edges[index ^ 1][2] += quantity
    return {pair: edges[index ^ 1][2] for pair, index in pair_edges.items()}


def allocate(snapshot: DomainSnapshot, *, objective: str,
             carbon_scores: LinearCarbonScores | None = None,
             factor_dataset_version: str | None = None,
             carbon_context_id: str | None = None) -> AllocationPlan:
    """Dispatch one objective against immutable inputs; no persistence or I/O.

    Carbon callers must supply the expected full-context ID and factor version
    from shared orchestration, independently of the returned score batch.
    """
    if objective not in ('MAX_REUSE', 'EARLIEST_DEADLINE', 'MAX_NET_CO2E_AVOIDED'):
        raise ValueError(f'Unsupported allocation objective: {objective}')
    if objective == 'MAX_REUSE':
        if any(v is not None for v in (carbon_scores, factor_dataset_version, carbon_context_id)):
            raise ValueError('MAX_REUSE does not consume carbon scoring inputs')
        return allocate_max_reuse(snapshot)
    if objective == 'EARLIEST_DEADLINE' and any(
            v is not None for v in (carbon_scores, factor_dataset_version, carbon_context_id)):
        raise ValueError('EARLIEST_DEADLINE does not consume carbon scoring inputs')
    candidates = generate_candidate_pairs(snapshot)
    ranked, routes, fallback = _rank_pairs(snapshot, candidates.eligible)
    supplies = {sid: s.quantity.uncommitted_quantity for sid, s in snapshot.supplies.items()}
    demands = {did: (d.quantity.newly_allocatable_quantity
                     if d.request_status == 'OPEN' and d.is_outstanding_need_confirmed else 0)
               for did, d in snapshot.demands.items()}
    unscored, negative = (), ()
    assumptions = {
        'algorithm_version': 'exact-lexicographic-reward-flow-v1',
        'quantity_unit': 'pcs',
        'reservation_timing_policy': 'reserve_and_dispatch_on_or_after_needed_from',
        'lead_time_policy_version': candidates.lead_time_policy_version,
        'lead_time_is_synthetic': True,
        'symmetric_demo_route_lookup': True,
        'missing_distance_policy': 'stable_ids_for_entire_equal_deadline_delivery_group',
        'pair_tie_break_order': ('required_by', 'earliest_delivery', 'distance_km',
                                'source_project_id', 'destination_project_id',
                                'supply_offer_id', 'demand_request_id'),
    }
    if objective == 'MAX_NET_CO2E_AVOIDED':
        if not isinstance(carbon_scores, LinearCarbonScores):
            raise ValueError('MAX_NET_CO2E_AVOIDED requires a LinearCarbonScores batch')
        if (carbon_scores.allocation_snapshot_hash != allocation_snapshot_hash(snapshot)
                or factor_dataset_version != carbon_scores.factor_dataset_version
                or carbon_context_id != carbon_scores.carbon_context_id):
            raise ValueError('Carbon scores do not match the expected snapshot/factor/context')
        eligible_ids = {_pair_id(p) for p in ranked}
        if set(carbon_scores.net_kgco2e_per_piece) - eligible_ids:
            raise ValueError('Carbon scores reference unknown or noneligible pairs')
        unscored = tuple(sorted(pid for pid in eligible_ids
                                if carbon_scores.net_kgco2e_per_piece.get(pid) is None))
        negative = tuple(sorted(pid for pid in eligible_ids
                                if carbon_scores.net_kgco2e_per_piece.get(pid) is not None
                                and carbon_scores.net_kgco2e_per_piece[pid] < 0))
        excluded = set(unscored + negative)
        ranked = [p for p in ranked if _pair_id(p) not in excluded]
        primary = {_pair_id(p): (Fraction(carbon_scores.net_kgco2e_per_piece[_pair_id(p)]),
                                 Fraction(1)) for p in ranked}
        assumptions.update({
            'primary_policy': 'maximum_net_carbon_then_maximum_pcs_then_pair_preferences',
            'factor_dataset_version': factor_dataset_version,
            'carbon_context_id': carbon_context_id,
            'allocation_snapshot_hash': carbon_scores.allocation_snapshot_hash,
            'carbon_model': 'member4_guaranteed_linear_per_piece',
            'missing_carbon_policy': 'exclude_and_flag',
            'negative_carbon_policy': 'exclude',
        })
    else:
        deadlines = sorted({snapshot.demands[p.demand_request_id].required_by for p in ranked})
        primary = {_pair_id(p): tuple(Fraction(int(
            snapshot.demands[p.demand_request_id].required_by == deadline))
            for deadline in deadlines) for p in ranked}
        assumptions.update({'primary_policy': 'maximum_pcs_by_deadline_earliest_first',
                            'deadline_groups': tuple(d.isoformat() for d in deadlines)})
    rewards = {_pair_id(p): primary[_pair_id(p)] + tuple(Fraction(int(i == j))
               for j in range(len(ranked))) for i, p in enumerate(ranked)}
    quantities = _lexicographic_flow(supplies, demands, ranked, rewards)
    allocations = []
    for pair in ranked:
        sid, did = _pair_id(pair)
        quantity = quantities[sid, did]
        if not quantity:
            continue
        supplies[sid] -= quantity
        demands[did] -= quantity
        route = routes[sid, did]
        reasons = pair.reason_codes + (objective + '_OPTIMUM', 'PAIR_PRIORITY_TIE_BREAK')
        if route is None:
            reasons += ('ROUTE_DISTANCE_MISSING',)
        if (sid, did) in fallback:
            reasons += ('DISTANCE_TIE_BREAK_UNAVAILABLE',)
        allocations.append(PlannedAllocation(
            sid, did, snapshot.supplies[sid].material_id, quantity, 'pcs',
            pair.earliest_dispatch_date, pair.earliest_delivery_date,
            snapshot.demands[did].required_by, route.distance_km if route else None,
            route.id if route else None, reasons))
    estimated = None
    available = None
    if carbon_scores is not None:
        from decimal import localcontext
        net = sum((Fraction(carbon_scores.net_kgco2e_per_piece[_pair_id(p)])
                   * quantities[_pair_id(p)] for p in ranked), Fraction(0))
        with localcontext() as context:
            context.prec = len(str(abs(net.numerator))) + len(str(net.denominator)) + 2
            estimated = Decimal(net.numerator) / Decimal(net.denominator)
        available = len(unscored) < len(candidates.eligible) or not candidates.eligible
        if not available:
            estimated = None
    return AllocationPlan(
        objective, 'SUCCEEDED', snapshot.as_of_date,
        sum(a.proposed_quantity for a in allocations), tuple(allocations),
        MappingProxyType(dict(sorted(supplies.items()))),
        MappingProxyType(dict(sorted(demands.items()))),
        tuple(sorted(pid for pid, route in routes.items() if route is None)),
        MappingProxyType(assumptions), estimated, bool(unscored), unscored, negative, available)
