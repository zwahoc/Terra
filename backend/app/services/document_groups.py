"""Provider-constrained page planning and explicit, auditable file assembly."""

import json
from backend.app.schemas.analysis import FileDraft
from backend.app.services.ingestion_errors import IngestionError

CONTEXT_TOKENS = 1048576
OUTPUT_TOKENS = 393216
REQUEST_BYTES = 48 * 1024 * 1024
IMAGES = 600
IMAGE_BYTES = 200 * 1024 * 1024


def input_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())


def partition_records(records, capacity):
    parts, current, size = [], [], 0
    for index, record in enumerate(records):
        needed = input_size(record) + 2
        if needed > capacity:
            raise IngestionError('MODEL_INPUT_TOO_LARGE', 'One record exceeds available request context. Its source and completed work are retained.')
        if current and size + needed > capacity:
            parts.append(current)
            current, size = [], 0
        current.append(index)
        size += needed
    if current or not parts:
        parts.append(current)
    return parts


def plan_pages(document, overhead=0):
    groups, current = [], []
    image_count = total_bytes = text_bytes = 0
    for page in document.pages:
        number = page['page_number']
        images = page['images']
        count, size = len(images), sum(image['bytes'] for image in images)
        text = len(document.text(number).encode())
        if count > IMAGES or size > IMAGE_BYTES or text + count * 1024 + overhead + OUTPUT_TOKENS > CONTEXT_TOKENS:
            raise IngestionError('PROVIDER_PAGE_LIMIT', 'One page exceeds the provider request/context capacity, including its detail views. Original and completed work are retained.')
        if current and (image_count + count > IMAGES or total_bytes + size > IMAGE_BYTES or
                        text_bytes + text + (image_count + count) * 1024 + overhead + OUTPUT_TOKENS > CONTEXT_TOKENS):
            groups.append(current)
            current, image_count, total_bytes, text_bytes = [], 0, 0, 0
        current.append(number)
        image_count += count
        total_bytes += size
        text_bytes += text
    if current:
        groups.append(current)
    return groups


def assemble(groups):
    result = FileDraft(extraction_version='MATERIAL_V2', document_type='OTHER', summary='')
    references, kinds, summaries, all_kinds = {}, set(), [], set()
    for group in groups:
        if group.status != 'SUCCEEDED' or group.draft is None:
            raise IngestionError('DOCUMENT_INCOMPLETE', 'All page groups must finish before the file is complete.')
        draft = group.draft
        all_kinds.add(draft.document_type)
        if draft.records:
            kinds.add(draft.document_type)
        summaries.append(draft.summary)
        result.page_coverage.extend(draft.page_coverage)
        for info in draft.project_info:
            previous_info = next((p for p in result.project_info if info.project_ref is not None and p.project_ref == info.project_ref), None)
            if previous_info:
                for field in ('name', 'reference', 'location', 'managing_organisation', 'start_date', 'end_date'):
                    old, new = getattr(previous_info, field), getattr(info, field)
                    if old is None:
                        setattr(previous_info, field, new)
                    elif new is not None and old != new:
                        previous_info.issues.append(f'Project field {field} differs on another page: {old} / {new}. Verify source.')
                for field in ('assumptions', 'issues', 'inferred_fields'):
                    setattr(previous_info, field, list(dict.fromkeys([*getattr(previous_info, field), *getattr(info, field)])))
            elif info not in result.project_info:
                result.project_info.append(info.model_copy(deep=True))
        for ref in draft.project_refs:
            if ref not in result.project_refs:
                result.project_refs.append(ref.model_copy(deep=True))
        indices = []
        for local, row in enumerate(draft.records):
            ref = row.continues_from
            if ref:
                # Only explicit references to an earlier boundary record can merge.
                if ref not in references or ref.startswith(group.id + ':'):
                    raise IngestionError('PAGE_CONTINUATION_INVALID', 'A continuation did not reference an earlier saved group record.')
                index = references[ref]
                previous = result.records[index]
                if (previous.project_ref and row.project_ref and previous.project_ref != row.project_ref or
                        previous.material_ref and row.material_ref and previous.material_ref != row.material_ref or
                        previous.source_item_ref and row.source_item_ref and previous.source_item_ref != row.source_item_ref):
                    raise IngestionError('PAGE_CONTINUATION_INVALID', 'A continuation changed project, material identity or source item.')
                if previous.material_ref is None and previous.material_name != row.material_name:
                    raise IngestionError('PAGE_CONTINUATION_INVALID', 'An unmapped continuation has an ambiguous material identity.')
                merged = previous.model_copy(deep=True)
                merged.project_ref = previous.project_ref or row.project_ref
                merged.material_ref = previous.material_ref or row.material_ref
                merged.source_item_ref = previous.source_item_ref or row.source_item_ref
                quantity_conflicted = any('Conflicting cross-page quantity/unit observations' in issue for issue in previous.issues)
                if previous.quantity is None and row.quantity is not None and not quantity_conflicted:
                    merged.quantity_basis = row.quantity_basis
                for field in ('quantity', 'unit'):
                    old, new = getattr(merged, field), getattr(row, field)
                    if old is None and not quantity_conflicted:
                        setattr(merged, field, new)
                    elif new is not None and old != new:
                        merged.quantity = None
                        merged.quantity_basis = 'UNKNOWN'
                        merged.issues.append('Conflicting cross-page quantity/unit observations; verify the original. No quantities were added.')
                if quantity_conflicted:
                    merged.quantity, merged.quantity_basis = None, 'UNKNOWN'
                for key, value in row.specifications.items():
                    if key in merged.specifications and merged.specifications[key] != value:
                        merged.issues.append(f'Cross-page specification conflict for {key}: {merged.specifications[key]} / {value}')
                    else:
                        merged.specifications[key] = value
                for field in ('assumptions', 'issues', 'inferred_fields'):
                    setattr(merged, field, list(dict.fromkeys([*getattr(merged, field), *getattr(row, field)])))
                if row.evidence_basis == 'INFERRED':
                    merged.evidence_basis = 'INFERRED'
                    merged.inference_explanation = ' '.join(filter(None, [merged.inference_explanation, row.inference_explanation]))
                merged.raw_fields[f'continuation_page_{row.source_page}'] = json.dumps(row.model_dump(mode='json'), ensure_ascii=False)
                merged.additional_source_pages = sorted(set([*merged.additional_source_pages, *row.additional_source_pages, row.source_page]) - {None, merged.source_page})
                merged.continues_from = None
                result.records[index] = merged
            else:
                index = len(result.records)
                result.records.append(row.model_copy(deep=True))
            indices.append(index)
            references[f'{group.id}:{local}'] = index
        group.assembled_record_indices = indices
        for item in draft.source_items:
            saved = item.model_copy(deep=True)
            saved.record_indices = list(dict.fromkeys(indices[index] for index in item.record_indices))
            result.source_items.append(saved)
        result.assumptions.extend(draft.assumptions)
        result.issues.extend(draft.issues)
    kinds = kinds or all_kinds
    result.document_type = next(iter(kinds)) if len(kinds) == 1 else 'MIXED'
    result.summary = '\n'.join(dict.fromkeys(summaries))
    result.page_coverage = sorted(set(result.page_coverage))
    result.assumptions = list(dict.fromkeys(result.assumptions))
    result.issues = list(dict.fromkeys(result.issues))
    return result
