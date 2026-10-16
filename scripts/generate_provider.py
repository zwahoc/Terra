"""Generate checked-in schema, named local admin operations and field dictionary."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from terra.contract import FIELDS,TYPES,fields,camel
ROOT=Path(__file__).resolve().parents[1]

def render():
    enums={}; types=[]; operations=[]; selections=[]
    for entity in FIELDS:
        typ=TYPES[entity]; singular=typ[0].lower()+typ[1:]; plural=camel(entity)
        lines=[f'type {typ} @table(name: "{entity}", key: "id", singular: "{singular}", plural: "{plural}") {{']
        names=[]
        for name,spec,optional in fields(entity):
            gql=camel(name); names.append(gql)
            if spec.startswith('FK='):
                scalar='String'
            elif '=' in spec:
                scalar, values=spec.split('=',1); enums[scalar]=values.split(',')
            else: scalar={'str':'String','int':'Int','float':'Float','bool':'Boolean','json':'Any','array':'[String!]','date':'Date','timestamp':'Timestamp'}[spec]
            suffix='' if optional else '!'
            unique=' @unique' if (entity=='projects' and name=='code') or (entity=='transfers' and name=='proposal_id') else ''
            lines.append(f'  {gql}: {scalar}{suffix} @col(name: "{name}"){unique}')
            if spec.startswith('FK='):
                target=spec.split('=',1)[1]; relation=camel(name.removesuffix('_id'))
                lines.append(f'  {relation}: {TYPES[target]}{suffix} @ref(fields: "{gql}", references: "id")')
        lines.append('}')
        types.append('\n'.join(lines))
        selection=' '.join(names)
        selections.append(f'  {plural}(limit: 1000, orderBy: {{id: ASC}}) {{ {selection} }}')
        operations.append(f'query List{typ}s @auth(level: NO_ACCESS) {{\n  {plural}(limit: 1000, orderBy: {{id: ASC}}) {{ {selection} }}\n}}')
        operations.append(f'mutation Upsert{typ}s($rows: [{typ}_Data!]! @allow(fields: "{selection}", maxCount: 5000)) @auth(level: NO_ACCESS) @transaction {{\n  {singular}_upsertMany(data: $rows)\n}}')
    approval_operation='''type TransferApprovalOperation @table(name: "transfer_approval_operations", key: "id", singular: "transferApprovalOperation", plural: "transferApprovalOperations") {
  id: String! @col(name: "id")
  requestFingerprint: String! @col(name: "request_fingerprint")
  transferId: String! @col(name: "transfer_id")
  transfer: Transfer! @ref(fields: "transferId", references: "id")
  eventId: String! @col(name: "event_id") @unique
  approvedQuantity: Int! @col(name: "approved_quantity")
  sourceConfirmationStatus: Confirmation! @col(name: "source_confirmation_status")
  destinationConfirmationStatus: Confirmation! @col(name: "destination_confirmation_status")
  actorLabel: String! @col(name: "actor_label")
  evidenceRef: String @col(name: "evidence_ref")
  occurredAt: Timestamp! @col(name: "occurred_at")
}'''
    workflow_types='''type TransferWorkflowOperation @table(name: "transfer_workflow_operations", key: "id", singular: "transferWorkflowOperation", plural: "transferWorkflowOperations") {
  id: String! @col(name: "id")
  operationType: String! @col(name: "operation_type")
  requestFingerprint: String! @col(name: "request_fingerprint")
  transferId: String! @col(name: "transfer_id")
  transfer: Transfer! @ref(fields: "transferId", references: "id")
  eventId: String! @col(name: "event_id") @unique
  quantity: Int @col(name: "quantity")
  reason: String @col(name: "reason")
  actorLabel: String! @col(name: "actor_label")
  evidenceRef: String @col(name: "evidence_ref")
  occurredAt: Timestamp! @col(name: "occurred_at")
}

"""Replay guard for creation of a REQUESTED transfer from one proposal."""
type TransferRequestOperation @table(name: "transfer_request_operations", key: "id", singular: "transferRequestOperation", plural: "transferRequestOperations") {
  id: String! @col(name: "id")
  requestFingerprint: String! @col(name: "request_fingerprint")
  proposalId: String! @col(name: "proposal_id")
  proposal: AllocationProposal! @ref(fields: "proposalId", references: "id")
  transferId: String! @col(name: "transfer_id")
  transfer: Transfer! @ref(fields: "transferId", references: "id")
  eventId: String! @col(name: "event_id")
  event: TransferEvent! @ref(fields: "eventId", references: "id")
  actorLabel: String! @col(name: "actor_label")
  evidenceRef: String @col(name: "evidence_ref")
  occurredAt: Timestamp! @col(name: "occurred_at")
}

type OptimisationRunOperation @table(name: "optimisation_run_operations", key: "id", singular: "optimisationRunOperation", plural: "optimisationRunOperations") {
  id: String! @col(name: "id")
  requestFingerprint: String! @col(name: "request_fingerprint")
  runId: String! @col(name: "run_id") @unique
  run: OptimisationRun! @ref(fields: "runId", references: "id")
}

type DemandCommitmentBalance @table(name: "demand_commitment_balances", key: "demandRequestId", singular: "demandCommitmentBalance", plural: "demandCommitmentBalances") {
  demandRequestId: String! @col(name: "demand_request_id")
  demandRequest: DemandRequest! @ref(fields: "demandRequestId", references: "id")
  committedQuantity: Int! @col(name: "committed_quantity")
}

type ImpactAssessmentHead @table(name: "impact_assessment_heads", key: "id", singular: "impactAssessmentHead", plural: "impactAssessmentHeads") {
  id: String! @col(name: "id")
  basis: ImpactBasis! @col(name: "basis")
  proposalId: String @col(name: "proposal_id")
  proposal: AllocationProposal @ref(fields: "proposalId", references: "id")
  transferId: String @col(name: "transfer_id")
  transfer: Transfer @ref(fields: "transferId", references: "id")
  currentAssessmentId: String @col(name: "current_assessment_id")
  currentAssessment: ImpactAssessment @ref(fields: "currentAssessmentId", references: "id")
  revision: Int! @col(name: "revision")
  inputFingerprint: String @col(name: "input_fingerprint")
  updatedAt: Timestamp @col(name: "updated_at")
}

type ImpactCalculationOperation @table(name: "impact_calculation_operations", key: "id", singular: "impactCalculationOperation", plural: "impactCalculationOperations") {
  id: String! @col(name: "id")
  requestFingerprint: String! @col(name: "request_fingerprint")
  scopeId: String! @col(name: "scope_id")
  assessmentId: String! @col(name: "assessment_id") @unique
  assessment: ImpactAssessment! @ref(fields: "assessmentId", references: "id")
}'''
    schema='# Generated by scripts/generate_provider.py. No implicit UUIDs or application users.\n\n'
    schema+='\n\n'.join('enum '+name+' { '+ ' '.join(values)+' }' for name,values in enums.items())+'\n\n'+'\n\n'.join(types+[approval_operation,workflow_types])+'\n'
    operations.insert(0,'query SeedSnapshot @auth(level: NO_ACCESS) {\n'+'\n'.join(selections)+'\n}')
    # A snapshot replacement is one transaction, never an event replay.
    from terra.contract import ORDER
    variables=[]; writes=[]; deletes=[]
    for entity in ORDER:
        typ=TYPES[entity]; singular=typ[0].lower()+typ[1:]
        names=' '.join(camel(n) for n,_,_ in fields(entity))
        variables.append(f'${camel(entity)}: [{typ}_Data!]! @allow(fields: "{names}", maxCount: 5000)')
        writes.append(f'  {singular}_upsertMany(data: ${camel(entity)})')
    for entity in reversed(ORDER):
        typ=TYPES[entity]; deletes.append(f'  {typ[0].lower()+typ[1:]}_deleteMany(all: true)')
    approval_fields='id proposalId approvedQuantity reservedQuantity dispatchedQuantity receivedQuantity actuallyUsedQuantity status sourceConfirmationStatus destinationConfirmationStatus requestedAt deliveredAt reuseConfirmedAt notes'
    operations.append(f'''query GetTransferApprovalState($transferId: String!, $operationId: String!, $eventId: String!) @auth(level: NO_ACCESS) {{
  transfer(id: $transferId) {{ {approval_fields} proposal {{ id proposedQuantity unit compatibilityResult status supplyOfferId demandRequestId }} }}
  transferApprovalOperation(id: $operationId) {{ id requestFingerprint transferId eventId approvedQuantity sourceConfirmationStatus destinationConfirmationStatus actorLabel evidenceRef occurredAt }}
  transferEvent(id: $eventId) {{ id transferId eventType occurredAt actorLabel payload evidenceRef }}
}}''')
    operations.append(f'''query GetTransferRequestState($proposalId: String!, $operationId: String!, $transferId: String!, $eventId: String!) @auth(level: NO_ACCESS) {{
  allocationProposal(id: $proposalId) {{ id proposedQuantity unit compatibilityResult status supplyOfferId demandRequestId }}
  transfers(where: {{proposalId: {{eq: $proposalId}}}}, limit: 2) {{ {approval_fields} }}
  transferRequestOperation(id: $operationId) {{ id requestFingerprint proposalId transferId eventId actorLabel evidenceRef occurredAt }}
  transfer(id: $transferId) {{ {approval_fields} }}
  transferEvent(id: $eventId) {{ id transferId eventType occurredAt actorLabel payload evidenceRef }}
}}''')
    operations.append('''mutation CreateTransferRequest(
  $proposalId: String!
  $operationId: String!
  $requestFingerprint: String!
  $transferId: String!
  $eventId: String!
  $actorLabel: String!
  $evidenceRef: String
  $notes: String
  $approvedQuantity: Int!
  $eventPayload: Any!
  $occurredAt: Timestamp!
) @auth(level: NO_ACCESS) @transaction {
  query @redact
    @check(expr: "response.query.allocationProposal != null", message: "PROPOSAL_NOT_FOUND")
    @check(expr: "response.query.allocationProposal.status == 'SELECTED' && response.query.allocationProposal.compatibilityResult == 'ELIGIBLE'", message: "PROPOSAL_NOT_REQUESTABLE") {
    allocationProposal(id: $proposalId) { status compatibilityResult }
  }
  transfer_insert(data: {
    id: $transferId proposalId: $proposalId
    approvedQuantity: $approvedQuantity reservedQuantity: 0 dispatchedQuantity: 0 receivedQuantity: 0 actuallyUsedQuantity: 0
    status: REQUESTED sourceConfirmationStatus: CONFIRMED destinationConfirmationStatus: CONFIRMED
    requestedAt: $occurredAt deliveredAt: null reuseConfirmedAt: null notes: $notes
  })
  transferEvent_insert(data: {
    id: $eventId transferId: $transferId eventType: REQUESTED occurredAt: $occurredAt
    actorLabel: $actorLabel payload: $eventPayload evidenceRef: $evidenceRef
  })
  transferRequestOperation_insert(data: {
    id: $operationId requestFingerprint: $requestFingerprint proposalId: $proposalId
    transferId: $transferId eventId: $eventId actorLabel: $actorLabel evidenceRef: $evidenceRef occurredAt: $occurredAt
  })
}''')
    run_fields='id createdAt objective inputsSnapshotHash inputSnapshot factorDatasetVersion solverStatus assumptions'
    proposal_fields='id runId supplyOfferId demandRequestId proposedQuantity unit compatibilityResult status reasonCodes createdAt'
    operations.append(f'''query GetOptimisationRunPersistenceState($runId: String!, $operationId: String!) @auth(level: NO_ACCESS) {{
  optimisationRun(id: $runId) {{ {run_fields} }}
  optimisationRunOperation(id: $operationId) {{ id requestFingerprint runId }}
  allocationProposals(where: {{runId: {{eq: $runId}}}}, orderBy: {{id: ASC}}, limit: 1000) {{ {proposal_fields} }}
}}''')
    operations.append(f'''query GetOptimisationRun($runId: String!) @auth(level: NO_ACCESS) {{
  optimisationRun(id: $runId) {{ {run_fields} }}
  allocationProposals(where: {{runId: {{eq: $runId}}}}, orderBy: {{id: ASC}}, limit: 1000) {{ {proposal_fields} }}
}}''')
    operations.append(f'''mutation PersistOptimisationRun(
  $operationId: String!
  $runId: String!
  $requestFingerprint: String!
  $run: OptimisationRun_Data! @allow(fields: "{run_fields}")
  $proposals: [AllocationProposal_Data!]! @allow(fields: "{proposal_fields}", maxCount: 1000)
) @auth(level: NO_ACCESS) @transaction {{
  optimisationRun_insert(data: $run)
  allocationProposal_insertMany(data: $proposals)
  optimisationRunOperation_insert(data: {{id: $operationId requestFingerprint: $requestFingerprint runId: $runId}})
}}''')
    operations.append('''mutation ApproveTransfer(
  $transferId: String!
  $operationId: String!
  $requestFingerprint: String!
  $eventId: String!
  $approvedQuantity: Int!
  $sourceConfirmationStatus: Confirmation!
  $destinationConfirmationStatus: Confirmation!
  $actorLabel: String!
  $evidenceRef: String
  $eventPayload: Any!
  $occurredAt: Timestamp!
) @auth(level: NO_ACCESS) @transaction {
  query
    @redact
    @check(expr: "response.query.transfer != null", message: "TRANSFER_NOT_FOUND")
    @check(expr: "response.query.transfer.status == 'REQUESTED'", message: "TRANSFER_INVALID_STAGE")
    @check(expr: "response.query.transfer.proposal.status == 'SELECTED' && response.query.transfer.proposal.compatibilityResult == 'ELIGIBLE'", message: "PROPOSAL_NOT_APPROVABLE")
    @check(expr: "vars.approvedQuantity > 0 && vars.approvedQuantity <= response.query.transfer.proposal.proposedQuantity", message: "APPROVED_QUANTITY_INVALID")
    @check(expr: "vars.sourceConfirmationStatus == 'CONFIRMED' && vars.destinationConfirmationStatus == 'CONFIRMED'", message: "CONFIRMATIONS_REQUIRED") {
    transfer(id: $transferId) {
      status
      proposal { proposedQuantity compatibilityResult status }
    }
  }
  transferApprovalOperation_insert(data: {
    id: $operationId
    requestFingerprint: $requestFingerprint
    transferId: $transferId
    eventId: $eventId
    approvedQuantity: $approvedQuantity
    sourceConfirmationStatus: $sourceConfirmationStatus
    destinationConfirmationStatus: $destinationConfirmationStatus
    actorLabel: $actorLabel
    evidenceRef: $evidenceRef
    occurredAt: $occurredAt
  })
  transfer_update(id: $transferId, data: {
    approvedQuantity: $approvedQuantity
    status: APPROVED
    sourceConfirmationStatus: $sourceConfirmationStatus
    destinationConfirmationStatus: $destinationConfirmationStatus
  })
  transferEvent_insert(data: {
    id: $eventId
    transferId: $transferId
    eventType: APPROVED
    occurredAt: $occurredAt
    actorLabel: $actorLabel
    payload: $eventPayload
    evidenceRef: $evidenceRef
  })
}''')
    workflow_fields='id proposalId approvedQuantity reservedQuantity dispatchedQuantity receivedQuantity actuallyUsedQuantity status sourceConfirmationStatus destinationConfirmationStatus requestedAt deliveredAt reuseConfirmedAt notes'
    event_fields='id transferId eventType occurredAt actorLabel payload evidenceRef'
    supply_fields='id sourceProjectId materialId declaredQuantity confirmedQuantity reservedActiveQuantity transferredOutQuantity unit surplusStatus condition availableFrom availableUntil'
    demand_fields='id destinationProjectId materialId requiredQuantity fulfilledQuantity unit neededFrom requiredBy requestStatus isOutstandingNeedConfirmed'
    operations.append(f'''query GetTransferWorkflowState($transferId: String!, $operationId: String!, $eventId: String!) @auth(level: NO_ACCESS) {{
  transfer(id: $transferId) {{ {workflow_fields} proposal {{ id proposedQuantity unit compatibilityResult status supplyOfferId demandRequestId supplyOffer {{ {supply_fields} }} demandRequest {{ {demand_fields} }} }} }}
  transferWorkflowOperation(id: $operationId) {{ id operationType requestFingerprint transferId eventId quantity reason actorLabel evidenceRef occurredAt }}
  transferEvent(id: $eventId) {{ {event_fields} }}
}}''')
    operations.append(f'''query GetTransferEvents($transferId: String!) @auth(level: NO_ACCESS) {{
  transferEvents(where: {{transferId: {{eq: $transferId}}}}, orderBy: {{occurredAt: ASC}}, limit: 1000) {{ {event_fields} }}
}}''')
    operations.append(f'''query GetSupplyOffer($id: String!) @auth(level: NO_ACCESS) {{
  supplyOffer(id: $id) {{ {supply_fields} }}
}}''')
    operations.append(f'''query GetDemandRequest($id: String!) @auth(level: NO_ACCESS) {{
  demandRequest(id: $id) {{ {demand_fields} }}
  demandCommitmentBalance(key: {{demandRequestId: $id}}) {{ demandRequestId committedQuantity }}
}}''')
    operations.append('''query ListDemandCommitmentBalances @auth(level: NO_ACCESS) {
  demandCommitmentBalances(limit: 1000, orderBy: {demandRequestId: ASC}) { demandRequestId committedQuantity }
}''')
    assessment_fields='id basis proposalId transferId quantityAssessed unit baselineDescription avoidedProductionKgco2E additionalTransportKgco2E additionalProcessingKgco2E netAvoidedKgco2E factorIds assumptions calculationStatus calculatedAt'
    operations.append('''query ListImpactAssessmentHeads @auth(level: NO_ACCESS) {
  impactAssessmentHeads(limit: 1000, orderBy: {id: ASC}) { id basis proposalId transferId currentAssessmentId revision inputFingerprint updatedAt }
}''')
    operations.append(f'''query GetImpactPersistenceState($scopeId: String!, $operationId: String!) @auth(level: NO_ACCESS) {{
  impactAssessmentHead(id: $scopeId) {{ id basis proposalId transferId currentAssessmentId revision inputFingerprint updatedAt }}
  impactCalculationOperation(id: $operationId) {{ id requestFingerprint scopeId assessmentId assessment {{ {assessment_fields} }} }}
}}''')
    impact_common='''
  $scopeId: String!
  $operationId: String!
  $requestFingerprint: String!
  $assessmentId: String!
  $expectedRevision: Int!
  $newRevision: Int!
  $inputFingerprint: String!
  $calculatedAt: Timestamp!
  $assessment: ImpactAssessment_Data! @allow(fields: "id basis proposalId transferId quantityAssessed unit baselineDescription avoidedProductionKgco2E additionalTransportKgco2E additionalProcessingKgco2E netAvoidedKgco2E factorIds assumptions calculationStatus calculatedAt")'''
    operations.append(f'''mutation PersistForecastImpactAssessment({impact_common}
  $proposalId: String!
  $expectedQuantity: Int!
  $expectedUnit: Unit!
) @auth(level: NO_ACCESS) @transaction {{
  allocationProposal_updateMany(where: {{id: {{eq: $proposalId}} proposedQuantity: {{eq: $expectedQuantity}} unit: {{eq: $expectedUnit}}}}, data: {{proposedQuantity: $expectedQuantity}}) @check(expr: "this == 1", message: "IMPACT_SOURCE_STALE")
  impactAssessment_insert(data: $assessment)
  impactAssessmentHead_updateMany(where: {{id: {{eq: $scopeId}} revision: {{eq: $expectedRevision}}}}, data: {{currentAssessmentId: $assessmentId revision: $newRevision inputFingerprint: $inputFingerprint updatedAt: $calculatedAt}}) @check(expr: "this == 1", message: "IMPACT_REVISION_STALE")
  impactCalculationOperation_insert(data: {{id: $operationId requestFingerprint: $requestFingerprint scopeId: $scopeId assessmentId: $assessmentId}})
}}''')
    operations.append(f'''mutation PersistActualImpactAssessment({impact_common}
  $transferId: String!
  $expectedUsedQuantity: Int!
  $expectedDispatchedQuantity: Int!
  $expectedReceivedQuantity: Int!
  $expectedReuseConfirmedAt: Timestamp!
) @auth(level: NO_ACCESS) @transaction {{
  transfer_updateMany(where: {{id: {{eq: $transferId}} actuallyUsedQuantity: {{eq: $expectedUsedQuantity}} dispatchedQuantity: {{eq: $expectedDispatchedQuantity}} receivedQuantity: {{eq: $expectedReceivedQuantity}} reuseConfirmedAt: {{eq: $expectedReuseConfirmedAt}}}}, data: {{actuallyUsedQuantity: $expectedUsedQuantity}}) @check(expr: "this == 1", message: "IMPACT_SOURCE_STALE")
  impactAssessment_insert(data: $assessment)
  impactAssessmentHead_updateMany(where: {{id: {{eq: $scopeId}} revision: {{eq: $expectedRevision}}}}, data: {{currentAssessmentId: $assessmentId revision: $newRevision inputFingerprint: $inputFingerprint updatedAt: $calculatedAt}}) @check(expr: "this == 1", message: "IMPACT_REVISION_STALE")
  impactCalculationOperation_insert(data: {{id: $operationId requestFingerprint: $requestFingerprint scopeId: $scopeId assessmentId: $assessmentId}})
}}''')
    common_vars='''
  $transferId: String!
  $operationId: String!
  $requestFingerprint: String!
  $eventId: String!
  $quantity: Int!
  $actorLabel: String!
  $evidenceRef: String
  $eventPayload: Any!
  $occurredAt: Timestamp!
  $operationDate: Date!
  $supplyOfferId: String!
  $demandRequestId: String!'''
    operation_insert='''transferWorkflowOperation_insert(data: {
    id: $operationId operationType: OPERATION_TYPE requestFingerprint: $requestFingerprint
    transferId: $transferId eventId: $eventId quantity: $quantity
    actorLabel: $actorLabel evidenceRef: $evidenceRef occurredAt: $occurredAt
  })'''
    event_insert='''transferEvent_insert(data: {
    id: $eventId transferId: $transferId eventType: EVENT_TYPE occurredAt: $occurredAt
    actorLabel: $actorLabel payload: $eventPayload evidenceRef: $evidenceRef
  })'''
    reserve_insert=operation_insert.replace('OPERATION_TYPE','"RESERVE"')
    reserve_event=event_insert.replace('EVENT_TYPE','RESERVED')
    operations.append(f'''mutation ReserveTransfer({common_vars}
) @auth(level: NO_ACCESS) @transaction {{
  {reserve_insert}
  transfer_updateMany(where: {{id: {{eq: $transferId}} status: {{in: [REQUESTED, APPROVED]}}}}, data: {{reservedQuantity: $quantity status: RESERVED}}) @check(expr: "this == 1", message: "TRANSFER_INVALID_STAGE")
  supplyOffer_update(id: $supplyOfferId, data: {{reservedActiveQuantity_update: {{inc: $quantity}}}}) @check(expr: "this != null", message: "SUPPLY_NOT_FOUND")
  demandCommitmentBalance_update(key: {{demandRequestId: $demandRequestId}}, data: {{committedQuantity_update: {{inc: $quantity}}}}) @check(expr: "this != null", message: "DEMAND_BALANCE_NOT_FOUND")
  query @redact
    @check(expr: "response.query.transfer.status == 'RESERVED'", message: "TRANSFER_INVALID_STAGE")
    @check(expr: "response.query.transfer.sourceConfirmationStatus == 'CONFIRMED' && response.query.transfer.destinationConfirmationStatus == 'CONFIRMED'", message: "CONFIRMATIONS_REQUIRED")
    @check(expr: "response.query.transfer.approvedQuantity == vars.quantity && response.query.transfer.reservedQuantity == vars.quantity && response.query.transfer.dispatchedQuantity == 0", message: "RESERVATION_QUANTITY_INVALID")
    @check(expr: "response.query.transfer.proposal.status == 'SELECTED' && response.query.transfer.proposal.compatibilityResult == 'ELIGIBLE' && response.query.transfer.proposal.supplyOfferId == vars.supplyOfferId && response.query.transfer.proposal.demandRequestId == vars.demandRequestId", message: "PROPOSAL_NOT_RESERVABLE")
    @check(expr: "response.query.supplyOffer.materialId == response.query.demandRequest.materialId && response.query.supplyOffer.unit == response.query.demandRequest.unit && response.query.supplyOffer.unit == response.query.transfer.proposal.unit", message: "MATERIAL_UNIT_MISMATCH")
    @check(expr: "response.query.supplyOffer.surplusStatus == 'CONFIRMED' && response.query.supplyOffer.condition == 'UNUSED' && response.query.supplyOffer.confirmedQuantity != null && response.query.supplyOffer.reservedActiveQuantity + response.query.supplyOffer.transferredOutQuantity <= response.query.supplyOffer.confirmedQuantity", message: "SOURCE_STOCK_UNAVAILABLE")
    @check(expr: "response.query.demandRequest.requestStatus == 'OPEN' && response.query.demandRequest.isOutstandingNeedConfirmed && response.query.demandRequest.fulfilledQuantity + response.query.demandCommitmentBalance.committedQuantity <= response.query.demandRequest.requiredQuantity", message: "DEMAND_UNAVAILABLE")
    @check(expr: "response.query.supplyOffer.availableFrom <= vars.operationDate && (response.query.supplyOffer.availableUntil == null || response.query.supplyOffer.availableUntil >= vars.operationDate) && response.query.demandRequest.neededFrom <= vars.operationDate && response.query.demandRequest.requiredBy >= vars.operationDate", message: "TRANSFER_DATE_INELIGIBLE") {{
    transfer(id: $transferId) {{ status approvedQuantity reservedQuantity dispatchedQuantity sourceConfirmationStatus destinationConfirmationStatus proposal {{ unit status compatibilityResult supplyOfferId demandRequestId }} }}
    supplyOffer(id: $supplyOfferId) {{ materialId unit surplusStatus condition confirmedQuantity reservedActiveQuantity transferredOutQuantity availableFrom availableUntil }}
    demandRequest(id: $demandRequestId) {{ materialId unit requiredQuantity fulfilledQuantity neededFrom requiredBy requestStatus isOutstandingNeedConfirmed }}
    demandCommitmentBalance(key: {{demandRequestId: $demandRequestId}}) {{ committedQuantity }}
  }}
  {reserve_event}
}}''')
    dispatch_insert=operation_insert.replace('OPERATION_TYPE','"DISPATCH"')
    dispatch_event=event_insert.replace('EVENT_TYPE','DISPATCHED')
    operations.append(f'''mutation DispatchTransfer({common_vars}
) @auth(level: NO_ACCESS) @transaction {{
  {dispatch_insert}
  transfer_updateMany(where: {{id: {{eq: $transferId}} status: {{eq: RESERVED}} reservedQuantity: {{eq: $quantity}} dispatchedQuantity: {{eq: 0}} sourceConfirmationStatus: {{eq: CONFIRMED}} destinationConfirmationStatus: {{eq: CONFIRMED}}}}, data: {{reservedQuantity: 0 dispatchedQuantity: $quantity status: IN_TRANSIT}}) @check(expr: "this == 1", message: "TRANSFER_INVALID_STAGE")
  supplyOffer_update(id: $supplyOfferId, data: {{reservedActiveQuantity_update: {{dec: $quantity}} transferredOutQuantity_update: {{inc: $quantity}}}}) @check(expr: "this != null", message: "SUPPLY_NOT_FOUND")
  query @redact
    @check(expr: "response.query.transfer.status == 'IN_TRANSIT' && response.query.transfer.sourceConfirmationStatus == 'CONFIRMED' && response.query.transfer.destinationConfirmationStatus == 'CONFIRMED' && response.query.transfer.proposal.status == 'SELECTED' && response.query.transfer.proposal.compatibilityResult == 'ELIGIBLE' && response.query.transfer.proposal.supplyOfferId == vars.supplyOfferId && response.query.transfer.proposal.demandRequestId == vars.demandRequestId", message: "TRANSFER_INVALID_STAGE")
    @check(expr: "vars.quantity > 0 && response.query.transfer.approvedQuantity == vars.quantity && response.query.transfer.reservedQuantity == 0 && response.query.transfer.dispatchedQuantity == vars.quantity", message: "DISPATCH_QUANTITY_INVALID")
    @check(expr: "response.query.supplyOffer.confirmedQuantity != null && response.query.supplyOffer.reservedActiveQuantity >= 0 && response.query.supplyOffer.transferredOutQuantity >= 0 && response.query.supplyOffer.reservedActiveQuantity + response.query.supplyOffer.transferredOutQuantity <= response.query.supplyOffer.confirmedQuantity", message: "SOURCE_COUNTER_INVALID")
    @check(expr: "response.query.supplyOffer.availableFrom <= vars.operationDate && (response.query.supplyOffer.availableUntil == null || response.query.supplyOffer.availableUntil >= vars.operationDate)", message: "TRANSFER_DATE_INELIGIBLE") {{
    transfer(id: $transferId) {{ status approvedQuantity reservedQuantity dispatchedQuantity sourceConfirmationStatus destinationConfirmationStatus proposal {{ status compatibilityResult supplyOfferId demandRequestId }} }}
    supplyOffer(id: $supplyOfferId) {{ confirmedQuantity reservedActiveQuantity transferredOutQuantity availableFrom availableUntil }}
  }}
  {dispatch_event}
}}''')
    receive_insert=operation_insert.replace('OPERATION_TYPE','"RECEIVE"')
    receive_event=event_insert.replace('EVENT_TYPE','RECEIVED')
    operations.append(f'''mutation ReceiveTransfer({common_vars}
) @auth(level: NO_ACCESS) @transaction {{
  {receive_insert}
  transfer_updateMany(where: {{id: {{eq: $transferId}} status: {{eq: IN_TRANSIT}} dispatchedQuantity: {{eq: $quantity}} reservedQuantity: {{eq: 0}} receivedQuantity: {{eq: 0}} actuallyUsedQuantity: {{eq: 0}}}}, data: {{receivedQuantity: $quantity status: RECEIVED deliveredAt: $occurredAt}}) @check(expr: "this == 1", message: "TRANSFER_INVALID_STAGE")
  query @redact
    @check(expr: "response.query.transfer.status == 'RECEIVED' && response.query.transfer.proposal.supplyOfferId == vars.supplyOfferId && response.query.transfer.proposal.demandRequestId == vars.demandRequestId", message: "TRANSFER_INVALID_STAGE")
    @check(expr: "vars.quantity > 0 && response.query.transfer.reservedQuantity == 0 && response.query.transfer.receivedQuantity == vars.quantity && response.query.transfer.dispatchedQuantity == vars.quantity && response.query.transfer.actuallyUsedQuantity == 0", message: "RECEIPT_QUANTITY_INVALID")
    @check(expr: "response.query.demandRequest.neededFrom <= vars.operationDate && response.query.demandRequest.requiredBy >= vars.operationDate", message: "TRANSFER_DATE_INELIGIBLE") {{
    transfer(id: $transferId) {{ status reservedQuantity dispatchedQuantity receivedQuantity actuallyUsedQuantity proposal {{ supplyOfferId demandRequestId }} }}
    demandRequest(id: $demandRequestId) {{ neededFrom requiredBy }}
  }}
  {receive_event}
}}''')
    use_insert=operation_insert.replace('OPERATION_TYPE','"CONFIRM_USE"')
    use_event=event_insert.replace('EVENT_TYPE','USED')
    operations.append(f'''mutation ConfirmTransferUse({common_vars}
  $notes: String
  $demandStatus: RequestStatus!
  $previousUsedQuantity: Int!
  $newUsedQuantity: Int!
) @auth(level: NO_ACCESS) @transaction {{
  {use_insert}
  transfer_updateMany(where: {{id: {{eq: $transferId}} status: {{in: [RECEIVED, REUSED]}} actuallyUsedQuantity: {{eq: $previousUsedQuantity}} receivedQuantity: {{ge: $newUsedQuantity}}}}, data: {{actuallyUsedQuantity: $newUsedQuantity status: REUSED reuseConfirmedAt: $occurredAt notes: $notes}}) @check(expr: "this == 1", message: "TRANSFER_INVALID_STAGE")
  demandRequest_update(id: $demandRequestId, data: {{fulfilledQuantity_update: {{inc: $quantity}} requestStatus: $demandStatus}}) @check(expr: "this != null", message: "DEMAND_NOT_FOUND")
  demandCommitmentBalance_update(key: {{demandRequestId: $demandRequestId}}, data: {{committedQuantity_update: {{dec: $quantity}}}}) @check(expr: "this != null", message: "DEMAND_BALANCE_NOT_FOUND")
  query @redact
    @check(expr: "response.query.transfer.status == 'REUSED' && response.query.transfer.proposal.supplyOfferId == vars.supplyOfferId && response.query.transfer.proposal.demandRequestId == vars.demandRequestId", message: "TRANSFER_INVALID_STAGE")
    @check(expr: "vars.quantity > 0 && vars.newUsedQuantity == vars.previousUsedQuantity + vars.quantity && response.query.transfer.actuallyUsedQuantity == vars.newUsedQuantity && vars.newUsedQuantity <= response.query.transfer.receivedQuantity", message: "USE_QUANTITY_INVALID")
    @check(expr: "response.query.demandRequest.fulfilledQuantity <= response.query.demandRequest.requiredQuantity && response.query.demandCommitmentBalance.committedQuantity >= 0 && ((response.query.demandRequest.fulfilledQuantity == response.query.demandRequest.requiredQuantity && vars.demandStatus == 'FULFILLED') || (response.query.demandRequest.fulfilledQuantity < response.query.demandRequest.requiredQuantity && vars.demandStatus == 'OPEN'))", message: "DEMAND_COUNTER_INVALID") {{
    transfer(id: $transferId) {{ status receivedQuantity actuallyUsedQuantity proposal {{ supplyOfferId demandRequestId }} }}
    demandRequest(id: $demandRequestId) {{ requiredQuantity fulfilledQuantity requestStatus }}
    demandCommitmentBalance(key: {{demandRequestId: $demandRequestId}}) {{ committedQuantity }}
  }}
  {use_event}
}}''')
    cancel_insert=operation_insert.replace('OPERATION_TYPE','"CANCEL"').replace('quantity: $quantity','quantity: $quantity reason: $reason')
    cancel_event=event_insert.replace('EVENT_TYPE','CANCELLED')
    operations.append(f'''mutation CancelTransfer({common_vars}
  $reason: String!
  $notes: String
) @auth(level: NO_ACCESS) @transaction {{
  {cancel_insert}
  transfer_updateMany(where: {{id: {{eq: $transferId}} status: {{in: [REQUESTED, APPROVED, RESERVED]}} dispatchedQuantity: {{eq: 0}} reservedQuantity: {{eq: $quantity}}}}, data: {{reservedQuantity: 0 status: CANCELLED notes: $notes}}) @check(expr: "this == 1", message: "TRANSFER_INVALID_STAGE")
  supplyOffer_update(id: $supplyOfferId, data: {{reservedActiveQuantity_update: {{dec: $quantity}}}}) @check(expr: "this != null", message: "SUPPLY_NOT_FOUND")
  demandCommitmentBalance_update(key: {{demandRequestId: $demandRequestId}}, data: {{committedQuantity_update: {{dec: $quantity}}}}) @check(expr: "this != null", message: "DEMAND_BALANCE_NOT_FOUND")
  query @redact
    @check(expr: "response.query.transfer.status == 'CANCELLED' && response.query.transfer.dispatchedQuantity == 0 && response.query.transfer.proposal.supplyOfferId == vars.supplyOfferId && response.query.transfer.proposal.demandRequestId == vars.demandRequestId", message: "TRANSFER_INVALID_STAGE")
    @check(expr: "response.query.transfer.reservedQuantity == 0", message: "CANCELLATION_RELEASE_INVALID")
    @check(expr: "response.query.supplyOffer.reservedActiveQuantity >= 0 && response.query.demandCommitmentBalance.committedQuantity >= 0", message: "COMMITMENT_COUNTER_INVALID") {{
    transfer(id: $transferId) {{ status reservedQuantity dispatchedQuantity proposal {{ supplyOfferId demandRequestId }} }}
    supplyOffer(id: $supplyOfferId) {{ reservedActiveQuantity }}
    demandCommitmentBalance(key: {{demandRequestId: $demandRequestId}}) {{ committedQuantity }}
  }}
  {cancel_event}
}}''')
    balance_rows='''$demandCommitmentBalances: [DemandCommitmentBalance_Data!]! @allow(fields: "demandRequestId committedQuantity", maxCount: 5000)'''
    variables.append(balance_rows)
    writes.append('  demandCommitmentBalance_upsertMany(data: $demandCommitmentBalances)')
    head_rows='''$impactAssessmentHeads: [ImpactAssessmentHead_Data!]! @allow(fields: "id basis proposalId transferId currentAssessmentId revision inputFingerprint updatedAt", maxCount: 5000)'''
    variables.append(head_rows)
    writes.append('  impactAssessmentHead_upsertMany(data: $impactAssessmentHeads)')
    operations.append('mutation ImportBaseline(\n  '+'\n  '.join(variables)+'\n) @auth(level: NO_ACCESS) @transaction {\n'+'\n'.join(writes)+'\n}')
    deletes.insert(0, '  demandCommitmentBalance_deleteMany(all: true)')
    deletes.insert(0, '  transferWorkflowOperation_deleteMany(all: true)')
    deletes.insert(0, '  transferRequestOperation_deleteMany(all: true)')
    deletes.insert(0, '  optimisationRunOperation_deleteMany(all: true)')
    deletes.insert(0, '  transferApprovalOperation_deleteMany(all: true)')
    deletes.insert(0, '  impactAssessmentHead_deleteMany(all: true)')
    deletes.insert(0, '  impactCalculationOperation_deleteMany(all: true)')
    operations.append('mutation ClearBaseline @auth(level: NO_ACCESS) @transaction {\n'+'\n'.join(deletes)+'\n}')
    return schema,'# Administrative connector operations. Not public application APIs.\n\n'+'\n\n'.join(operations)+'\n'

if __name__=='__main__':
    a,b=render()
    if '--check' in sys.argv:
        assert (ROOT/'dataconnect/schema/schema.gql').read_text(encoding='utf-8')==a
        assert (ROOT/'dataconnect/terra/operations.gql').read_text(encoding='utf-8')==b
        print('Provider definitions match the field registry')
    else:
        (ROOT/'dataconnect/schema/schema.gql').write_text(a, encoding="utf-8", newline="\n")
        (ROOT/'dataconnect/terra/operations.gql').write_text(b, encoding="utf-8", newline="\n")
