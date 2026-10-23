"""Draft-only extraction and reconciliation guards, independent of HTTP handlers."""

from backend.app.services.ingestion_errors import IngestionError


def output_error(message, paths=()):
    error = IngestionError('MODEL_OUTPUT_INVALID', message)
    error.allowed_paths = list(paths)
    return error


def combine_validation_errors(errors):
    """Keep every independent defect and its repair scope in one response."""
    if len(errors) == 1:
        error = errors[0]
    else:
        error = IngestionError(errors[0].code, f'The candidate has {len(errors)} validation problems; correct the reported defects together.')
    error.allowed_paths = list(dict.fromkeys(path for item in errors for path in getattr(item, 'allowed_paths', [])))
    details, validation = {}, []
    for item in errors:
        paths = getattr(item, 'allowed_paths', [])
        validation.extend(getattr(item, 'validation_errors', None) or [{
            'location': [int(p) if p.isdigit() else p.replace('~1', '/').replace('~0', '~') for p in paths[0].lstrip('/').split('/')] if paths else [],
            'type': item.code, 'message': item.message,
        }])
        for key, value in getattr(item, 'details', {}).items():
            if isinstance(value, list):
                collected = details.setdefault(key, [])
                for entry in value:
                    if entry not in collected:
                        collected.append(entry)
            else:
                details[key] = value
    error.validation_errors = validation
    error.details = details
    return error


def validate_material_extraction(draft):
    errors, warnings = [], []
    def add(message, paths, **details):
        error = output_error(message, paths)
        error.details = details
        errors.append(error)
    if draft.extraction_version != 'MATERIAL_V2':
        add('Return MATERIAL_V2 extraction metadata, project context and internal source-item accounting.',
            ['/extraction_version', '/project_info', '/source_items'])
    for index, row in enumerate(draft.records):
        base = f'/records/{index}'
        if (row.evidence_basis == 'INFERRED' or row.inferred_fields) and not row.inference_explanation:
            add('Inferred information requires a specific evidence-based explanation.', [base + '/inference_explanation'])
        if row.quantity_basis in ('SOURCE_WORK', 'UNKNOWN') and row.quantity is not None:
            add('Source work quantities cannot become individual material quantities. Preserve raw source values.',
                [base + '/quantity_basis', base + '/quantity', base + '/unit'])
        if row.quantity_basis == 'SOURCE_WORK' and row.unit is not None:
            add('Keep source work units in raw_unit rather than a material unit.', [base + '/unit'])
        if row.application != 'UNDECIDED' or row.replaces_record_ids:
            add('Extraction does not decide changes to existing project records; reconciliation follows.',
                [base + '/application', base + '/replaces_record_ids'])
    project_refs = {(r.kind, r.id) for r in [*draft.project_refs, *(row.project_ref for row in draft.records)] if r}
    info_refs = {(p.project_ref.kind, p.project_ref.id) for p in draft.project_info if p.project_ref}
    if not project_refs <= info_refs:
        add('Identified projects require visible extracted project information and an association explanation.', ['/project_info'])
    linked = set()
    for position, item in enumerate(draft.source_items):
        indices = item.record_indices
        base = f'/source_items/{position}'
        if len(indices) != len(set(indices)) or any(i < 0 or i >= len(draft.records) for i in indices):
            add('Source-item record indices must be unique and in range.', [base + '/record_indices'])
        if (item.disposition == 'MATERIAL') != bool(indices):
            add('Source-item disposition and record indices disagree.', [base + '/disposition', base + '/record_indices'])
        mismatches = []
        for index in indices:
            if not 0 <= index < len(draft.records):
                continue
            row = draft.records[index]
            if item.source_page not in [row.source_page, *row.additional_source_pages] or row.source_item_ref != item.source_item_ref:
                mismatches.append({'record_index': index, 'record_page': row.source_page,
                                   'record_ref': row.source_item_ref, 'entry_page': item.source_page,
                                   'entry_ref': item.source_item_ref})
            else:
                linked.add(index)
        if mismatches:
            paths = [base + '/record_indices']
            # The coverage membership may be wrong, or an associated record may
            # have omitted/misstated its item reference. Permit either specific
            # link correction, never the whole record or raw source evidence.
            paths.extend(f"/records/{mismatch['record_index']}/source_item_ref"
                         for mismatch in mismatches if mismatch['record_ref'] != mismatch['entry_ref'])
            add('Material candidates must retain the source item/page referenced by their coverage entry.',
                paths, source_link_mismatches=mismatches)
        if item.disposition == 'UNREADABLE':
            warnings.append(f'Source item {item.source_item_ref} on page {item.source_page or "unknown"} is unreadable; material completeness requires human review. {item.explanation}')
    for index, row in enumerate(draft.records):
        if row.source_item_ref is not None and index not in linked:
            entries = [i for i, item in enumerate(draft.source_items)
                       if item.source_page in [row.source_page, *row.additional_source_pages] and item.source_item_ref == row.source_item_ref]
            paths = [f'/source_items/{i}/record_indices' for i in entries] or ['/source_items/-']
            details = {} if entries else {'missing_source_items': [{'page': row.source_page, 'item_reference': row.source_item_ref}]}
            add('A numbered material candidate is missing its valid internal source-item link.', paths, **details)
    if errors:
        raise combine_validation_errors(errors)
    draft.issues.extend(warning for warning in warnings if warning not in draft.issues)


def validate_reconciliation(result, draft, reads):
    errors = []
    def add(message, paths):
        errors.append(output_error(message, paths))
    indices = [item.record_index for item in result.materials]
    if sorted(indices) != list(range(len(draft.records))):
        add('Reconciliation must account for every extracted material exactly once.', ['/materials'])
    projects = [item.project_info_index for item in result.projects]
    if sorted(projects) != list(range(len(draft.project_info))):
        add('Reconciliation must account for every extracted project exactly once.', ['/projects'])
    for index, item in enumerate(result.materials):
        if not 0 <= item.record_index < len(draft.records):
            continue
        row = draft.records[item.record_index]
        path = f'/materials/{index}'
        if item.relationship in ('ADDITIONAL_EVIDENCE', 'NEWER_OBSERVATION', 'POSSIBLE_DUPLICATE', 'POSSIBLE_REVISION', 'CONFLICT') and not item.existing_records:
            add('An existing-record relationship needs verified stored references.', [path])
        if item.suggested_treatment == 'REPLACE' and not item.existing_records:
            add('Replacement requires an existing stored record.', [path])
        for ref in item.existing_records:
            if row.project_ref is None or row.project_ref.kind != 'EXISTING' or ref.project_id != row.project_ref.id:
                add('A reconciliation reference must belong to the extracted material project.', [path + '/existing_records'])
                continue
            record = reads.call('get_record_context', {'project_id': ref.project_id, 'collection': ref.collection,
                                                     'record_id': ref.record_id})['record']
            if record is None:
                add('Reconciliation referenced a record not found in that project.', [path + '/existing_records'])
                continue
            material_id = record.get('material_id') or record.get('suggested_material_id')
            if material_id and row.material_ref and row.material_ref.kind == 'EXISTING' and material_id != row.material_ref.id:
                add('A cited material record refers to a different catalogue material.', [path + '/existing_records'])
    if errors:
        raise combine_validation_errors(errors)
