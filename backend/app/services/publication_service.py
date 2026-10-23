"""Build an approved change set and commit it once, with no model calls."""
import copy
from decimal import Decimal, localcontext
from uuid import uuid5, NAMESPACE_URL
from backend.app.schemas.ingestion import IngestionBatch
from backend.app.repositories.publication_repository import PublicationRepository
from backend.app.services.review_service import ReviewService, require, audit
from backend.app.services.ingestion_service import now
from backend.app.services.ingestion_storage import digest_json
from backend.app.services.review_calculations import group_id
from terra.contract import FIELDS, camel, fields
from terra.publication_provider import EXTENSIONS
from terra.quantities import amount, ordinary, unit as normal_unit

SUPPORTED = {'PAVING_BLOCK','BRICK','TILE'}


def stable(prefix, *parts):
    return prefix+'-'+uuid5(NAMESPACE_URL, ':'.join(parts)).hex


def provider_row(entity, row):
    return {camel(key): row[key] for key, _, _ in fields(entity)}


def effective_quantity(row):
    record=row.current
    if record.quantity is None:return None,record.unit
    with localcontext() as ctx:
        ctx.prec=max(1000,len(record.quantity)+len(row.conversion.factor if row.conversion else '')+20)
        value=Decimal(record.quantity)
        if row.conversion:value*=Decimal(row.conversion.factor)
    return format(value,'f'), normal_unit(row.conversion.to_unit if row.conversion else record.unit)


class PublicationService:
    def __init__(self, intake=None, repository=None):
        self.review=ReviewService(intake);self.intake=self.review.intake
        self.repository=repository or PublicationRepository(self.intake.repository.adapter)

    def get_receipt(self,batch_id):
        record=self.repository.receipt(stable('PUB',batch_id))
        return self.view_receipt(record) if record else None

    @staticmethod
    def view_receipt(record):
        return {**record['receipt'],'handoff_status':record['handoffStatus'],
                'handoff':record['handoffPayload'],'operational_writes':True}

    def plan(self,batch_id):
        batch=self.intake.get(batch_id)
        if batch.state=='PUBLISHED':return {'published':True,'receipt':self.get_receipt(batch_id),'blockers':[]}
        return self._build(batch)[0]

    def _build(self,batch):
        view=self.review._preview(batch);review=batch.review
        state=self.repository.state()
        # Re-read review with current data; a guarded mutation later checks the
        # exact same raw operational state as well as the guard revision.
        verified=self.review._preview(batch)
        require(view['preview_digest']==verified['preview_digest'],'PUBLICATION_CONTEXT_STALE','Review context changed. Refresh before publication.')
        blockers=[message for sub in view['blockers'].values() for item in sub for message in item['messages']]
        blockers+=view['warnings']
        blockers += ['Every included file/manual submission needs a current approval.'] if not review.submissions or not all(view['approvals'].values()) else []
        data={camel(e):[] for e in ('projects','materials','documents','extracted_rows','supply_offers','demand_requests')}
        data.update({key:[] for key in EXTENSIONS});data.update(closedOfferIds=[],closedDemandIds=[],demandBalances=[],impactIntents=[],projectUpdates=[],masterAudits=[],matchingScopes=[])
        publication_id=stable('PUB',batch.id)
        existing_projects={p['id']:p for p in state['projects']}
        existing_materials={m['id']:m for m in state['materials']}
        existing_materials.update({m['id']:m['payload'] for m in state['registeredMaterials']})
        entities={e.proposal.id:e for e in review.entities}
        referenced={ref.id for sub in review.submissions for row in sub.rows if row.decision!='EXCLUDED'
                    for ref in (row.current.project_ref,row.current.material_ref) if ref and ref.kind=='PROPOSED'}
        referenced.update(p.current.project_ref.id for sub in review.submissions for p in sub.projects
                          if p.current.project_ref and p.current.project_ref.kind=='PROPOSED' and p.confirmed)
        ids={};warnings=[];created_project_codes={p['code'] for p in state['projects']}
        for local_id in sorted(referenced):
            entity=entities.get(local_id)
            if not entity or not entity.confirmed:
                blockers.append('A referenced project/material proposal is unconfirmed.');continue
            p=entity.proposal;attributes=p.attributes
            identity=stable('PRJ' if p.kind=='PROJECT' else 'MAT',publication_id,local_id);ids[local_id]=identity
            if p.kind=='PROJECT':
                if any(not attributes.get(k) for k in ('name','code','township','managing_organisation')):
                    blockers.append('New project needs name, code, township and managing organisation.');continue
                if attributes['code'] in created_project_codes:blockers.append('Project code already exists; resolve to that project rather than duplicate it.')
                created_project_codes.add(attributes['code'])
                obj={'id':identity,'code':attributes['code'],'name':attributes['name'],'township':attributes['township'],
                     'location':None,'start_date':attributes.get('start_date'),'target_end_date':attributes.get('target_end_date'),
                     'status':'ACTIVE','managing_organisation':attributes['managing_organisation']}
                info=max((fact.current for sub in review.submissions for fact in sub.projects
                           if fact.confirmed and fact.current.project_ref and fact.current.project_ref.id==local_id),
                         key=lambda fact: (bool(fact.location),bool(fact.start_date),bool(fact.end_date)), default=None)
                if info:
                    obj['location']={'address':info.location} if info.location else None
                    obj['start_date']=attributes.get('start_date') or (str(info.start_date) if info.start_date else None)
                    obj['target_end_date']=attributes.get('target_end_date') or (str(info.end_date) if info.end_date else None)
                data['projects'].append(provider_row('projects',obj));existing_projects[identity]=obj
            else:
                category=attributes.get('category_code');unit=attributes.get('standard_unit')
                obj={'id':identity,'canonical_name':attributes['canonical_name'],'category':category,
                     'specifications':attributes.get('specifications',{}),'standard_unit':unit,
                     'mass_kg_per_unit':None,'mass_source':None,'reference_code':attributes.get('reference_code'),'is_synthetic':True}
                obj['standard_unit']=normal_unit(unit)
                data['materials'].append(provider_row('materials',obj))
                existing_materials[identity]=obj
        def resolve(ref):return ids.get(ref.id,ref.id) if ref else None
        original_subs={s.id:s for s in batch.submissions}
        new_rows={};replaced=set();all_rows={r.id:r for s in review.submissions for r in s.rows}
        for sub in review.submissions:
            if sub.kind != 'FILE': continue
            source=original_subs[sub.id].source
            self.intake.store.path(source)
            for info in sub.projects:
                project=resolve(info.current.project_ref)
                if not info.confirmed or project not in existing_projects: continue
                document_id=stable('DOC',publication_id,sub.id,project)
                obj={'id':document_id,'project_id':project,'document_type':'OTHER','display_filename':source.display_filename,
                     'file_uri':'terra-source:'+source.id,'file_hash':source.sha256,'source_availability':'FILE_AVAILABLE',
                     'processing_status':'REVIEWED','recorded_at':now().isoformat(),'is_simulated':False}
                if not any(d['id']==document_id for d in data['documents']):data['documents'].append(provider_row('documents',obj))

        for sub in review.submissions:
            for row in sub.rows:
                if row.decision=='EXCLUDED':continue
                record=row.current;project=resolve(record.project_ref);material=resolve(record.material_ref)
                if project not in existing_projects or material not in existing_materials:
                    blockers.append('Record has unresolved operational project/material identity.');continue
                identity=stable('PMR',publication_id,row.id);ids[row.id]=identity
                quantity,unit=effective_quantity(row)
                source={'kind':sub.kind,'submission_id':sub.id,'label':sub.label}
                if sub.kind=='FILE':
                    submission=original_subs[sub.id];self.intake.store.path(submission.source)
                    document_id=stable('DOC',publication_id,sub.id,project)
                    source.update(document_id=document_id,source_id=submission.source.id,sha256=submission.source.sha256,
                                  source_page=record.source_page,source_locator=record.source_locator,source_item_ref=record.source_item_ref)
                    if not any(d['id']==document_id for d in data['documents']):
                        obj={'id':document_id,'project_id':project,'document_type':'OTHER','display_filename':submission.source.display_filename,
                             'file_uri':'terra-source:'+submission.source.id,'file_hash':submission.source.sha256,'source_availability':'FILE_AVAILABLE',
                             'processing_status':'REVIEWED','recorded_at':now().isoformat(),'is_simulated':False}
                        data['documents'].append(provider_row('documents',obj))
                    if record.application!='HISTORY_ONLY' and any(d.get('fileHash')==submission.source.sha256 and d['projectId']==project for d in state['documents']):
                        blockers.append('This file is already published for this project. Use reviewed history-only evidence or a distinct correction document.')
                payload={'id':identity,'project_id':project,'material_id':material,'record_kind':record.record_kind,
                         'quantity':quantity,'unit':unit,'effective_date':str(record.effective_date) if record.effective_date else None,
                         'application':record.application,'source':source,'original':row.original.model_dump(mode='json') if row.original else None,
                         'reviewed':record.model_dump(mode='json'),'conversion':row.conversion.model_dump(mode='json') if row.conversion else None,
                         'edited_by_operator':row.edited_by_operator,'publication_id':publication_id,'review_row_id':row.id,
                         'approved_at':sub.approved_at.isoformat() if sub.approved_at else None}
                new_rows[row.id]=payload
                data['projectMaterialRecords'].append({'id':identity,'projectId':project,'materialId':material,'payload':payload})
                if record.application=='REPLACE':
                    for target in record.replaces_record_ids:
                        if target in replaced:blockers.append('Two changes replace the same predecessor.')
                        replaced.add(target)
                        data['supersededRecords'].append({'id':stable('PMR',publication_id,target) if target in all_rows else target,
                                                         'projectId':project,'successorId':identity})
                if record.application=='HISTORY_ONLY':continue
        # Close only uncommitted legacy projections belonging to replaced records.
        for collection,key in [('supplyOffers','closedOfferIds'),('demandRequests','closedDemandIds')]:
            for item in state[collection]:
                targets=[item.get('originDocumentRowId')]
                targets += [row['id'] for row in state['projectMaterialRecords'] if row['payload'].get('projection_id')==item['id']]
                if not set(targets)&replaced:continue
                if collection=='supplyOffers' and (item['reservedActiveQuantity'] or item['transferredOutQuantity']):
                    blockers.append('A replaced offer has transfer history or commitments. Resolve in Transfer Management.')
                if collection=='demandRequests':
                    committed=next((c['committedQuantity'] for c in state.get('demandCommitmentBalances',[]) if c['demandRequestId']==item['id']),0)
                    # Demand balances are also present in review context and checked below.
                    if item['fulfilledQuantity'] or committed:blockers.append('A replaced demand has fulfilment/commitments. Resolve in Transfer Management.')
                data[key].append(item['id'])
        # Current context holds per-project commitments. Never close a committed demand.
        checked_projects=set()
        for sub in review.submissions:
            for row in sub.rows:
                if row.current.project_ref and row.current.project_ref.kind=='EXISTING' and row.current.project_ref.id not in checked_projects:
                    checked_projects.add(row.current.project_ref.id)
                    context=self.intake.reads.project_context(row.current.project_ref.id)['collections']
                    if any(c['demand_request_id'] in data['closedDemandIds'] and c['committed_incoming_quantity']>0 for c in context['demand_commitments']):
                        blockers.append('A replaced demand has incoming commitments. Resolve in Transfer Management.')
        effective_new={rowid:payload for rowid,payload in new_rows.items() if rowid not in replaced and payload['application']!='HISTORY_ONLY'}
        for group in view['groups']:
            project=ids.get(group['project'],group['project']);material=ids.get(group['material'],group['material']);unit=group['unit']
            legacy=material in {m['id'] for m in state['materials']}|{m['id'] for m in data['materials']}
            prior_head=next((h for h in state['projectStockHeads'] if h['projectId']==project and h['materialId']==material and normal_unit(h['payload']['unit'])==unit),None)
            if prior_head and set(prior_head['payload']['members']) & replaced and not group['stock_scope_confirmed']:
                blockers.append('Replacing published stock requires confirming every affected current stock scope, including a scope reduced to zero.')
            if group['stock_scope_confirmed'] and group['on_hand_observations'] is not None:
                members={entry['id']: next((str(raw['parsedFields'].get('quantity')) for raw in state['extractedRows'] if raw['id']==entry['id']),None)
                         for entry in group['inputs'] if entry['kind']=='ON_HAND_INVENTORY' and entry['id'] not in replaced}
                for entry in group['inputs']:
                    prior_record=next((r for r in state['projectMaterialRecords'] if r['id']==entry['id']),None)
                    if entry['kind']=='ON_HAND_INVENTORY' and prior_record and entry['id'] not in replaced:
                        members[entry['id']]=prior_record['payload']['quantity']
                    if entry['kind']=='ON_HAND_INVENTORY' and entry['id'] in new_rows and entry['id'] not in replaced:
                        members[ids[entry['id']]]=new_rows[entry['id']]['quantity'];members.pop(entry['id'],None)
                prior=next((h for h in state['projectStockHeads'] if h['projectId']==project and h['materialId']==material and normal_unit(h['payload']['unit'])==unit),None)
                if prior:
                    members.update({k:v for k,v in prior['payload']['members'].items() if k not in replaced})
                    members.pop(prior['id'],None)
                head={'id':stable('STOCK',project,material,unit),'projectId':project,'materialId':material,
                      'payload':{'id':stable('STOCK',project,material,unit),'project_id':project,'material_id':material,'unit':unit,
                                 'quantity':group['on_hand_observations'],'members':members,
                                 'outgoing_baseline':{o['id']:o['transferredOutQuantity'] for o in state['supplyOffers'] if o['sourceProjectId']==project and o['materialId']==material and normal_unit(o['unit'])==unit},
                                 'publication_id':publication_id}}
                data['projectStockHeads'].append(head)
            for rowid,payload in effective_new.items():
                if payload['project_id']!=project or payload['material_id']!=material or payload['unit']!=unit:continue
                record=all_rows[rowid].current;quantity=Decimal(payload['quantity']) if payload['quantity'] is not None else Decimal(0)
                if record.record_kind not in ('CONFIRMED_SURPLUS','OUTSTANDING_DEMAND') or quantity<=0:continue
                timing=(bool(record.available_from) if record.record_kind=='CONFIRMED_SURPLUS' else bool(record.needed_from and record.required_by))
                try: quantity=amount(quantity,unit_name=unit)
                except ValueError as exc:
                    blockers.append(str(exc));continue
                if not legacy or not timing:
                    warnings.append('A declaration is saved as evidence but has no operational projection: unresolved catalogue identity or incomplete timing.');continue
                projection=stable('SUP' if record.record_kind=='CONFIRMED_SURPLUS' else 'DEM',publication_id,rowid)
                payload['projection_id']=projection
                if record.record_kind=='CONFIRMED_SURPLUS':
                    if not group['stock_scope_confirmed'] or group['available_stock'] is None:
                        blockers.append('Confirmed offers require verified complete stock scope.');continue
                    claimed=sum(max(o['confirmedQuantity']-o['transferredOutQuantity'],0) for o in state['supplyOffers']
                        if o['sourceProjectId']==project and o['materialId']==material and normal_unit(o['unit'])==unit and o['surplusStatus']=='CONFIRMED'
                        and o['confirmedQuantity'] is not None and o['id'] not in data['closedOfferIds'])
                    if Decimal(group['declared_confirmed_surplus'])+claimed>Decimal(group['on_hand_observations'])-Decimal(group['remaining_local_requirement'] or '0'):
                        blockers.append('Existing and proposed confirmed offers would allocate the same physical stock twice.');continue
                    obj={'id':projection,'source_project_id':project,'material_id':material,'origin_document_row_id':None,
                         'declared_quantity':ordinary(quantity),'confirmed_quantity':ordinary(quantity),'reserved_active_quantity':0,'transferred_out_quantity':0,
                         'unit':unit,'surplus_status':'CONFIRMED','condition':'UNUSED' if all_rows[rowid].release_confirmed else 'UNKNOWN','available_from':str(record.available_from),
                         'available_until':str(record.available_until) if record.available_until else None,'batch_or_lot_code':None,
                         'material_owner_label':existing_projects[project].get('managing_organisation',existing_projects[project].get('managingOrganisation')),
                         'evidence_refs':[payload['id']]}
                    if not all_rows[rowid].release_confirmed:
                        warnings.append('An offer retains UNKNOWN condition and is not matcher eligible until unused/release/suitability is explicitly confirmed.')
                    # UNKNOWN condition prevents an ingestion declaration from
                    # inventing engineering/suitability confirmation.
                    data['supplyOffers'].append(provider_row('supply_offers',obj))
                else:
                    # ADD is a separate net-of-stock requirement. Existing incoming
                    # holds stay on their original demand; do not reduce required
                    # here and subtract those holds a second time on later reads.
                    allowed=quantity
                    obj={'id':projection,'destination_project_id':project,'material_id':material,'origin_document_row_id':None,
                         'required_quantity':ordinary(allowed),'fulfilled_quantity':0,'unit':unit,'needed_from':str(record.needed_from),
                         'required_by':str(record.required_by),'request_status':'OPEN','is_outstanding_need_confirmed':True}
                    data['demandRequests'].append(provider_row('demand_requests',obj));data['demandBalances'].append({'demandRequestId':projection,'committedQuantity':0})
        updates={}
        for sub in review.submissions:
            for fact in sub.projects:
                if not fact.master_updates:continue
                require(fact.confirmed and fact.current.project_ref and fact.current.project_ref.kind=='EXISTING',
                    'PROJECT_CORRECTION_UNCONFIRMED','Explicitly confirm an existing project before applying corrections.')
                pid=fact.current.project_ref.id
                prior=existing_projects[pid];changed=updates.get(pid,copy.deepcopy(prior))
                for key,value in fact.master_updates.items():
                    target='location' if key=='address' else camel(key)
                    new={**(changed.get('location') or {}),'address':value} if key=='address' else value
                    require(pid not in updates or target not in updates[pid] or updates[pid][target] in (prior.get(target),new),
                        'PROJECT_CORRECTION_CONFLICT','Conflicting project corrections need resolution.')
                    changed[target]=new
                require(not changed.get('startDate') or not changed.get('targetEndDate') or changed['startDate']<=changed['targetEndDate'],
                    'PROJECT_DATES_INVALID','Corrected project dates are reversed.')
                updates[pid]=changed
        data['projectUpdates']=list(updates.values())
        if updates:data['masterAudits']=[{'id':stable('AUD',publication_id),'kind':'PROJECT_CORRECTION','payload':{
            'publication_id':publication_id,'before':[existing_projects[k] for k in sorted(updates)],'after':list(updates.values())}}]
        affected={r['materialId'] for r in data['projectMaterialRecords'] if r['payload']['application']!='HISTORY_ONLY'}
        affected.update(r['materialId'] for r in [*state['supplyOffers'],*state['demandRequests']] if r.get('sourceProjectId',r.get('destinationProjectId')) in updates)
        if updates:
            offers_by_id={r['id']:r for r in state['supplyOffers']}
            demands_by_id={r['id']:r for r in state['demandRequests']}
            proposals_by_id={r['id']:r for r in state['allocationProposals']}
            for transfer in state['transfers']:
                if transfer['actuallyUsedQuantity']<=0:continue
                proposal=proposals_by_id[transfer['proposalId']]
                projects={offers_by_id[proposal['supplyOfferId']]['sourceProjectId'],demands_by_id[proposal['demandRequestId']]['destinationProjectId']}
                if projects & updates.keys():data['impactIntents'].append({'id':transfer['id'],'token':publication_id,'status':'PENDING',
                    'payload':{'reason':'Confirmed project correction','publication_id':publication_id}})
        data['matchingScopes']=[{'id':mid,'token':publication_id,'status':'PENDING','generationId':None,'payload':{}} for mid in sorted(affected)]
        blockers=list(dict.fromkeys(blockers));warnings=list(dict.fromkeys(warnings))
        for rows in (v for v in data.values() if isinstance(v,list)):
            if len(rows)>5000:blockers.append('The change set exceeds the connector transaction input capacity; no partial split is permitted.')
        plan={'batch_id':batch.id,'revision':batch.revision,'published':False,'publication_id':publication_id,
              'file_resolutions': [{'submission_id':s.id, 'resolution':s.resolution, 'manual_submission_id':s.manual_submission_id} for s in batch.submissions],
              'preview_digest':view['preview_digest'],'blockers':blockers,'warnings':warnings,
              'counts':{key:len(value) for key,value in data.items()},'id_mapping':ids,
              'changes':data,'matching_handoff':'DURABLE_POST_COMMIT_WORKER',
              'project_facts':[p.current.model_dump(mode='json') for s in review.submissions for p in s.projects],
              'operational_writes':False,'review_groups':view['groups'],'context_digest':view['context_digest']}
        # Avoid volatile document timestamps changing plan identity on refresh.
        digest_data=copy.deepcopy(data)
        for document in digest_data['documents']:document.pop('recordedAt',None)
        plan['plan_digest']=digest_json({'revision':batch.revision,'preview':view['preview_digest'],'state':state,
                                        'changes':digest_data,'ids':ids,'project_facts':plan['project_facts']})
        return plan,state

    def publish(self,batch_id,command):
        publication_id=stable('PUB',batch_id)
        fingerprint=digest_json({'batch_id':batch_id,'plan_digest':command.plan_digest})
        previous=self.repository.receipt(publication_id)
        if previous:
            require(previous['requestKey']==command.idempotency_key and previous['requestFingerprint']==fingerprint,
                    'PUBLICATION_KEY_REUSED','This batch already has a different publication request.')
            return {**self.view_receipt(previous),'replayed':True}
        with self.intake.store.batch_lock(batch_id):
            previous=self.repository.receipt(publication_id)
            if previous:
                require(previous['requestKey']==command.idempotency_key and previous['requestFingerprint']==fingerprint,
                        'PUBLICATION_KEY_REUSED','This batch already has a different publication request.')
                return {**self.view_receipt(previous),'replayed':True}
            batch=self.intake.get(batch_id)
            require(batch.state!='PUBLISHED','PUBLICATION_RECEIPT_MISSING','Published batch receipt is absent; do not replay into a reset database.')
            require(batch.revision==command.expected_revision,'STALE_REVISION','Batch changed. Refresh the publication plan.')
            plan,state=self._build(batch)
            require(plan['plan_digest']==command.plan_digest,'PUBLICATION_PLAN_STALE','Publication plan changed. Refresh and review the current changes.')
            require(not plan['blockers'],'PUBLICATION_BLOCKED','Resolve publication blockers before committing the batch.')
            receipt={'publication_id':publication_id,'batch_id':batch.id,'committed_at':now().isoformat(),
                     'file_resolutions':plan['file_resolutions'],
                     'counts':plan['counts'],'id_mapping':plan['id_mapping'],'project_facts':plan['project_facts'],
                     'warnings':plan['warnings'],'review_digest':plan['preview_digest'],'context_digest':plan['context_digest'],'groups':plan['review_groups'],'replayed':False}
            handoff={'event_id':publication_id,'event_type':'INGESTION_PUBLISHED','project_ids':sorted({r['projectId'] for r in plan['changes']['projectMaterialRecords']}),
                     'record_ids':[r['id'] for r in plan['changes']['projectMaterialRecords']],
                     'supply_offer_ids':[r['id'] for r in plan['changes']['supplyOffers']],
                     'demand_request_ids':[r['id'] for r in plan['changes']['demandRequests']],
                     'mode':'POST_COMMIT_WORKER','matcher_execution':'PENDING',
                     'matching_relevant':bool(plan['changes']['materials'] or plan['changes']['registeredMaterials'] or
                        plan['changes']['projectUpdates'] or any(r['payload']['application']!='HISTORY_ONLY' for r in plan['changes']['projectMaterialRecords']))}
            if not handoff['matching_relevant']:handoff['matcher_execution']='NOT_REQUIRED'
            old=batch.revision;batch.revision+=1;batch.state='PUBLISHED';batch.publication_id=publication_id;batch.updated_at=now()
            audit(batch.review,'BATCH_PUBLISHED',publication_id)
            values={**plan['changes'],'id':publication_id,'batchId':batch.id,'expectedBatchRevision':old,
                    'revision':batch.revision,'revisionId':f'{batch.id}:{batch.revision}', 'batchPayload':batch.model_dump(mode='json'),
                    'expectedOperationalRevision':state['operationalVersion']['revision'],
                    'expected':{k:v for k,v in state.items() if k!='operationalVersion'},
                    'requestKey':command.idempotency_key,'requestFingerprint':fingerprint,'receipt':receipt,'handoff':handoff,
                    'handoffStatus':'PENDING' if handoff['matching_relevant'] else 'NOT_REQUIRED'}
            stored=self.repository.publish(values)
            try:
                self.intake.store.checkpoint(batch)
            except OSError:
                # SQL Connect is already committed. The durable receipt and
                # revision remain authoritative if its local backup is unwritable.
                pass
        try:stored=self.repository.dispatch(publication_id)
        except Exception:pass  # Durable PENDING intent remains visible/retryable.
        return self.view_receipt(stored)
