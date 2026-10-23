"""Durable actual-impact revisions. Never repeats a physical-use command."""
from datetime import datetime,timedelta,timezone
from backend.app.domain.carbon import CALCULATION_POLICY_VERSION, assessment_factor_units_valid
from terra.local_adapter import LocalDataConnect,AdapterError
from backend.app.repositories.impact_repository import ImpactRepository
from backend.app.services.matching_service import current_records,pages
from backend.app.services.impact_service import _context,_build_assessment,_identity,_hash

ZONE=timezone(timedelta(hours=8))

class AutomaticImpactService:
    def __init__(self,adapter=None,clock=None):
        self.adapter=adapter or LocalDataConnect()
        self.clock=clock or (lambda:datetime.now(ZONE))

    def refresh(self,*,retry_failed=False):
        a=self.adapter
        if not a.execute('GetQuantityEncoding')['quantityEncoding']:return []
        self._enqueue_policy_updates()
        outcomes=[]
        for intent in pages(a,'PageImpactIntents'):
            if intent['status']=='COMPLETED' or (intent['status']=='FAILED' and not retry_failed):continue
            try:outcomes.append(self._calculate(intent))
            except Exception as exc:
                # A newer source update wins over this worker. Stale attempts
                # stay pending; other failures remain visible for explicit retry.
                cause=exc
                stale=False
                while cause is not None:
                    stale=stale or 'STALE' in str(cause) or getattr(cause,'code','').endswith('STALE')
                    cause=cause.__cause__
                if stale:continue
                try:
                    revision=a.execute('GetOperationalVersion')['operationalVersion']['revision']
                    a.execute('FinishImpactIntent',{'id':intent['id'],'token':intent['token'],'status':'FAILED',
                        'payload':{**intent['payload'],'error':'Impact calculation needs attention. Retry after checking inputs.','error_type':type(exc).__name__},
                        'expectedOperationalRevision':revision},write=True)
                except AdapterError:pass
                outcomes.append({'transfer_id':intent['id'],'status':'FAILED'})
        return outcomes

    def _enqueue_policy_updates(self):
        """Reassess old runtime results without replaying a physical operation."""
        a=self.adapter
        intents={r['id']:r for r in pages(a,'PageImpactIntents')}
        # Fast common path: completed current-policy intents need no full read.
        if intents and all(i['payload'].get('calculation_policy_version')==CALCULATION_POLICY_VERSION for i in intents.values()):return
        records,_=current_records(a)
        assessments={r['id']:r for r in records['impact_assessments']}
        heads={r['transfer_id']:r for r in ImpactRepository(a).list_heads() if r['basis']=='ACTUAL_CONFIRMED_USE'}
        for transfer in records['transfers']:
            if transfer['actually_used_quantity']<=0:continue
            intent=intents.get(transfer['id'])
            # A pending use/correction already carries the latest source intent.
            if intent and intent['status']!='COMPLETED':continue
            head=heads.get(transfer['id']);old=assessments.get(head['current_assessment_id']) if head else None
            if old and old['assumptions'].get('calculation_policy_version')==CALCULATION_POLICY_VERSION:continue
            token='POLICY:'+CALCULATION_POLICY_VERSION+':'+transfer['id']
            # Re-read revision and head before enqueue; CAS prevents replacing
            # a newer use/correction intent between discovery and this write.
            current,version=current_records(a)
            latest_head=ImpactRepository(a).persistence_state('ACTUAL_CONFIRMED_USE:'+transfer['id'],'none').head
            latest=next((r for r in current['impact_assessments'] if r['id']==latest_head['current_assessment_id']),None)
            if latest and latest['assumptions'].get('calculation_policy_version')==CALCULATION_POLICY_VERSION:continue
            live=a.execute('GetImpactIntent',{'id':transfer['id']})['impactRefreshIntent']
            if live and live['status']!='COMPLETED':continue
            try:a.execute('EnqueueImpactPolicyRefresh',{'id':transfer['id'],'token':token,
                'payload':{'reason':'Carbon factor-unit validation correction','calculation_policy_version':CALCULATION_POLICY_VERSION},
                'expectedOperationalRevision':version},write=True)
            except AdapterError as exc:
                if 'STALE' not in str(exc):raise

    def _calculate(self,intent):
        a=self.adapter; records,version=current_records(a);tid=intent['id']
        repo=ImpactRepository(a);scope='ACTUAL_CONFIRMED_USE:'+tid
        state=repo.persistence_state(scope,'NO-OPERATION')
        context=_context(records,'ACTUAL_CONFIRMED_USE',tid)
        now=self.clock().isoformat(timespec='seconds')
        assessment,fingerprint=_build_assessment(context,records['emission_factors'],assessment_id='PENDING',
            calculated_at=now,revision=state.head['revision']+1,previous_assessment_id=state.head['current_assessment_id'],
            revision_reason=intent['payload'].get('reason','Current confirmed inputs'),actor_label='Terra automatic impact')
        payload={**intent['payload'],'calculation_policy_version':CALCULATION_POLICY_VERSION,'input_fingerprint':fingerprint,'calculation_status':assessment['calculation_status']}
        previous=next((r for r in records['impact_assessments'] if r['id']==state.head['current_assessment_id']),None)
        previous_is_current=(previous is not None
            and previous['assumptions'].get('calculation_policy_version')==CALCULATION_POLICY_VERSION
            and assessment_factor_units_valid(previous,records['emission_factors']))
        if fingerprint==state.head['input_fingerprint'] and previous_is_current:
            a.execute('FinishImpactIntent',{'id':tid,'token':intent['token'],'status':'COMPLETED',
                'payload':{**payload,'assessment_id':state.head['current_assessment_id']},'expectedOperationalRevision':version},write=True)
            return {'transfer_id':tid,'status':'UNCHANGED'}
        # Include the head revision so reverting an input can produce a new
        # immutable revision with a previously observed source fingerprint.
        operation_id,assessment_id=_identity(f'AUTO:{tid}:{state.head["revision"]}:{fingerprint}')
        assessment['id']=assessment_id
        transfer=context['transfer']
        repo.persist('ACTUAL_CONFIRMED_USE',{'scope_id':scope,'operation_id':operation_id,
            'request_fingerprint':_hash({'automatic':tid,'input_fingerprint':fingerprint,'revision':state.head['revision']}),
            'expected_revision':state.head['revision'],'new_revision':state.head['revision']+1,
            'input_fingerprint':fingerprint,'assessment':assessment,
            'source_guard':{'transfer_id':tid,'actually_used_quantity':transfer['actually_used_quantity'],
                'dispatched_quantity':transfer['dispatched_quantity'],'received_quantity':transfer['received_quantity'],
                'reuse_confirmed_at':transfer['reuse_confirmed_at']},
            'expected_operational_revision':version,'intent_token':intent['token'],
            'intent_payload':{**payload,'assessment_id':assessment_id}})
        return {'transfer_id':tid,'status':assessment['calculation_status'],'assessment_id':assessment_id}

    def view(self):
        return list(pages(self.adapter,'PageImpactIntents'))
