"""One deliberate command approves and reserves an individual current proposal."""
import hashlib
from datetime import datetime, timedelta, timezone
from terra.local_adapter import LocalDataConnect, AdapterError, AdapterUnavailableError
from terra.quantities import amount, ordinary, text
from backend.app.repositories.transfer_repository import TransferRepository, TransferRepositoryError
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.ingestion_storage import digest_json
from backend.app.services.matching_service import current_records, dependency, material_records
from backend.app.services.forecast_preview_service import ForecastPreviewCalculator
from backend.app.services.optimisation_preview_service import preview_json
from backend.app.services.transfer_workflow_service import _response, TransferWorkflowError

ZONE=timezone(timedelta(hours=8))


def _ids(key):
    digest=hashlib.sha256(key.encode()).hexdigest()
    return 'TRF-C-'+digest[:32], 'WFO-'+digest, 'EVT-WFO-'+digest[:32]


def prepare_confirmation(adapter, proposal_id, quantity, generation_id, clock=None):
    if not adapter.execute('GetQuantityEncoding')['quantityEncoding']:
        raise IngestionError('LOCAL_CUTOVER_REQUIRED','Transfer confirmation requires the new local runtime setup.',409)
    records,revision=current_records(adapter)
    proposal=next((p for p in records['allocation_proposals'] if p['id']==proposal_id),None)
    if proposal is None:raise IngestionError('PROPOSAL_NOT_FOUND','This proposal was not found.',404)
    run=next(r for r in records['optimisation_runs'] if r['id']==proposal['run_id'])
    supply=next(r for r in records['supply_offers'] if r['id']==proposal['supply_offer_id'])
    demand=next(r for r in records['demand_requests'] if r['id']==proposal['demand_request_id'])
    mid=supply['material_id']; today=(clock or (lambda:datetime.now(ZONE)))().date()
    scope=adapter.execute('GetMatchingScope',{'id':mid})['matchingScope']
    generation=adapter.execute('GetMatchingGeneration',{'id':generation_id})['matchingGeneration']
    if (not generation or not scope or scope['status']!='CURRENT' or scope['generationId']!=generation_id
        or run['assumptions'].get('matching_generation')!=generation_id
        or generation['fingerprint']!=dependency(records,mid,today)):
        raise IngestionError('RECOMMENDATION_SUPERSEDED','This recommendation changed. Review the current matching plan.',409)
    if proposal['status'] not in ('PROPOSED','SELECTED') or proposal['compatibility_result']!='ELIGIBLE':
        raise IngestionError('PROPOSAL_NOT_CONFIRMABLE','This proposal cannot be confirmed.',409)
    try:q=amount(quantity,unit_name=proposal['unit'])
    except ValueError as exc:raise IngestionError('TRANSFER_QUANTITY_INVALID',str(exc),422) from exc
    if q<=0 or q>proposal['proposed_quantity']:
        raise IngestionError('TRANSFER_QUANTITY_INVALID','Choose a positive quantity up to the proposal quantity. Increases need a new plan.',422)
    calculator=ForecastPreviewCalculator(material_records(records,mid),planning_date=today,factor_dataset_version=run['factor_dataset_version'])
    pair=calculator._pairs.get((supply['id'],demand['id']))
    if pair is None or pair.compatibility_result!='ELIGIBLE' or q>pair.max_allocatable_quantity:
        raise IngestionError('TRANSFER_CONTEXT_CHANGED','Stock, demand or compatibility no longer supports this transfer. Refresh matching.',409)
    forecast=calculator.assess_forecast_preview(supply['id'],demand['id'],ordinary(q))
    return {'proposal_id':proposal_id,'generation_id':generation_id,'expected_revision':revision,
        'material_id':mid,'supply_offer_id':supply['id'],'demand_request_id':demand['id'],
        'original_quantity':proposal['proposed_quantity'],'chosen_quantity':ordinary(q),'unit':proposal['unit'],
        'confirmable':pair.earliest_dispatch_date<=today,'earliest_start':str(pair.earliest_dispatch_date),
        'arrival_date':str(pair.earliest_delivery_date),'operation_date':str(today),'forecast':preview_json(forecast)}


def confirm_transfer(proposal_id, command, adapter=None, clock=None):
    adapter=adapter or LocalDataConnect(); repository=TransferRepository(adapter)
    transfer_id,operation_id,event_id=_ids(command.idempotency_key)
    fingerprint=digest_json({'proposal_id':proposal_id,'quantity':text(amount(command.quantity)),'generation_id':command.generation_id,
        'actor_label':command.actor_label,'evidence_ref':command.evidence_ref})
    def read_back(replayed):
        try:state=repository.get_workflow_state(transfer_id,operation_id,event_id)
        except (TransferRepositoryError, TransferWorkflowError) as exc:
            raise IngestionError('CONFIRMATION_UNCERTAIN','The confirmation receipt could not be read. Retry this same command.',503) from exc
        if state.operation is None:return None
        if state.operation['request_fingerprint']!=fingerprint:
            raise IngestionError('IDEMPOTENCY_KEY_REUSED','This command key was already used with different transfer details.',409)
        try:return _response(repository,state,command.idempotency_key,replayed)
        except (TransferRepositoryError, TransferWorkflowError) as exc:
            raise IngestionError('CONFIRMATION_UNCERTAIN','Transfer counters could not be read back. Retry this same command.',503) from exc
    prior=read_back(True)
    if prior:return prior
    now=(clock or (lambda:datetime.now(ZONE)))()
    prepared=prepare_confirmation(adapter,proposal_id,command.quantity,command.generation_id,lambda:now)
    if prepared['expected_revision']!=command.expected_revision:
        raise IngestionError('CONFIRMATION_CONTEXT_STALE','Inputs changed. Check the latest quantity forecast before confirming.',409)
    if not prepared['confirmable']:
        raise IngestionError('TRANSFER_NOT_YET_AVAILABLE','This future opportunity cannot be reserved before its earliest start.',409)
    payload=preview_json({**prepared,'operator_confirmed':True,'forecast_basis':'CHOSEN_QUANTITY_AT_CONFIRMATION'})
    variables={'expectedRevision':prepared['expected_revision'],'generationId':command.generation_id,'materialId':prepared['material_id'],
        'proposalId':proposal_id,'transferId':transfer_id,'operationId':operation_id,'requestFingerprint':fingerprint,
        'approvalEventId':event_id+'-APPROVED','eventId':event_id,'quantity':prepared['chosen_quantity'],
        'actorLabel':command.actor_label,'evidenceRef':command.evidence_ref,'occurredAt':now.isoformat(),
        'operationDate':prepared['operation_date'],'arrivalDate':prepared['arrival_date'],'supplyOfferId':prepared['supply_offer_id'],
        'demandRequestId':prepared['demand_request_id'],'eventPayload':payload}
    try:adapter.execute('ConfirmTransferReservation',variables,write=True)
    except AdapterError as exc:
        replay=read_back(True)
        if replay:return replay
        if isinstance(exc,AdapterUnavailableError):
            raise IngestionError('CONFIRMATION_UNCERTAIN','Confirmation could not be verified. Retry this same command to check its result.',503) from exc
        raise IngestionError('CONFIRMATION_CONTEXT_STALE','The transfer could not be reserved atomically. Refresh and review current matching.',409) from exc
    result=read_back(False)
    if result is None:raise IngestionError('CONFIRMATION_UNCERTAIN','Confirmation has no verified receipt. Retry this same command.',503)
    return result
