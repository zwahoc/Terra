"""Generated-provider additions for draft-only intake, separate from seed entities."""

from terra.contract import TYPES, camel, fields


def render_intake():
    schema = '''

# Intake payloads are provisional. No seed/offer/demand/transfer foreign keys.
type IngestionBatch @table(name: "ingestion_batches", key: "id", singular: "ingestionBatch", plural: "ingestionBatches") {
  id: String! @col(name: "id")
  revision: Int! @col(name: "revision")
  payload: Any! @col(name: "payload")
}

type IngestionRevision @table(name: "ingestion_revisions", key: "id", singular: "ingestionRevision", plural: "ingestionRevisions") {
  id: String! @col(name: "id")
  batchId: String! @col(name: "batch_id")
  batch: IngestionBatch! @ref(fields: "batchId", references: "id")
  revision: Int! @col(name: "revision")
  payload: Any! @col(name: "payload")
}
'''
    operations = ['''query GetIngestionBatch($id: String!) @auth(level: NO_ACCESS) {
  ingestionBatch(id: $id) { id revision payload }
}''', '''mutation CreateIngestionBatch($id: String!, $revision: Int!, $revisionId: String!, $payload: Any!) @auth(level: NO_ACCESS) @transaction {
  ingestionBatch_insert(data: {id: $id revision: $revision payload: $payload})
  ingestionRevision_insert(data: {id: $revisionId batchId: $id revision: $revision payload: $payload})
}''', '''mutation UpdateIngestionBatch($id: String!, $expectedRevision: Int!, $revision: Int!, $revisionId: String!, $payload: Any!) @auth(level: NO_ACCESS) @transaction {
  ingestionBatch_updateMany(where: {id: {eq: $id} revision: {eq: $expectedRevision}}, data: {revision: $revision payload: $payload})
    @check(expr: "this == 1 && vars.revision == vars.expectedRevision + 1", message: "INGESTION_STALE_REVISION")
  ingestionRevision_insert(data: {id: $revisionId batchId: $id revision: $revision payload: $payload})
}''']
    for entity in ("projects", "materials"):
        typ = TYPES[entity]
        singular = typ[0].lower() + typ[1:]
        selection = " ".join(camel(name) for name, _, _ in fields(entity))
        operations.append(f'''query GetIntake{typ}($id: String!) @auth(level: NO_ACCESS) {{
  {singular}(id: $id) {{ {selection} }}
}}''')
    scopes = {
        "projects": "", "materials": "",
        "documents": "projectId: {eq: $projectId}",
        "extracted_rows": "document: {projectId: {eq: $projectId}}",
        "supply_offers": "sourceProjectId: {eq: $projectId}",
        "demand_requests": "destinationProjectId: {eq: $projectId}",
        "allocation_proposals": "_or: [{supplyOffer: {sourceProjectId: {eq: $projectId}}}, {demandRequest: {destinationProjectId: {eq: $projectId}}}]",
        "transfers": "proposal: {_or: [{supplyOffer: {sourceProjectId: {eq: $projectId}}}, {demandRequest: {destinationProjectId: {eq: $projectId}}}]}",
        "demand_commitments": "demandRequest: {destinationProjectId: {eq: $projectId}}",
    }
    for entity, scope in scopes.items():
        key = "demandRequestId" if entity == "demand_commitments" else "id"
        plural = "demandCommitmentBalances" if entity == "demand_commitments" else camel(entity)
        selection = "demandRequestId committedQuantity" if entity == "demand_commitments" else " ".join(camel(name) for name, _, _ in fields(entity))
        name = camel(entity)
        name = name[0].upper() + name[1:]
        project_variable = ", $projectId: String!" if scope else ""
        where = f"_and: [{{{key}: {{gt: $after}}}}, {{{scope}}}]" if scope else f"{key}: {{gt: $after}}"
        operations.append(f'''query PageIntake{name}($after: String!, $limit: Int!{project_variable}) @auth(level: NO_ACCESS) {{
  records: {plural}(where: {{{where}}}, orderBy: {{{key}: ASC}}, limit: $limit) {{ {selection} }}
}}''')
    return schema, "\n\n" + "\n\n".join(operations) + "\n"
