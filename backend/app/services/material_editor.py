"""Read-only material-editor assistance. Never save, approve or publish."""
from decimal import Decimal, localcontext

from backend.app.services.analysis_output import PLAIN_DECIMAL
from backend.app.services.ingestion_errors import IngestionError
from terra.quantities import amount, text, unit


def editor_preview(service, batch_id, command):
    batch = service.intake.get(batch_id)
    if batch.revision != command.expected_revision:
        raise IngestionError('DRAFT_REVISION_CONFLICT', 'The review changed. Reload before editing.', 409)
    value = command.current
    material = None
    if value.material_ref:
        if value.material_ref.kind == 'EXISTING':
            material = service.intake.reads.get_entity('materials', value.material_ref.id)
        elif batch.review:
            material = next((e.proposal.attributes for e in batch.review.entities
                             if e.proposal.kind == 'MATERIAL' and e.proposal.id == value.material_ref.id), None)
    standard = unit(material.get('standard_unit') or '') if material else ''
    effective_unit = unit(command.conversion.to_unit if command.conversion else value.unit or '')
    quantity = None
    questions = []
    if not material:
        questions.append('Resolve the catalogue material before using this quantity operationally.')
    if value.quantity is not None:
        if not PLAIN_DECIMAL.fullmatch(value.quantity):
            questions.append('Use a plain nonnegative decimal quantity.')
        else:
            with localcontext() as ctx:
                ctx.prec = max(1000, len(value.quantity) + len(command.conversion.factor if command.conversion else '') + 20)
                converted = Decimal(value.quantity)
                if command.conversion:
                    converted *= Decimal(command.conversion.factor)
                quantity = text(converted)
                try:
                    amount(quantity, unit_name=effective_unit)
                except ValueError as exc:
                    questions.append(str(exc))
    if standard and effective_unit != standard:
        questions.append('The document and catalogue units differ. Supply a product-specific conversion or keep supporting history only.')
    # Return readable exact observations, not stock heads/offers/transfers. The
    # save and publication paths still validate current targets and protection.
    predecessors = []
    if value.project_ref and value.material_ref and value.project_ref.kind == value.material_ref.kind == 'EXISTING':
        context = service.intake.reads.project_context(value.project_ref.id)['collections']
        superseded = {r['id'] for r in context.get('superseded_records', [])}
        documents = {r['id']: r for r in context.get('documents', [])}
        for collection in ('published_records', 'extracted_rows'):
            for prior in context.get(collection, []):
                fields = prior.get('parsed_fields', prior)
                if (prior['id'] in superseded or prior.get('superseded_by')
                        or fields.get('application') == 'HISTORY_ONLY'
                        or prior.get('review_status', 'ACCEPTED') not in ('ACCEPTED', 'CORRECTED')
                        or (prior.get('material_id') or prior.get('suggested_material_id')) != value.material_ref.id
                        or fields.get('record_kind') != value.record_kind
                        or unit(fields.get('unit') or '') != effective_unit):
                    continue
                source = prior.get('source') or {}
                document = documents.get(prior.get('document_id'), {})
                predecessors.append({'id': prior['id'], 'quantity': str(fields['quantity']) if fields.get('quantity') is not None else None,
                                     'unit': effective_unit, 'record_kind': value.record_kind,
                                     'effective_date': fields.get('effective_date'),
                                     'source': source.get('label') or document.get('filename') or document.get('title') or 'Stored project observation',
                                     'source_locator': fields.get('source_locator')})
    if batch.review and value.project_ref and value.material_ref:
        for sub in batch.review.submissions:
            for prior in sub.rows:
                if (prior.id != command.row_id and prior.decision == 'ACCEPTED'
                        and prior.current.application != 'HISTORY_ONLY'
                        and prior.current.project_ref == value.project_ref and prior.current.material_ref == value.material_ref
                        and prior.current.record_kind == value.record_kind
                        and unit(prior.conversion.to_unit if prior.conversion else prior.current.unit or '') == effective_unit):
                    with localcontext() as ctx:
                        ctx.prec = 1000
                        q = prior.current.quantity
                        if q is not None and prior.conversion:
                            q = text(Decimal(q) * Decimal(prior.conversion.factor))
                    predecessors.append({'id': prior.id, 'quantity': q, 'unit': effective_unit,
                                         'record_kind': value.record_kind, 'effective_date': str(prior.current.effective_date or '') or None,
                                         'source': sub.label, 'source_locator': prior.current.source_locator})
    return {'revision': batch.revision, 'quantity': quantity, 'unit': effective_unit,
            'catalogue_unit': standard, 'questions': questions, 'predecessors': predecessors,
            'operational_writes': False, 'approval_required': True}
