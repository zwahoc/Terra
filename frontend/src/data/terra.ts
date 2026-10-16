import seed from '../../../data/terra_seed.json';

export type SupplyStatus = 'POTENTIAL' | 'CONFIRMED' | 'SUSPENDED' | 'CLOSED';
export type TransferStatus =
  | 'REQUESTED'
  | 'APPROVED'
  | 'RESERVED'
  | 'IN_TRANSIT'
  | 'RECEIVED'
  | 'REUSED'
  | 'CANCELLED';

export const terra = seed;

const byId = <T extends { id: string }>(items: T[]) =>
  new Map(items.map((item) => [item.id, item]));

const projects = byId(seed.projects);
const materials = byId(seed.materials);
const offers = byId(seed.supply_offers);
const demands = byId(seed.demand_requests);
const proposals = byId(seed.allocation_proposals);

const routeFor = (fromProjectId: string, toProjectId: string) =>
  seed.route_distances.find(
    (route) =>
      (route.from_project_id === fromProjectId && route.to_project_id === toProjectId) ||
      (route.to_project_id === fromProjectId && route.from_project_id === toProjectId),
  );

export const projectName = (id: string) => projects.get(id)?.name ?? id;
export const materialName = (id: string) => materials.get(id)?.canonical_name ?? id;

export const reservableQuantity = (offer: (typeof seed.supply_offers)[number]) =>
  offer.surplus_status === 'CONFIRMED' && offer.condition === 'UNUSED'
    ? Math.max(0, (offer.confirmed_quantity ?? 0) - offer.reserved_active_quantity - offer.transferred_out_quantity)
    : 0;

export const supplyViews = seed.supply_offers.map((offer) => ({
  ...offer,
  project_name: projectName(offer.source_project_id),
  material_name: materialName(offer.material_id),
  reservable_quantity: reservableQuantity(offer),
}));

export const demandViews = seed.demand_requests.map((demand) => ({
  ...demand,
  project_name: projectName(demand.destination_project_id),
  material_name: materialName(demand.material_id),
  remaining_unfulfilled_quantity: Math.max(0, demand.required_quantity - demand.fulfilled_quantity),
}));

export const proposalViews = seed.allocation_proposals.map((proposal) => {
  const offer = offers.get(proposal.supply_offer_id);
  const demand = demands.get(proposal.demand_request_id);
  return {
    ...proposal,
    source_project_id: offer?.source_project_id ?? null,
    destination_project_id: demand?.destination_project_id ?? null,
    material_name: offer ? materialName(offer.material_id) : 'Unknown material',
    source_project_name: offer ? projectName(offer.source_project_id) : 'Unknown source',
    destination_project_name: demand ? projectName(demand.destination_project_id) : 'Unknown destination',
    route: offer && demand ? routeFor(offer.source_project_id, demand.destination_project_id) : undefined,
  };
});

/**
 * Fixture-derived matching preview. It is intentionally read-only: one offer
 * can appear against several demands and no candidate changes stock.
 * Exact canonical material identity is the temporary specification check;
 * the API/optimiser becomes authoritative when connected.
 */
export const candidateMatches = supplyViews.flatMap((offer) =>
  demandViews
    .filter(
      (demand) =>
        demand.request_status === 'OPEN' &&
        offer.source_project_id !== demand.destination_project_id &&
        offer.material_id === demand.material_id,
    )
    .map((demand) => {
      const availableByRequiredDate = offer.available_from <= demand.required_by;
      const maximumPreviewQuantity = Math.min(
        offer.reservable_quantity,
        demand.remaining_unfulfilled_quantity,
      );
      const isEligible =
        offer.surplus_status === 'CONFIRMED' &&
        offer.condition === 'UNUSED' &&
        availableByRequiredDate &&
        maximumPreviewQuantity > 0;

      return {
        id: `${offer.id}:${demand.id}`,
        supply_offer_id: offer.id,
        demand_request_id: demand.id,
        source_project_id: offer.source_project_id,
        destination_project_id: demand.destination_project_id,
        source_project_name: offer.project_name,
        destination_project_name: demand.project_name,
        material_name: offer.material_name,
        unit: materials.get(offer.material_id)?.standard_unit ?? 'units',
        available_from: offer.available_from,
        required_by: demand.required_by,
        supply_available_quantity: offer.reservable_quantity,
        demand_open_quantity: demand.remaining_unfulfilled_quantity,
        maximum_preview_quantity: maximumPreviewQuantity,
        compatibility_result: isEligible ? 'ELIGIBLE' : 'REVIEW_REQUIRED',
      };
    }),
);

export const optimisationPlanViews = seed.optimisation_runs.map((run) => {
  const allocations = proposalViews.filter((proposal) => proposal.run_id === run.id);
  const forecastAssessments = seed.impact_assessments.filter(
    (assessment) =>
      assessment.basis === 'PROPOSAL_FORECAST' &&
      assessment.proposal_id !== null &&
      allocations.some((proposal) => proposal.id === assessment.proposal_id),
  );
  const eligibleAllocations = allocations.filter(
    (proposal) => proposal.compatibility_result === 'ELIGIBLE',
  );
  const forecastByProposal = new Map(
    forecastAssessments.map((assessment) => [assessment.proposal_id, assessment]),
  );
  const carbonKnownAllocations = eligibleAllocations.filter((proposal) =>
    forecastByProposal.get(proposal.id)?.net_avoided_kgco2e !== null &&
    forecastByProposal.has(proposal.id),
  );
  const totalRouteKm = eligibleAllocations.reduce(
    (total, proposal) => total + (proposal.route?.distance_km ?? 0),
    0,
  );
  const routesWithDistance = eligibleAllocations.filter((proposal) => proposal.route !== undefined);
  return {
    ...run,
    allocations,
    total_proposed_quantity: allocations.reduce((total, proposal) => total + proposal.proposed_quantity, 0),
    eligible_quantity: eligibleAllocations
      .reduce((total, proposal) => total + proposal.proposed_quantity, 0),
    eligible_allocation_count: eligibleAllocations.length,
    carbon_known_allocation_count: carbonKnownAllocations.length,
    carbon_evidence_status: carbonKnownAllocations.length === eligibleAllocations.length
      ? 'COMPLETE'
      : carbonKnownAllocations.length > 0
        ? 'PARTIAL'
        : 'MISSING',
    total_route_km: routesWithDistance.length === eligibleAllocations.length ? totalRouteKm : null,
    forecast_net_kgco2e: carbonKnownAllocations.length !== eligibleAllocations.length
      ? null
      : carbonKnownAllocations.reduce(
          (total, proposal) => total + (forecastByProposal.get(proposal.id)?.net_avoided_kgco2e ?? 0),
          0,
        ),
  };
});

export const transferViews = seed.transfers.map((transfer) => {
  const proposal = proposals.get(transfer.proposal_id);
  const offer = proposal ? offers.get(proposal.supply_offer_id) : undefined;
  const demand = proposal ? demands.get(proposal.demand_request_id) : undefined;
  return {
    ...transfer,
    material_name: offer ? materialName(offer.material_id) : 'Unknown material',
    source_project_name: offer ? projectName(offer.source_project_id) : 'Unknown source',
    destination_project_name: demand ? projectName(demand.destination_project_id) : 'Unknown destination',
  };
});

const actualUseTransfers = seed.transfers.filter((transfer) => transfer.actually_used_quantity > 0);
const actualReuseKg = actualUseTransfers.reduce((total, transfer) => {
  const proposal = proposals.get(transfer.proposal_id);
  const offer = proposal ? offers.get(proposal.supply_offer_id) : undefined;
  const material = offer ? materials.get(offer.material_id) : undefined;
  return total + transfer.actually_used_quantity * (material?.mass_kg_per_unit ?? 0);
}, 0);

export const dashboard = {
  confirmed_reservable: supplyViews
    .filter((offer) => offer.surplus_status === 'CONFIRMED')
    .reduce((total, offer) => total + offer.reservable_quantity, 0),
  open_demand: demandViews
    .filter((demand) => demand.request_status === 'OPEN')
    .reduce((total, demand) => total + demand.remaining_unfulfilled_quantity, 0),
  active_transfers: transferViews.filter((transfer) =>
    ['RESERVED', 'IN_TRANSIT', 'RECEIVED'].includes(transfer.status),
  ).length,
  actual_reuse_tonnes: actualReuseKg / 1000,
  actual_net_kgco2e: seed.impact_assessments
    .filter((assessment) => assessment.basis === 'ACTUAL_CONFIRMED_USE' && assessment.net_avoided_kgco2e !== null)
    .reduce((total, assessment) => total + (assessment.net_avoided_kgco2e ?? 0), 0),
  incomplete_actual_assessments: seed.impact_assessments.filter(
    (assessment) => assessment.basis === 'ACTUAL_CONFIRMED_USE' && assessment.calculation_status === 'INSUFFICIENT_DATA',
  ).length,
};

export const transferStages: TransferStatus[] = [
  'REQUESTED',
  'RESERVED',
  'IN_TRANSIT',
  'RECEIVED',
  'REUSED',
];
