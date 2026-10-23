"""Checkpoint B local transactions and durable impact work."""
import re


def extend_transfer_runtime(schema, operations):
    schema += '''
type ImpactRefreshIntent @table(name: "impact_refresh_intents", key: "id", singular: "impactRefreshIntent", plural: "impactRefreshIntents") {
  id: String!
  token: String!
  status: String!
  payload: Any!
}
'''
    def operation(name):
        return re.search(r'mutation '+name+r'\([\s\S]*?\n}', operations).group(0)

    combined = operation('ProveCombinedTransferReservation').replace('ProveCombinedTransferReservation(', 'ConfirmTransferReservation(')
    # The two immutable events retain the original proposal and chosen-quantity
    # forecast in eventPayload. No original plan assessment is overwritten.
    operations += '\n'+combined+'\n'
    for name in ('ReserveTransfer','DispatchTransfer','ReceiveTransfer','ConfirmTransferUse','CancelTransfer'):
        old=operation(name)
        new=old.replace(') @auth', '''  $matchingScopes: [MatchingScope_Data!]! = [] @allow(fields: "id token status generationId payload", maxCount: 100)
  $impactIntents: [ImpactRefreshIntent_Data!]! = [] @allow(fields: "id token status payload", maxCount: 100)
) @auth''',1)
        new=new[:-1]+'''  matchingScope_upsertMany(data: $matchingScopes)
  impactRefreshIntent_upsertMany(data: $impactIntents)
}'''
        operations=operations.replace(old,new)
    old=operation('ConfirmRuntimeInputs')
    new=old.replace(') @auth',''' $impactIntents: [ImpactRefreshIntent_Data!]! = [] @allow(fields: "id token status payload", maxCount: 10000)
) @auth''',1)
    new=new[:-1]+''' impactRefreshIntent_upsertMany(data: $impactIntents)
}'''
    operations=operations.replace(old,new)
    old=operation('PersistActualImpactAssessment')
    new=old.replace('PersistActualImpactAssessment(', 'PersistCurrentActualImpact(')
    new=re.sub(r'  operationalVersion_updateMany[^\n]+\n', '', new)
    new=new.replace(') @auth','''  $expectedOperationalRevision: Int!
  $intentToken: String!
  $intentPayload: Any!
) @auth''',1)
    new=new.replace('@transaction {','''@transaction {
  operationalVersion_updateMany(where: {id: {eq: "GLOBAL"} revision: {eq: $expectedOperationalRevision}}, data: {revision_update: {inc: 1}}) @check(expr: "this == 1", message: "IMPACT_INPUT_STALE")
  impactRefreshIntent_updateMany(where: {id: {eq: $transferId} token: {eq: $intentToken} status: {in: ["PENDING","FAILED"]}},data: {status: "COMPLETED" payload: $intentPayload}) @check(expr: "this == 1", message: "IMPACT_INTENT_STALE")''',1)
    operations+='\n'+new+'\n'
    operations=operations.replace('mutation ClearBaseline @auth(level: NO_ACCESS) @transaction {','mutation ClearBaseline @auth(level: NO_ACCESS) @transaction {\n  impactRefreshIntent_deleteMany(all: true)')
    operations+='''
mutation EnqueueImpactPolicyRefresh($id: String!, $token: String!, $payload: Any!, $expectedOperationalRevision: Int!) @auth(level: NO_ACCESS) @transaction {
  operationalVersion_updateMany(where: {id: {eq: "GLOBAL"} revision: {eq: $expectedOperationalRevision}},data: {revision_update: {inc: 1}}) @check(expr: "this == 1", message: "IMPACT_INPUT_STALE")
  impactRefreshIntent_upsert(data: {id: $id token: $token status: "PENDING" payload: $payload})
}
mutation ReactivateMatchingGeneration($id: String!, $materialId: String!, $token: String!, $fingerprint: String!, $expectedRevision: Int!) @auth(level: NO_ACCESS) @transaction {
  operationalVersion_updateMany(where: {id: {eq: "GLOBAL"} revision: {eq: $expectedRevision}},data: {revision_update: {inc: 1}}) @check(expr: "this == 1", message: "MATCHING_INPUT_STALE")
  query @redact @check(expr: "response.query.matchingGeneration.materialId == vars.materialId && response.query.matchingGeneration.fingerprint == vars.fingerprint",message: "MATCHING_INPUT_STALE") {
    matchingGeneration(id: $id) { materialId fingerprint }
  }
  matchingScope_updateMany(where: {id: {eq: $materialId} token: {eq: $token} status: {eq: "PENDING"}},data: {status: "CURRENT" generationId: $id payload: {}}) @check(expr: "this == 1",message: "MATCHING_SCOPE_STALE")
}
query PageImpactIntents($after: String!, $limit: Int!) @auth(level: NO_ACCESS) {
  records: impactRefreshIntents(where: {id: {gt: $after}}, orderBy: {id: ASC}, limit: $limit) { id token status payload }
}
query GetImpactIntent($id: String!) @auth(level: NO_ACCESS) { impactRefreshIntent(id: $id) { id token status payload } }
mutation SetImpactIntent($id: String!, $token: String!, $status: String!, $payload: Any!) @auth(level: NO_ACCESS) @transaction {
  impactRefreshIntent_upsert(data: {id: $id token: $token status: $status payload: $payload})
}
mutation FinishImpactIntent($id: String!, $token: String!, $status: String!, $payload: Any!, $expectedOperationalRevision: Int!) @auth(level: NO_ACCESS) @transaction {
  operationalVersion_updateMany(where: {id: {eq: "GLOBAL"} revision: {eq: $expectedOperationalRevision}},data: {revision_update: {inc: 1}}) @check(expr: "this == 1", message: "IMPACT_INPUT_STALE")
  impactRefreshIntent_updateMany(where: {id: {eq: $id} token: {eq: $token}},data: {status: $status payload: $payload}) @check(expr: "this == 1", message: "IMPACT_INTENT_STALE")
}
'''
    return schema,operations
