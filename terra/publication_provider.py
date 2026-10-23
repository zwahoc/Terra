"""Additive operational publication schema/operations, separate from seed data."""
from terra.contract import FIELDS, TYPES, camel, fields

EXTENSIONS = {
 'registeredMaterials': ('RegisteredMaterial', 'registered_materials', 'id payload'),
 'projectMaterialRecords': ('ProjectMaterialRecord', 'project_material_records', 'id projectId materialId payload'),
 'supersededRecords': ('SupersededRecord', 'superseded_records', 'id projectId successorId'),
 'projectStockHeads': ('ProjectStockHead', 'project_stock_heads', 'id projectId materialId payload'),
}


def render_publication():
    schema = '''

type OperationalVersion @table(name: "operational_version", key: "id", singular: "operationalVersion", plural: "operationalVersions") {
  id: String!
  revision: Int! @default(value: 0)
}
type RegisteredMaterial @table(name: "registered_materials", key: "id", singular: "registeredMaterial", plural: "registeredMaterials") {
  id: String!
  payload: Any!
}
type ProjectMaterialRecord @table(name: "project_material_records", key: "id", singular: "projectMaterialRecord", plural: "projectMaterialRecords") {
  id: String!
  projectId: String!
  project: Project! @ref(fields: "projectId", references: "id")
  materialId: String!
  payload: Any!
}
type ProjectStockHead @table(name: "project_stock_heads", key: "id", singular: "projectStockHead", plural: "projectStockHeads") {
  id: String!
  projectId: String!
  materialId: String!
  payload: Any!
}
type SupersededRecord @table(name: "superseded_records", key: "id", singular: "supersededRecord", plural: "supersededRecords") {
  id: String!
  projectId: String!
  successorId: String!
}
type IngestionPublication @table(name: "ingestion_publications", key: "id", singular: "ingestionPublication", plural: "ingestionPublications") {
  id: String!
  batchId: String! @unique
  requestKey: String!
  requestFingerprint: String!
  receipt: Any!
  handoffStatus: String!
  handoffPayload: Any!
}
'''
    selections = [f'  {camel(entity)}(limit: 1000, orderBy: {{id: ASC}}) {{ '+ ' '.join(camel(n) for n,_,_ in fields(entity))+' }' for entity in FIELDS]
    selections += [f'  {name}(limit: 1000, orderBy: {{id: ASC}}) {{ {selection} }}' for name,(_,_,selection) in EXTENSIONS.items()]
    selection='\n'.join(selections)
    ops=['''query GetOperationalVersion @auth(level: NO_ACCESS) { operationalVersion(id: "GLOBAL") { revision } }''', f'''query GetPublicationState @auth(level: NO_ACCESS) {{
  operationalVersion(id: "GLOBAL") {{ revision }}
{selection}
}}''', '''query GetPublicationReceipt($id: String!) @auth(level: NO_ACCESS) {
  ingestionPublication(id: $id) { id batchId requestKey requestFingerprint receipt handoffStatus handoffPayload }
}''', '''mutation InitializeOperationalVersion @auth(level: NO_ACCESS) @transaction {
  operationalVersion_insert(data: {id: "GLOBAL" revision: 0})
}''', '''mutation RecordPublicationHandoff($id: String!) @auth(level: NO_ACCESS) @transaction {
  ingestionPublication_updateMany(where: {id: {eq: $id} handoffStatus: {eq: "PENDING"}}, data: {handoffStatus: "RECORDED_STUB"})
}''']
    variables=['$id: String!', '$batchId: String!', '$expectedBatchRevision: Int!', '$revision: Int!',
               '$revisionId: String!', '$batchPayload: Any!', '$expectedOperationalRevision: Int!',
               '$expected: Any!', '$requestKey: String!', '$requestFingerprint: String!', '$receipt: Any!', '$handoff: Any!', '$handoffStatus: String!']
    writes=[]
    for entity in ('projects','materials','documents','extracted_rows','supply_offers','demand_requests'):
        typ=TYPES[entity]; singular=typ[0].lower()+typ[1:]; name=camel(entity)
        names=' '.join(camel(n) for n,_,_ in fields(entity))
        variables.append(f'${name}: [{typ}_Data!]! @allow(fields: "{names}", maxCount: 5000)')
        writes.append(f'  {singular}_insertMany(data: ${name})')
    for name,(typ,_,names) in EXTENSIONS.items():
        variables.append(f'${name}: [{typ}_Data!]! @allow(fields: "{names}", maxCount: 5000)')
        writes.append(f'  {typ[0].lower()+typ[1:]}_{"upsertMany" if name == "projectStockHeads" else "insertMany"}(data: ${name})')
    variables += ['$impactIntents: [ImpactRefreshIntent_Data!]! = [] @allow(fields: "id token status payload",maxCount: 10000)',
                  '$projectUpdates: [Project_Data!]! @allow(fields: "id code name township location startDate targetEndDate status managingOrganisation",maxCount: 5000)',
                  '$masterAudits: [RuntimeAudit_Data!]! @allow(fields: "id kind payload",maxCount: 5000)',
                  '$matchingScopes: [MatchingScope_Data!]! @allow(fields: "id token status generationId payload",maxCount: 5000)',
                  '$closedOfferIds: [String!]!', '$closedDemandIds: [String!]!',
                  '$demandBalances: [DemandCommitmentBalance_Data!]! @allow(fields: "demandRequestId committedQuantity", maxCount: 5000)']
    check_lines=[]
    for entity in FIELDS:
        name=camel(entity)
        comparisons=[]
        for field,spec,optional in fields(entity):
            key=camel(field)
            if spec in ('date','timestamp'):
                expected_time = f"timestamp(prior.{key} + 'T00:00:00Z')" if spec == 'date' else f'timestamp(prior.{key})'
                comparisons.append(f'(row.{key} == null && prior.{key} == null || row.{key} != null && prior.{key} != null && row.{key} == {expected_time})')
            else:comparisons.append(f'row.{key} == prior.{key}')
        expression=f'size(response.query.{name}) == size(vars.expected.{name}) && response.query.{name}.all(row, vars.expected.{name}.exists(prior, prior.id == row.id && '+ ' && '.join(comparisons)+'))'
        check_lines.append(f'    @check(expr: "{expression}", message: "PUBLICATION_CONTEXT_STALE")')
    for name in EXTENSIONS:
        check_lines.append(f'    @check(expr: "response.query.{name} == vars.expected.{name}", message: "PUBLICATION_CONTEXT_STALE")')
    checks='\n'.join(check_lines)
    ops.append('mutation PublishIngestionBatch(\n  '+'\n  '.join(variables)+'''
) @auth(level: NO_ACCESS) @transaction {
  operationalVersion_updateMany(where: {id: {eq: "GLOBAL"} revision: {eq: $expectedOperationalRevision}}, data: {revision_update: {inc: 1}}) @check(expr: "this == 1", message: "PUBLICATION_CONTEXT_STALE")
  query @redact
'''+checks+' {\n'+selection+'''
  }
  ingestionBatch_updateMany(where: {id: {eq: $batchId} revision: {eq: $expectedBatchRevision}}, data: {revision: $revision payload: $batchPayload}) @check(expr: "this == 1", message: "INGESTION_STALE_REVISION")
'''+ '\n'.join(writes)+'''
  project_upsertMany(data: $projectUpdates)
  runtimeAudit_insertMany(data: $masterAudits)
  impactRefreshIntent_upsertMany(data: $impactIntents)
  matchingScope_upsertMany(data: $matchingScopes)
  supplyOffer_updateMany(where: {id: {in: $closedOfferIds}}, data: {surplusStatus: CLOSED})
  demandRequest_updateMany(where: {id: {in: $closedDemandIds}}, data: {requestStatus: CANCELLED})
  demandCommitmentBalance_insertMany(data: $demandBalances)
  ingestionPublication_insert(data: {id: $id batchId: $batchId requestKey: $requestKey requestFingerprint: $requestFingerprint receipt: $receipt handoffStatus: $handoffStatus handoffPayload: $handoff})
  ingestionRevision_insert(data: {id: $revisionId batchId: $batchId revision: $revision payload: $batchPayload})
}''')
    ops += ['''query PageRegisteredMaterials($after: String!, $limit: Int!) @auth(level: NO_ACCESS) {
  records: registeredMaterials(where: {id: {gt: $after}}, orderBy: {id: ASC}, limit: $limit) { id payload }
}''', '''query GetRegisteredMaterial($id: String!) @auth(level: NO_ACCESS) {
  registeredMaterial(id: $id) { id payload }
}''', '''query PagePublishedMaterialRecords($projectId: String!, $after: String!, $limit: Int!) @auth(level: NO_ACCESS) {
  records: projectMaterialRecords(where: {_and: [{projectId: {eq: $projectId}}, {id: {gt: $after}}]}, orderBy: {id: ASC}, limit: $limit) { id projectId materialId payload }
}''', '''query PageSupersededRecords($projectId: String!, $after: String!, $limit: Int!) @auth(level: NO_ACCESS) {
  records: supersededRecords(where: {_and: [{projectId: {eq: $projectId}}, {id: {gt: $after}}]}, orderBy: {id: ASC}, limit: $limit) { id projectId successorId }
}''']
    ops.append('''query PageProjectStockHeads($projectId: String!, $after: String!, $limit: Int!) @auth(level: NO_ACCESS) {
  records: projectStockHeads(where: {_and: [{projectId: {eq: $projectId}}, {id: {gt: $after}}]}, orderBy: {id: ASC}, limit: $limit) { id projectId materialId payload }
}''')
    return schema, '\n\n'+'\n\n'.join(ops)+'\n'


def guard_operational_operations(operations):
    """Serialize publication with existing administrative/transfer writes.

    The adapter initializes a missing guard with an insert. Guarded writes
    increment the existing row; failed transactions roll back that increment.
    """
    guarded=[]
    for operation in operations:
        if operation.startswith('mutation '):
            marker='@transaction {\n'
            if marker in operation:
                operation=operation.replace(marker,marker+'''  operationalVersion_updateMany(where: {id: {eq: "GLOBAL"}}, data: {revision_update: {inc: 1}}) @check(expr: "this == 1", message: "PUBLICATION_GUARD_MISSING")
''',1)
            if operation.startswith('mutation ClearBaseline'):
                operation=operation.replace('  impactCalculationOperation_deleteMany', '''  ingestionPublication_deleteMany(all: true)
  supersededRecord_deleteMany(all: true)
  projectStockHead_deleteMany(all: true)
  projectMaterialRecord_deleteMany(all: true)
  registeredMaterial_deleteMany(all: true)
  impactCalculationOperation_deleteMany''',1)
        guarded.append(operation)
    return guarded
