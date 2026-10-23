"""Local workspace identity, complete archive reads and controlled cutover."""
import re


def table_specs(schema):
    result=[]
    for match in re.finditer(r'type (\w+)\s+@table\(([^)]*)\)\s*\{([^}]+)\}',schema):
        name,attrs,body=match.groups()
        def attribute(key):return re.search(r'\b'+key+r':\s*"([^"]+)"',attrs).group(1)
        columns=[m.group(1) for line in body.splitlines() if '@ref' not in line
                 for m in [re.match(r'\s*(\w+):',line)] if m]
        result.append({'type':name,'plural':attribute('plural'),'key':attribute('key'),'fields':columns})
    return result


def extend_workspace(schema,operations):
    schema+='''
type WorkspaceIdentity @table(name: "workspace_identity", key: "id", singular: "workspaceIdentity", plural: "workspaceIdentities") {
  id: String!
  epoch: String!
  createdAt: Timestamp!
}
'''
    operations+='''
query GetCutoverBatchHeads @auth(level: NO_ACCESS) { ingestionBatches(limit: 1000, orderBy: {id: ASC}) { id revision } }
query GetWorkspaceIdentity @auth(level: NO_ACCESS) { workspaceIdentity(id: "GLOBAL") { epoch createdAt } }
mutation InitializeWorkspaceIdentity($epoch: String!, $createdAt: Timestamp!) @auth(level: NO_ACCESS) @transaction {
  workspaceIdentity_insert(data: {id: "GLOBAL" epoch: $epoch createdAt: $createdAt})
}
'''
    for spec in table_specs(schema):
        key=spec['key'];selection=' '.join(spec['fields'])
        operations+=f'''query PageArchive{spec['type']}($after: String!, $limit: Int!) @auth(level: NO_ACCESS) {{
  records: {spec['plural']}(where: {{{key}: {{gt: $after}}}}, orderBy: {{{key}: ASC}}, limit: $limit) {{ {selection} }}
}}\n'''
    clear=re.search(r'mutation ClearBaseline @auth\(level: NO_ACCESS\) @transaction \{([\s\S]*?)\n}',operations).group(1)
    clear=re.sub(r'\n  operationalVersion_updateMany[^\n]+','',clear)
    operations+='''mutation ResetLocalWorkspace($expectedOperationalRevision: Int!, $expectedBatches: Any!) @auth(level: NO_ACCESS) @transaction {
  cutoverGuard: operationalVersion_updateMany(where: {id: {eq: "GLOBAL"} revision: {eq: $expectedOperationalRevision}},data: {revision_update: {inc: 1}}) @check(expr: "this == 1",message: "CUTOVER_CONTEXT_STALE")
''' + '''  cutoverHeads: query @redact @check(expr: "size(response.cutoverHeads.ingestionBatches) < 1000 && size(response.cutoverHeads.ingestionBatches) == size(vars.expectedBatches.batches) && response.cutoverHeads.ingestionBatches.all(row, vars.expectedBatches.batches.exists(prior, prior.id == row.id && int(prior.revision) == row.revision))",message: "CUTOVER_DRAFTS_CHANGED") {
    ingestionBatches(limit: 1000) { id revision }
  }
''' + clear+'''
  ingestionRevision_deleteMany(all: true)
  ingestionBatch_deleteMany(all: true)
  workspaceIdentity_deleteMany(all: true)
}
'''
    # A fresh clone may install public demo facts, but never merge them into
    # existing work. Serialize against operational writes and check every
    # business/draft table in the same transaction as the import.
    template=re.search(r'mutation ImportBaseline\(([\s\S]*?)\n\) @auth\(level: NO_ACCESS\) @transaction \{([\s\S]*?)\n}',operations)
    arguments,body=template.groups()
    body=re.sub(r'\n  operationalVersion_updateMany[^\n]+','',body)
    specs=[s for s in table_specs(schema) if s['type'] not in ('OperationalVersion','QuantityEncoding')]
    condition=' && '.join(f'size(response.empty.{s["plural"]}) == 0' for s in specs)
    selection='\n'.join(f'    {s["plural"]}(limit: 1) {{ {s["key"]} }}' for s in specs)
    operations+=f'''mutation ImportDemoWorkspace({arguments}
  $expectedRevision: Int!
  $epoch: String!
  $createdAt: Timestamp!
  $receipt: Any!
) @auth(level: NO_ACCESS) @transaction {{
  operationalVersion_updateMany(where: {{id: {{eq: "GLOBAL"}} revision: {{eq: $expectedRevision}}}}, data: {{revision_update: {{inc: 1}}}}) @check(expr: "this == 1", message: "DEMO_WORKSPACE_CHANGED")
  empty: query @redact @check(expr: "{condition}", message: "DEMO_REQUIRES_EMPTY_WORKSPACE") {{
{selection}
  }}
  encoding: query @redact @check(expr: "response.encoding.quantityEncoding != null && response.encoding.quantityEncoding.version == 'millionths-v1'", message: "DEMO_REQUIRES_EXACT_QUANTITIES") {{
    quantityEncoding(id: "GLOBAL") {{ version }}
  }}
{body}
  workspaceIdentity_insert(data: {{id: "GLOBAL" epoch: $epoch createdAt: $createdAt}})
  runtimeAudit_insert(data: {{id: "DEMO-WORKSPACE-BOOTSTRAP" kind: "DEMO_BOOTSTRAP" payload: $receipt}})
}}
'''
    return schema,operations
