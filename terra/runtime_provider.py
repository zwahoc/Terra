"""Generated runtime extensions. All commands remain local/admin only."""
import re
from terra.quantities import AMOUNT_KEYS
from terra.contract import FIELDS,TYPES,fields,camel

def exact_scalars(source):
    source=source.replace('mutation ClearBaseline @auth(level: NO_ACCESS) @transaction {',
        'mutation ClearBaseline @auth(level: NO_ACCESS) @transaction {\n  matchingScope_deleteMany(all: true)\n  matchingGeneration_deleteMany(all: true)\n  runtimeAudit_deleteMany(all: true)')
    source=source.replace('$expectedUnit: Unit!', '$expectedUnit: String!')
    source=source.replace('id proposedQuantity unit compatibilityResult status supplyOfferId demandRequestId', 'id runId proposedQuantity unit compatibilityResult status supplyOfferId demandRequestId')
    for key in AMOUNT_KEYS:
        source = re.sub(r'\b'+key+r': Int\b', key+': Int64', source)
    # Any-typed expected snapshots carry Int64 wire strings; CEL sees an int
    # for a typed Int64 result and must explicitly convert the expected value.
    for key in AMOUNT_KEYS:
        replacement=(f'(row.{key} == null && prior.{key} == null || row.{key} != null && prior.{key} != null && row.{key} == int(prior.{key}))'
                     if key=='confirmedQuantity' else f'row.{key} == int(prior.{key})')
        source=source.replace(f'row.{key} == prior.{key}',replacement)
    return source

def render_runtime():
    schema='''
type QuantityEncoding @table(name: "quantity_encoding", key: "id", singular: "quantityEncoding", plural: "quantityEncodings") {
  id: String!
  version: String!
}
type MatchingScope @table(name: "matching_scopes", key: "id", singular: "matchingScope", plural: "matchingScopes") {
  id: String!
  token: String!
  status: String!
  generationId: String
  payload: Any!
}
type MatchingGeneration @table(name: "matching_generations", key: "id", singular: "matchingGeneration", plural: "matchingGenerations") {
  id: String!
  materialId: String!
  fingerprint: String!
  payload: Any!
}
type RuntimeAudit @table(name: "runtime_audit", key: "id", singular: "runtimeAudit", plural: "runtimeAudits") {
  id: String!
  kind: String!
  payload: Any!
}
'''
    ops='''
query GetQuantityEncoding @auth(level: NO_ACCESS) { quantityEncoding(id: "GLOBAL") { version } }
mutation InitializeExactQuantities @auth(level: NO_ACCESS) @transaction {
  query @redact @check(expr: "size(response.query.supplyOffers) == 0 && size(response.query.demandRequests) == 0 && size(response.query.transfers) == 0", message: "EXACT_ENCODING_REQUIRES_EMPTY_DATABASE") {
    supplyOffers(limit: 1) { id }
    demandRequests(limit: 1) { id }
    transfers(limit: 1) { id }
  }
  quantityEncoding_insert(data: {id: "GLOBAL" version: "millionths-v1"})
}
query GetMatchingScope($id: String!) @auth(level: NO_ACCESS) { matchingScope(id: $id) { id token status generationId payload } }
query GetMatchingGeneration($id: String!) @auth(level: NO_ACCESS) { matchingGeneration(id: $id) { id materialId fingerprint payload } }
query GetRuntimeAudit($id: String!) @auth(level: NO_ACCESS) { runtimeAudit(id: $id) { id kind payload } }
query PageMatchingScopes($after: String!, $limit: Int!) @auth(level: NO_ACCESS) {
  records: matchingScopes(where: {id: {gt: $after}}, orderBy: {id: ASC}, limit: $limit) { id token status generationId payload }
}
query PageMatchingPublications($after: String!, $limit: Int!) @auth(level: NO_ACCESS) {
  records: ingestionPublications(where: {id: {gt: $after}}, orderBy: {id: ASC}, limit: $limit) { id handoffStatus handoffPayload }
}
mutation DirtyMatchingScope($id: String!, $token: String!, $expectedRevision: Int!) @auth(level: NO_ACCESS) @transaction {
  operationalVersion_updateMany(where: {id: {eq: "GLOBAL"} revision: {eq: $expectedRevision}},data: {revision_update: {inc: 1}}) @check(expr: "this == 1",message: "MATCHING_INPUT_STALE")
  matchingScope_upsert(data: {id: $id token: $token status: "PENDING" generationId: null payload: {}})
}
mutation FailMatchingScope($id: String!, $token: String!, $payload: Any!) @auth(level: NO_ACCESS) @transaction {
  matchingScope_updateMany(where: {id: {eq: $id} token: {eq: $token}},data: {status: "FAILED" payload: $payload})
}
mutation FinishMatchingPublication($id: String!, $payload: Any!) @auth(level: NO_ACCESS) @transaction {
  ingestionPublication_update(id: $id,data: {handoffStatus: "COMPLETED" handoffPayload: $payload})
}
'''
    for entity in FIELDS:
        selection=' '.join(camel(n) for n,_,_ in fields(entity))
        ops+=f'''query PageRuntime{TYPES[entity]}s($after: String!, $limit: Int!) @auth(level: NO_ACCESS) {{
  records: {camel(entity)}(where: {{id: {{gt: $after}}}},orderBy: {{id: ASC}},limit: $limit) {{ {selection} }}
}}\n'''
    names={e:' '.join(camel(n) for n,_,_ in fields(e)) for e in ('optimisation_runs','allocation_proposals','impact_assessments')}
    ops+='''mutation CommitMatchingGeneration(
  $id: String!, $materialId: String!, $token: String!, $fingerprint: String!, $payload: Any!, $expectedRevision: Int!
  $runs: [OptimisationRun_Data!]! @allow(fields: "'''+names['optimisation_runs']+'''",maxCount: 10000)
  $proposals: [AllocationProposal_Data!]! @allow(fields: "'''+names['allocation_proposals']+'''",maxCount: 5000)
  $assessments: [ImpactAssessment_Data!]! @allow(fields: "'''+names['impact_assessments']+'''",maxCount: 5000)
  $heads: [ImpactAssessmentHead_Data!]! @allow(fields: "id basis proposalId transferId currentAssessmentId revision inputFingerprint updatedAt",maxCount: 5000)
  $operations: [OptimisationRunOperation_Data!]! @allow(fields: "id requestFingerprint runId",maxCount: 3)
) @auth(level: NO_ACCESS) @transaction {
  operationalVersion_updateMany(where: {id: {eq: "GLOBAL"} revision: {eq: $expectedRevision}},data: {revision_update: {inc: 1}}) @check(expr: "this == 1",message: "MATCHING_INPUT_STALE")
  matchingScope_updateMany(where: {id: {eq: $materialId} token: {eq: $token} status: {in: ["PENDING","FAILED"]}},data: {status: "CURRENT" generationId: $id payload: {}}) @check(expr: "this == 1 && size(vars.runs) == 3",message: "MATCHING_SCOPE_STALE")
  optimisationRun_insertMany(data: $runs)
  allocationProposal_insertMany(data: $proposals)
  impactAssessment_insertMany(data: $assessments)
  impactAssessmentHead_insertMany(data: $heads)
  optimisationRunOperation_insertMany(data: $operations)
  matchingGeneration_insert(data: {id: $id materialId: $materialId fingerprint: $fingerprint payload: $payload})
}
'''
    ops+='''mutation ConfirmRuntimeInputs(
 $expectedRevision: Int!, $auditId: String!, $kind: String!, $payload: Any!
 $projects: [Project_Data!]! @allow(fields: "'''+ ' '.join(camel(n) for n,_,_ in fields('projects'))+'''",maxCount: 100)
 $materials: [Material_Data!]! @allow(fields: "'''+ ' '.join(camel(n) for n,_,_ in fields('materials'))+'''",maxCount: 100)
 $routes: [RouteDistance_Data!]! @allow(fields: "'''+ ' '.join(camel(n) for n,_,_ in fields('route_distances'))+'''",maxCount: 100)
 $scopes: [MatchingScope_Data!]! @allow(fields: "id token status generationId payload",maxCount: 5000)
) @auth(level: NO_ACCESS) @transaction {
 operationalVersion_updateMany(where: {id: {eq: "GLOBAL"} revision: {eq: $expectedRevision}},data: {revision_update: {inc: 1}}) @check(expr: "this == 1",message: "RUNTIME_INPUT_STALE")
 project_upsertMany(data: $projects)
 material_upsertMany(data: $materials)
 routeDistance_upsertMany(data: $routes)
 matchingScope_upsertMany(data: $scopes)
 runtimeAudit_insert(data: {id: $auditId kind: $kind payload: $payload})
}
'''
    ops+='''mutation ProveCombinedTransferReservation(
 $expectedRevision: Int!, $generationId: String!, $materialId: String!, $proposalId: String!, $transferId: String!,
 $operationId: String!, $requestFingerprint: String!, $approvalEventId: String!, $eventId: String!,
 $quantity: Int64!, $actorLabel: String!, $evidenceRef: String, $occurredAt: Timestamp!, $operationDate: Date!, $arrivalDate: Date!,
 $supplyOfferId: String!, $demandRequestId: String!, $eventPayload: Any!
) @auth(level: NO_ACCESS) @transaction {
 operationalVersion_updateMany(where: {id: {eq: "GLOBAL"} revision: {eq: $expectedRevision}},data: {revision_update: {inc: 1}}) @check(expr: "this == 1",message: "CONFIRMATION_CONTEXT_STALE")
 initialScope: query @redact
  @check(expr: "response.initialScope.matchingScope != null && response.initialScope.matchingScope.status == 'CURRENT' && response.initialScope.matchingScope.generationId == vars.generationId",message: "RECOMMENDATION_SUPERSEDED") {
  matchingScope(id: $materialId) { status generationId }
 }
 allocationProposal_updateMany(where: {id: {eq: $proposalId} status: {in: [PROPOSED,SELECTED]} compatibilityResult: {eq: ELIGIBLE} proposedQuantity: {ge: $quantity}},data: {status: SELECTED}) @check(expr: "this == 1 && vars.quantity > 0",message: "PROPOSAL_NOT_CONFIRMABLE")
 transfer_insert(data: {id: $transferId proposalId: $proposalId approvedQuantity: $quantity reservedQuantity: $quantity dispatchedQuantity: 0 receivedQuantity: 0 actuallyUsedQuantity: 0 status: RESERVED sourceConfirmationStatus: CONFIRMED destinationConfirmationStatus: CONFIRMED requestedAt: $occurredAt})
 supplyOffer_update(id: $supplyOfferId,data: {reservedActiveQuantity_update: {inc: $quantity}})
 demandCommitmentBalance_update(key: {demandRequestId: $demandRequestId},data: {committedQuantity_update: {inc: $quantity}})
 query @redact
  @check(expr: "response.query.transfer.proposal.supplyOfferId == vars.supplyOfferId && response.query.transfer.proposal.demandRequestId == vars.demandRequestId && response.query.transfer.proposal.run.assumptions.matching_generation == vars.generationId",message: "PROPOSAL_NOT_CONFIRMABLE")
  @check(expr: "response.query.supplyOffer.materialId == vars.materialId && response.query.demandRequest.materialId == vars.materialId && response.query.supplyOffer.unit == response.query.demandRequest.unit && response.query.supplyOffer.unit == response.query.transfer.proposal.unit",message: "MATERIAL_UNIT_MISMATCH")
  @check(expr: "response.query.supplyOffer.surplusStatus == 'CONFIRMED' && response.query.supplyOffer.condition == 'UNUSED' && response.query.supplyOffer.confirmedQuantity != null && response.query.supplyOffer.reservedActiveQuantity + response.query.supplyOffer.transferredOutQuantity <= response.query.supplyOffer.confirmedQuantity",message: "SOURCE_STOCK_UNAVAILABLE")
  @check(expr: "response.query.demandRequest.requestStatus == 'OPEN' && response.query.demandRequest.isOutstandingNeedConfirmed && response.query.demandRequest.fulfilledQuantity + response.query.demandCommitmentBalance.committedQuantity <= response.query.demandRequest.requiredQuantity",message: "DEMAND_UNAVAILABLE")
  @check(expr: "response.query.supplyOffer.availableFrom <= vars.operationDate && (response.query.supplyOffer.availableUntil == null || response.query.supplyOffer.availableUntil >= vars.operationDate) && response.query.demandRequest.neededFrom <= vars.operationDate && vars.arrivalDate >= vars.operationDate && vars.arrivalDate <= response.query.demandRequest.requiredBy",message: "TRANSFER_DATE_INELIGIBLE") {
  transfer(id: $transferId) { proposal { unit supplyOfferId demandRequestId run { assumptions } } }
  supplyOffer(id: $supplyOfferId) { materialId unit surplusStatus condition confirmedQuantity reservedActiveQuantity transferredOutQuantity availableFrom availableUntil }
  demandRequest(id: $demandRequestId) { materialId unit requiredQuantity fulfilledQuantity neededFrom requiredBy requestStatus isOutstandingNeedConfirmed }
  demandCommitmentBalance(key: {demandRequestId: $demandRequestId}) { committedQuantity }
 }
 approvalEvent: transferEvent_insert(data: {id: $approvalEventId transferId: $transferId eventType: APPROVED occurredAt: $occurredAt actorLabel: $actorLabel payload: $eventPayload evidenceRef: $evidenceRef})
 transferEvent_insert(data: {id: $eventId transferId: $transferId eventType: RESERVED occurredAt: $occurredAt actorLabel: $actorLabel payload: $eventPayload evidenceRef: $evidenceRef})
 transferWorkflowOperation_insert(data: {id: $operationId operationType: "APPROVE_RESERVE" requestFingerprint: $requestFingerprint transferId: $transferId eventId: $eventId quantity: $quantity actorLabel: $actorLabel evidenceRef: $evidenceRef occurredAt: $occurredAt})
 impactAssessmentHead_insert(data: {id_expr: "'ACTUAL_CONFIRMED_USE:' + vars.transferId" basis: ACTUAL_CONFIRMED_USE transferId: $transferId revision: 0})
 matchingScope_update(id: $materialId,data: {token: $operationId status: "PENDING" generationId: null payload: {}})
}
'''
    return schema,ops
