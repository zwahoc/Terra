"""Explicit seed field registry shared by validation and provider mapping.

JSON remains the canonical dataset. This registry defines types, not stock data.
Quantity fields are integer pcs; impact arithmetic uses Decimal.
"""
from pydantic import BaseModel, ConfigDict, create_model, Field
from typing import Literal

# Field spec: name: scalar, optional ?, or enum EnumName=VALUES, or FK:target?
FIELDS = {
'projects': '''id:str code:str name:str township:str location:json? start_date:date? target_end_date:date? status:ProjectStatus=ACTIVE,COMPLETED managing_organisation:str''',
'materials': '''id:str category:Category=PAVING_BLOCK,BRICK,TILE canonical_name:str specifications:json standard_unit:Unit=pcs mass_kg_per_unit:float? mass_source:str? reference_code:str? is_synthetic:bool''',
'documents': '''id:str project_id:FK=projects document_type:DocumentType=BOQ,PURCHASE_ORDER,INVENTORY,DEMAND,OTHER display_filename:str file_uri:str? file_hash:str? source_availability:SourceAvailability=METADATA_ONLY,FILE_AVAILABLE processing_status:ProcessingStatus=SIMULATED,QUEUED,PROCESSED,FAILED,REVIEWED recorded_at:timestamp is_simulated:bool''',
'extracted_rows': '''id:str document_id:FK=documents source_locator:str raw_description:str raw_quantity:str raw_unit:str parsed_fields:json suggested_material_id:FK=materials? confidence_score:float? review_status:ReviewStatus=PENDING,ACCEPTED,CORRECTED,REJECTED review_mode:ReviewMode=DEMO_PREAPPROVED,PENDING_DEMO,MANUAL_CORRECTION is_simulated:bool''',
'supply_offers': '''id:str source_project_id:FK=projects material_id:FK=materials origin_document_row_id:FK=extracted_rows? declared_quantity:int confirmed_quantity:int? reserved_active_quantity:int transferred_out_quantity:int unit:Unit=pcs surplus_status:SurplusStatus=POTENTIAL,CONFIRMED,SUSPENDED,CLOSED condition:Condition=UNUSED,RECOVERED,UNKNOWN available_from:date available_until:date? batch_or_lot_code:str? material_owner_label:str? evidence_refs:array''',
'demand_requests': '''id:str destination_project_id:FK=projects material_id:FK=materials origin_document_row_id:FK=extracted_rows? required_quantity:int fulfilled_quantity:int unit:Unit=pcs needed_from:date required_by:date request_status:RequestStatus=OPEN,FULFILLED,CANCELLED is_outstanding_need_confirmed:bool''',
'route_distances': '''id:str from_project_id:FK=projects to_project_id:FK=projects distance_km:float assumption_type:RouteAssumption=SIMULATED_ROAD_DISTANCE transport_mode:TransportMode=ROAD_FREIGHT is_synthetic:bool''',
'optimisation_runs': '''id:str created_at:timestamp objective:Objective=MAX_REUSE,MAX_NET_CO2E_AVOIDED,EARLIEST_DEADLINE inputs_snapshot_hash:str input_snapshot:json factor_dataset_version:str solver_status:SolverStatus=SUCCEEDED,INFEASIBLE,FAILED assumptions:json''',
'allocation_proposals': '''id:str run_id:FK=optimisation_runs supply_offer_id:FK=supply_offers demand_request_id:FK=demand_requests proposed_quantity:int unit:Unit=pcs compatibility_result:Compatibility=ELIGIBLE,REVIEW_REQUIRED,INELIGIBLE status:ProposalStatus=PROPOSED,SELECTED,REJECTED,EXPIRED reason_codes:array created_at:timestamp''',
 'transfers': '''id:str proposal_id:FK=allocation_proposals approved_quantity:int reserved_quantity:int dispatched_quantity:int received_quantity:int actually_used_quantity:int status:TransferStatus=REQUESTED,APPROVED,RESERVED,IN_TRANSIT,RECEIVED,REUSED,CANCELLED source_confirmation_status:Confirmation=PENDING,CONFIRMED,DECLINED destination_confirmation_status:Confirmation=PENDING,CONFIRMED,DECLINED requested_at:timestamp delivered_at:timestamp? reuse_confirmed_at:timestamp? notes:str?''',
 'transfer_events': '''id:str transfer_id:FK=transfers event_type:EventType=REQUESTED,APPROVED,RESERVED,DISPATCHED,RECEIVED,USED,CANCELLED,CORRECTION occurred_at:timestamp actor_label:str payload:json evidence_ref:str?''',
 'emission_factors': '''id:str factor_type:FactorType=NEW_MATERIAL_PRODUCTION,TRANSPORT,PROCESSING material_id:FK=materials? material_category:Category=PAVING_BLOCK,BRICK,TILE? transport_mode:TransportMode=ROAD_FREIGHT? value:float unit:str source_label:str source_url:str? geography:str lifecycle_boundary:str version:str valid_from:date is_demo_factor:bool''',
 'impact_assessments': '''id:str basis:ImpactBasis=PROPOSAL_FORECAST,ACTUAL_CONFIRMED_USE proposal_id:FK=allocation_proposals? transfer_id:FK=transfers? quantity_assessed:int unit:Unit=pcs baseline_description:str avoided_production_kgco2e:float? additional_transport_kgco2e:float? additional_processing_kgco2e:float? net_avoided_kgco2e:float? factor_ids:array assumptions:json calculation_status:CalculationStatus=DEMO,PRELIMINARY,INSUFFICIENT_DATA,REVIEWED calculated_at:timestamp'''
}
TYPES = dict(zip(FIELDS, ['Project','Material','Document','ExtractedRow','SupplyOffer','DemandRequest','RouteDistance','OptimisationRun','AllocationProposal','Transfer','TransferEvent','EmissionFactor','ImpactAssessment']))
PREFIXES = dict(zip(FIELDS, ['PRJ','MAT','DOC','ROW','SUP','DEM','RTE','RUN','ALC','TRF','EVT','EF','IMP']))
COUNTS = dict(zip(FIELDS, [(5,5),(20,20),(12,15),(40,60),(20,25),(20,25),(10,10),(3,5),(10,15),(5,8),(15,40),(6,10),(5,10)]))
ORDER = ['projects','materials','documents','extracted_rows','supply_offers','demand_requests','route_distances','emission_factors','optimisation_runs','allocation_proposals','transfers','transfer_events','impact_assessments']

def fields(entity):
    for token in FIELDS[entity].split():
        name, spec = token.split(':',1)
        optional=spec.endswith('?')
        yield name, spec.rstrip('?'), optional

def camel(name):
    words=name.split('_'); return words[0]+''.join(w.title() for w in words[1:])

class StrictRow(BaseModel):
    model_config=ConfigDict(extra='forbid', strict=True)

MODELS={}
for entity in FIELDS:
    definitions={}
    for name,spec,optional in fields(entity):
        if spec.startswith('FK='): typ=str
        elif '=' in spec: typ=Literal[tuple(spec.split('=',1)[1].split(','))]
        else: typ={'str':str,'int':int,'float':float,'bool':bool,'json':dict,'array':list[str],'date':str,'timestamp':str}[spec]
        if optional: typ=typ|None
        definitions[name]=(typ,Field(...))
    MODELS[entity]=create_model(TYPES[entity],__base__=StrictRow,**definitions)
