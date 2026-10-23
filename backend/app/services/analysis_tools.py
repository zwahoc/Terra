"""Typed Terra-only tools. Model write tools can create run-local proposals only."""

import copy
from threading import Lock
from typing import Literal
from uuid import uuid4

from pydantic import Field, ValidationError, model_validator

from backend.app.schemas.analysis import AnalysisModel, MaterialProposal, ProjectProposal, ProposedEntity, ToolObservation
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.ingestion_service import now
from backend.app.services.ingestion_storage import digest_json
from backend.app.services.material_search import MATERIAL_SEARCH_FIELDS, flexible_material_page, normalise_search_text


class SearchArguments(AnalysisModel):
    query: str = ""
    after: str = ""
    limit: int = Field(50, ge=1, le=200)


class RunContextArguments(SearchArguments):
    collection: Literal['proposals', 'file_records'] = 'proposals'
    submission_id: str | None = None


class MaterialSearchQuery(SearchArguments):
    query_id: str = Field(min_length=1)
    terms: list[str] = Field(default_factory=list, description='Alternative literal words/phrases chosen by the model. Cannot be combined with nonempty query. Each phrase stays together.')
    match_mode: Literal['ANY', 'ALL'] | None = Field(None, description='ANY = any term; ALL = every term, across selected fields. With query, split query on whitespace. With terms, preserve each phrase. No mode/terms/fields = original literal search.')
    search_fields: list[Literal['id', 'canonical_name', 'reference_code', 'category', 'specifications', 'standard_unit']] | None = Field(None, description='Published catalogue fields to inspect. Flexible search defaults to all listed fields, including nested specifications. No equivalence judgement.')

    @model_validator(mode='after')
    def valid_search(self):
        if self.terms and self.query.strip():
            raise ValueError('Use terms or query, not both')
        if any(not term.strip() for term in self.terms) or self.search_fields == []:
            raise ValueError('Search terms and selected fields cannot be blank')
        return self


class BulkMaterialArguments(AnalysisModel):
    queries: list[MaterialSearchQuery] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_ids(self):
        if len({q.query_id for q in self.queries}) != len(self.queries):
            raise ValueError('query_id must be unique in a bulk request')
        return self


class ProjectArguments(AnalysisModel):
    project_id: str = Field(min_length=1)


class MaterialArguments(AnalysisModel):
    material_id: str = Field(min_length=1)


class ProjectRecordsArguments(ProjectArguments):
    collection: Literal["documents", "extracted_rows", "supply_offers", "demand_requests", "allocation_proposals", "transfers", "demand_commitments"]
    after: str = ""
    limit: int = Field(100, ge=1, le=200)


class RecordArguments(ProjectArguments):
    collection: Literal["documents", "extracted_rows", "supply_offers", "demand_requests", "allocation_proposals", "transfers", "demand_commitments"]
    record_id: str = Field(min_length=1)


class PublishedRecordsArguments(ProjectRecordsArguments):
    collection: Literal['published_records', 'superseded_records', 'stock_heads'] = 'published_records'


class PublishedRecordArguments(RecordArguments):
    collection: Literal['published_records', 'superseded_records', 'stock_heads'] = 'published_records'


class RelatedDocumentsArguments(ProjectArguments):
    after: str = ""
    limit: int = Field(100, ge=1, le=200)


TOOLS = {
    'get_published_records': (PublishedRecordsArguments, 'Read current published project/material evidence, supersession markers or stock scopes. Follow all pages. Source observations are distinct from current physical balances.'),
    'get_published_record_context': (PublishedRecordArguments, 'Read an exact published record or stock scope within its project. Use only returned IDs.'),
    'get_run_draft_context': (RunContextArguments, 'Read only this model run\'s provisional proposals or saved file material records. Use collection=proposals or file_records plus submission_id. Query is literal case-insensitive text; empty query returns all. Follow next_cursor for every match. Never approved facts or another model\'s drafts.'),
    "search_projects": (SearchArguments, "Search published Terra projects. Follow next_cursor even for empty filtered pages."),
    "get_project_context": (ProjectArguments, "Read project facts, materials, recorded stock/supply/demand and commitments. Not a complete physical-stock ledger."),
    "search_materials": (SearchArguments, "Search the existing Terra material catalogue. Name similarity alone does not prove compatibility."),
    "search_materials_bulk": (BulkMaterialArguments, "Search multiple materials in one request. Prefer terms with ANY for alternative names, or ALL for required words/spec evidence. Search names, codes and specifications; every match is accessible in stable ID order through next_cursor, with no ranking or top-N suppression. Follow each query's cursor with unchanged criteria until search.complete. Empty completed search proves only no match for those terms/fields. Query alone preserves original literal name/code search and source-page cursors. Repeated equivalent queries are cached, then blocked individually. Names alone do not establish compatibility."),
    "get_material_context": (MaterialArguments, "Get an exact existing catalogue material and its specifications."),
    "get_project_records": (ProjectRecordsArguments, "Read a page of this project's stored document, extracted-row, offer, demand, proposal, transfer or commitment records."),
    "get_record_context": (RecordArguments, "Find an exact stored record within a project, following all pages."),
    "find_related_documents": (RelatedDocumentsArguments, "Read project document metadata to investigate overlap/revisions. These are stored records, not automatically new stock."),
    "propose_project": (ProjectProposal, "Create a provisional project in this model run only. Unknown fields may be null. Requires human review."),
    "propose_material": (MaterialProposal, "Create a provisional material in this model run only. Categories/units may extend the seed; no eligibility or engineering approval is implied."),
}


def tool_definitions():
    return [{"name": name, "description": description, "parameters": model.model_json_schema()}
            for name, (model, description) in TOOLS.items()]


def model_business_context(value):
    """Copy stored evidence without developer fixture provenance.

    Storage and ordinary HTTP reads retain audit fields. Business evidence,
    including absent attachments, unknown quantities and mass assumptions,
    remains visible. Never rewrite free text or change business statuses.
    """
    from decimal import Decimal
    from terra.quantities import text
    if isinstance(value,Decimal):return text(value)
    if isinstance(value, list):
        return [model_business_context(item) for item in value]
    if not isinstance(value, dict):
        return value
    audit_fields = {'is_synthetic', 'is_simulated', 'synthetic_baseline', 'synthetic_test_fixture'}
    if value.get('synthetic_baseline') is True:
        audit_fields.add('baseline_as_of_date')
    if value.get('review_mode') in ('DEMO_PREAPPROVED', 'PENDING_DEMO'):
        audit_fields.add('review_mode')
    if value.get('processing_status') == 'SIMULATED':
        audit_fields.add('processing_status')
    return {key: model_business_context(item) for key, item in value.items() if key not in audit_fields}


class FrozenTerraReads:
    """Equivalent queries share observed approved-store facts, never model proposals."""
    def __init__(self, reads):
        self.reads, self.cache, self.lock = reads, {}, Lock()
        self.material_pages = {}

    def _material_page(self, *, after, limit):
        # Shared observed catalogue pages, never sent wholesale to the model.
        key = (after, limit)
        if key not in self.material_pages:
            self.material_pages[key] = copy.deepcopy(self.reads.page('materials', after=after, limit=limit))
        return copy.deepcopy(self.material_pages[key])

    def call(self, name, args):
        key = digest_json({"tool": name, "arguments": args})
        with self.lock:
            if key in self.cache:
                return copy.deepcopy(self.cache[key])
            if name == "search_projects":
                result = self.reads.page("projects", **args)
            elif name == "search_materials":
                result = self.reads.page("materials", **args)
            elif name == 'search_materials_flexible':
                result = flexible_material_page(self._material_page, **args)
            elif name == "get_project_context":
                result = self.reads.project_context(args["project_id"])
            elif name == "get_material_context":
                result = {"material": self.reads.get_entity("materials", args["material_id"])}
            elif name in ("get_project_records", "find_related_documents", "get_published_records"):
                values = dict(args)
                collection = values.pop("collection", "documents")
                if self.reads.get_entity("projects", values["project_id"]) is None:
                    raise IngestionError("PROJECT_NOT_FOUND", "Requested project does not exist.", 404)
                result = self.reads.page(collection, **values)
            elif name in ("get_record_context", "get_published_record_context"):
                after, found = "", None
                while True:
                    page = self.reads.page(args["collection"], project_id=args["project_id"], after=after)
                    found = next((row for row in page["records"] if row["id"] == args["record_id"]), None)
                    if found is not None or page["next_cursor"] is None:
                        break
                    after = page["next_cursor"]
                result = {"record": found}
            else:
                raise IngestionError("TOOL_NOT_ALLOWED", "This operation is not a Terra read tool.")
            result = {**model_business_context(result), "fact_source": "STORED_TERRA_RECORDS", "consistency": "OBSERVED_READS"}
            self.cache[key] = copy.deepcopy(result)
            return result


class ToolExecutor:
    def __init__(self, run, reads, persist):
        self.run, self.reads, self.persist = run, reads, persist
        self.calls = 0
        self.start_file()

    def start_file(self):
        self.repeats, self.answers, self.evidence = {}, {}, set()
        self.progress_count = 0

    def _read(self, name, arguments):
        arguments = dict(arguments)
        if 'query' in arguments:
            arguments['query'] = arguments['query'].casefold().strip()
        key = digest_json({'tool': name, 'arguments': arguments})
        count = self.repeats.get(key, 0) + 1
        self.repeats[key] = count
        if key in self.answers:
            if count >= 3:
                return {'status': 'REPEATED_REQUEST_BLOCKED',
                        'message': 'This exact operation was already answered. Use previous_result or continue with other work. The file is not blocked.',
                        'previous_result': copy.deepcopy(self.answers[key])}
            return {**copy.deepcopy(self.answers[key]), 'lookup_status': 'CACHED'}
        try:
            result = self.reads.call(name, arguments)
        except IngestionError as exc:
            if exc.status >= 500:
                raise
            result = {'error': {'code': exc.code, 'message': exc.message}}
        self.answers[key] = copy.deepcopy(result)
        # Evidence, rather than minor query spelling changes, establishes progress.
        evidence_result = {key: value for key, value in result.items() if key != 'search'}
        fingerprint = digest_json({'tool': name, 'result': evidence_result})
        if fingerprint not in self.evidence:
            self.evidence.add(fingerprint)
            self.progress_count += 1
        return result

    @staticmethod
    def _merge_proposal(previous, incoming):
        """Reuse exact names with nonconflicting metadata; distinct specs stay distinct."""
        merged = copy.deepcopy(previous)
        for key, value in incoming.items():
            if value is None or value == {}:
                continue
            old = merged.get(key)
            if key == 'specifications' and isinstance(old, dict):
                if any(k in old and old[k] != v for k, v in value.items()):
                    return None
                merged[key] = {**old, **value}
            elif old is None or old == {}:
                merged[key] = value
            elif old != value:
                return None
        return merged

    def execute(self, call):
        self.calls += 1
        model = TOOLS.get(call.name, (None,))[0]
        if model is None:
            result = {"error": {"code": "TOOL_NOT_ALLOWED", "message": "Only the declared Terra tools can be called."}}
            # Do not echo arbitrary unrecognised arguments into storage/logs.
            arguments = {}
        else:
            try:
                arguments = model.model_validate(call.arguments).model_dump(mode="json")
                if call.name in ("propose_project", "propose_material"):
                    kind = "PROJECT" if call.name == "propose_project" else "MATERIAL"
                    proposal = None
                    for existing in self.run.proposals:
                        if existing.kind == kind:
                            merged = self._merge_proposal(existing.attributes, arguments)
                            if merged is not None:
                                proposal = existing
                                if merged != existing.attributes:
                                    existing.attributes = merged
                                    self.progress_count += 1
                                break
                    if proposal is None:
                        proposal = ProposedEntity(id=f"DRAFT-{kind}-{uuid4().hex}", kind=kind, attributes=arguments)
                        self.run.proposals.append(proposal)
                        self.progress_count += 1
                    result = {"proposal": proposal.model_dump(mode="json"), "fact_source": "THIS_RUN_PROVISIONAL_ONLY"}
                    key = digest_json({'tool': call.name, 'arguments': arguments})
                    self.repeats[key] = self.repeats.get(key, 0) + 1
                    if self.repeats[key] >= 3:
                        result = {'status': 'REPEATED_REQUEST_BLOCKED', 'previous_result': result,
                                  'message': 'This proposal already exists; use its returned ID. The file is not blocked.'}
                elif call.name == 'search_materials_bulk':
                    results = []
                    for query in arguments['queries']:
                        values = dict(query)
                        query_id = values.pop('query_id')
                        terms, mode, fields = (values.pop('terms'), values.pop('match_mode'), values.pop('search_fields'))
                        if terms or mode is not None or fields is not None:
                            text = values.pop('query')
                            terms = terms or text.split()
                            values.update(terms=sorted({normalise_search_text(term) for term in terms}),
                                          match_mode=mode or 'ANY',
                                          search_fields=sorted(set(fields or MATERIAL_SEARCH_FIELDS)))
                            name = 'search_materials_flexible'
                        else:
                            name = 'search_materials'
                        results.append({'query_id': query_id, **self._read(name, values)})
                    result = {'results': results}
                elif call.name == 'get_run_draft_context':
                    from backend.app.services.material_search import field_text
                    if arguments['collection'] == 'proposals':
                        rows = [p.model_dump(mode='json') for p in self.run.proposals]
                    else:
                        selected = next((f for f in self.run.files if f.submission_id == arguments['submission_id']), None)
                        if selected is None:
                            raise IngestionError('DRAFT_NOT_FOUND', 'No file with that ID exists in this model run.', 404)
                        rows = []
                        if selected and selected.draft:
                            rows = [{'id': f'{i:012}', 'record_index': i, 'record': row.model_dump(mode='json')}
                                    for i, row in enumerate(selected.draft.records)]
                        elif selected:
                            rows = [{'id': f'{group.id}:{i:012}', 'record_ref': f'{group.id}:{i}', 'group_id': group.id, 'record_index': i, 'record': row.model_dump(mode='json')}
                                    for group in selected.page_groups if group.status == 'SUCCEEDED' for i, row in enumerate(group.draft.records)]
                    rows = sorted((row for row in rows if row['id'] > arguments['after'] and
                                   arguments['query'].casefold() in field_text(row).casefold()), key=lambda row: row['id'])
                    page = rows[:arguments['limit']]
                    result = {'records': page, 'next_cursor': page[-1]['id'] if len(rows) > len(page) else None,
                              'fact_source': 'THIS_RUN_PROVISIONAL_ONLY', 'coverage': 'PAGE'}
                    key = digest_json({'tool': call.name, 'arguments': arguments, 'result': result})
                    count = self.repeats.get(key, 0) + 1
                    self.repeats[key] = count
                    fingerprint = digest_json(result)
                    if fingerprint not in self.evidence:
                        self.progress_count += 1
                        self.evidence.add(fingerprint)
                    if count >= 3:
                        result = {'status': 'REPEATED_REQUEST_BLOCKED', 'previous_result': result,
                                  'message': 'This exact observed draft context was already returned. Other work can continue.'}
                else:
                    result = self._read(call.name, arguments)
            except ValidationError:
                arguments = {}
                result = {"error": {"code": "TOOL_ARGUMENTS_INVALID", "message": "Arguments did not match the tool schema. Correct them and retry."}}
            except IngestionError as exc:
                # Provider/storage outages stop the run; they are not model-repairable input.
                if exc.status >= 500:
                    raise
                result = {"error": {"code": exc.code, "message": exc.message}}
        self.run.observations.append(ToolObservation(tool=call.name, arguments=arguments, result=result, observed_at=now()))
        self.persist(self.run)
        return {"id": call.id, "name": call.name, "result": result}

    def validate_references(self, draft):
        references = [("PROJECT", ref, f'/project_refs/{i}') for i, ref in enumerate(draft.project_refs)]
        references.extend((kind, ref, f'/records/{i}/{field}') for i, record in enumerate(draft.records)
            for kind, field, ref in (("PROJECT", 'project_ref', record.project_ref), ("MATERIAL", 'material_ref', record.material_ref)))
        references.extend(('PROJECT', info.project_ref, f'/project_info/{i}/project_ref') for i, info in enumerate(draft.project_info))
        invalid = []
        for kind, ref, path in references:
            if ref is None:
                continue
            if ref.kind == "PROPOSED":
                valid = any(p.id == ref.id and p.kind == kind for p in self.run.proposals)
            elif kind == "PROJECT":
                try:
                    self.reads.call("get_project_context", {"project_id": ref.id})
                    valid = True
                except IngestionError as exc:
                    if exc.status >= 500:
                        raise
                    valid = False
            else:
                valid = self.reads.call("get_material_context", {"material_id": ref.id})["material"] is not None
            if not valid:
                invalid.append(path)
        if invalid:
            error = IngestionError("DRAFT_REFERENCE_INVALID", "A draft references an unknown entity or another model run's proposal.")
            error.details = {'invalid_reference_paths': invalid}
            raise error
