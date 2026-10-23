"""Evidence-linked draft recommendations. Never approve or publish anything."""
import re
from decimal import Decimal

from backend.app.schemas.review import Conversion
from terra.quantities import unit


def same(ref, other):
    return ref is not None and other is not None and (ref.kind, ref.id) == (other.kind, other.id)


def project_complete(attributes):
    return all(attributes.get(key) for key in ('name', 'code', 'township', 'managing_organisation'))


def material_complete(attributes):
    return all(attributes.get(key) for key in ('canonical_name', 'category_code', 'standard_unit'))


def prepare(service, batch):
    """Opt-in and idempotent for new untouched rows. Keep original model output."""
    review = batch.review
    review.prepared = True
    run = next((r for c in batch.comparisons for r in c.runs if r.id == review.run_id), None)
    files = {f.submission_id: f for f in run.files} if run else {}
    # Consolidate source-stated missing project facts, never a competing nonempty value.
    for entity in review.entities:
        if (entity.proposal.kind != 'PROJECT' or entity.confirmed or entity.edited_by_operator
                or entity.original and entity.original.attributes != entity.proposal.attributes):
            continue
        attributes = entity.proposal.attributes
        infos = [p.current for sub in review.submissions for p in sub.projects
                 if p.current.project_ref and p.current.project_ref.id == entity.proposal.id]
        for target, field in [('name', 'name'), ('code', 'reference'), ('township', 'location'),
                              ('managing_organisation', 'managing_organisation'),
                              ('start_date', 'start_date'), ('target_end_date', 'end_date')]:
            values = {str(value) for info in infos if (value := getattr(info, field))}
            if not attributes.get(target) and len(values) == 1:
                attributes[target] = values.pop()
    for sub in review.submissions:
        file = files.get(sub.id)
        findings = file.reconciliation.result.materials if file and file.reconciliation and file.reconciliation.result else []
        for index, row in enumerate(sub.rows):
            if row.preparation or row.edited_by_operator or row.decision != 'PENDING':
                continue
            value = row.current
            finding = next((f for f in findings if f.record_index == index), None)
            proposed = value.model_copy(deep=True)
            reasons, questions = [], []
            if proposed.application == 'UNDECIDED':
                if proposed.quantity is None and proposed.record_kind == 'UNKNOWN':
                    proposed.application = 'HISTORY_ONLY'
                    reasons.append('Technical or contextual evidence; no operational quantity is asserted.')
                elif finding:
                    proposed.application = finding.suggested_treatment
                    if proposed.application == 'UNDECIDED' and finding.relationship == 'NEW_INFORMATION':
                        proposed.application = 'ADD'
                    reasons.append(finding.explanation)
                    if finding.relationship in ('CONFLICT', 'POSSIBLE_DUPLICATE', 'POSSIBLE_REVISION'):
                        proposed.application = 'UNDECIDED'
                        questions.append('Choose how this potentially overlapping or conflicting observation should apply.')
                else:
                    questions.append('Choose whether this is separate evidence, a replacement or supporting history.')
            if proposed.application == 'REPLACE':
                targets = []
                for ref in finding.existing_records if finding else []:
                    if ref.collection not in ('published_records', 'extracted_rows'):
                        continue  # Stock heads, offers and transfers are not replaceable observations.
                    if not proposed.project_ref or proposed.project_ref.kind != 'EXISTING' or ref.project_id != proposed.project_ref.id:
                        continue
                    rows = service.intake.reads.project_context(ref.project_id)['collections'].get(ref.collection, [])
                    target = next((r for r in rows if r['id'] == ref.record_id), None)
                    if not target:
                        continue
                    material = target.get('material_id') or target.get('suggested_material_id')
                    fields = target.get('parsed_fields', target)
                    if (material == (proposed.material_ref.id if proposed.material_ref else None)
                            and fields.get('record_kind') == proposed.record_kind
                            and unit(fields.get('unit') or '') == unit(proposed.unit or '')):
                        targets.append(ref.record_id)
                proposed.replaces_record_ids = list(dict.fromkeys(targets))
                if not targets:
                    questions.append('No exact same-project/material/meaning/unit predecessor was verified. Select the prior observation.')
                elif len(targets) == 1:
                    reasons.append(f'Replaces observation {targets[0]}; its original evidence stays in history.')
            # These labels are model-retained source fields, not arithmetic guesses.
            column = proposed.raw_fields.get('quantity_column', '').strip().casefold()
            net = proposed.raw_fields.get('gap_basis', '').casefold()
            if column in ('outstanding gap', 'uncovered gap') and 'net' in net:
                proposed.record_kind = 'OUTSTANDING_DEMAND'
                reasons.append('The source identifies an uncovered gap already net of usable stock.')
            elif column == 'gross required' and proposed.record_kind == 'PLANNED_REQUIREMENT':
                proposed.record_kind = 'REMAINING_LOCAL_REQUIREMENT'
                reasons.append('The source describes gross need for unfinished work, before applying local stock.')
            if proposed.record_kind == 'OUTSTANDING_DEMAND' and not proposed.needed_from:
                window = proposed.raw_fields.get('receipt_window', '')
                match = re.search(r'\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s*[-–]\s*\d{1,2}\s+\w+\s+(\d{4})\b', window)
                if match:
                    from datetime import datetime
                    try:
                        proposed.needed_from = datetime.strptime(f'{match[1]} {match[2]} {match[3]}', '%d %B %Y').date()
                        reasons.append('Start date is taken from the source-stated receipt window.')
                    except ValueError:
                        questions.append('The stated receipt window has an invalid date. Confirm the needed-from date.')
            row.current = proposed
            row.preparation = {'version': 'prepared-review-v1', 'reasons': reasons,
                               'questions': questions, 'snapshot': proposed.model_dump(mode='json')}
    for sub in review.submissions:
        for row in sub.rows:
            if row.preparation and not row.edited_by_operator:
                prepare_material(service, review, row)
        for project in sub.projects:
            info = project.current
            if (not project.edited_by_operator and (not project.original or project.current == project.original)
                    and info.project_ref and info.project_ref.kind == 'EXISTING' and info.end_date and not project.master_updates):
                stored = service.intake.reads.get_entity('projects', info.project_ref.id) or {}
                old = stored.get('target_end_date')
                if old and str(info.end_date) != str(old):
                    project.master_updates['target_end_date'] = str(info.end_date)


def prepare_material(service, review, row):
    value = row.current
    ref = value.material_ref
    if not ref:
        return
    material = (next((e.proposal.attributes for e in review.entities if e.proposal.id == ref.id), None)
                if ref.kind == 'PROPOSED' else service.intake.reads.get_entity('materials', ref.id))
    if not material:
        return
    known = material.get('specifications', {})
    raw = value.raw_fields
    reference = (raw.get('product_reference') or raw.get('supplier_product_ref') or
                 value.specifications.get('product_reference') or value.specifications.get('supplier_product_ref'))
    # A shared explicit product code plus nonconflicting physical attributes permits
    # contextual wording to be standardised. Never copy dimensions/grades/classes.
    wording = {'type', 'pipe_type', 'use', 'application', 'packaging', 'supply_form', 'bar_type'}
    physical_conflicts = [key for key in value.specifications if key in known and key not in wording
                          and str(value.specifications[key]).strip().casefold() != str(known[key]).strip().casefold()]
    if reference and reference == material.get('reference_code') and not physical_conflicts:
        for key in wording:
            old, canonical = value.specifications.get(key), known.get(key)
            if old and canonical and old != canonical:
                # Truly incompatible product forms must remain questions, even when a code was reused.
                contradictory = any((word in old.casefold()) != (word in str(canonical).casefold())
                                    for word in ('pressure', 'potable', 'loadbearing', 'damaged', 'used',
                                                 'reinforced', 'unsealed', 'gravity', 'drainage'))
                if contradictory:
                    continue
                value.specifications[key] = str(canonical)
                row.preparation.setdefault('wording', []).append({'field':key, 'source':old, 'catalogue':canonical})
    if value.application != 'HISTORY_ONLY' and value.unit and unit(value.unit) != unit(material.get('standard_unit') or ''):
        # Only a same-product, explicitly stated pieces/area ratio is prepared.
        if unit(value.unit) == 'm2' and unit(material.get('standard_unit') or '') == 'pcs' and not row.conversion:
            factors = []
            for sub in review.submissions:
                for evidence in sub.rows:
                    if not same(value.material_ref, evidence.current.material_ref):
                        continue
                    for text in [*evidence.original.specifications.values(), *evidence.original.raw_fields.values()] if evidence.original else []:
                        match = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:pcs|pieces)\s*(?:per|/)\s*(?:1\s*)?m[²2]\b', text, re.I)
                        if match:
                            factors.append((match[1], evidence.id, text))
            unique = {Decimal(f[0]) for f in factors}
            if len(unique) == 1 and next(iter(unique)) > 0:
                factor, evidence_id, text = factors[0]
                row.conversion = Conversion(to_unit='pcs', factor=factor, basis=f'Documented product coverage: {text}', confirmed=False)
                row.preparation['conversion_evidence_row'] = evidence_id
    row.preparation['snapshot'] = value.model_dump(mode='json')


def candidate(batch):
    """Evaluate recommendations for reading, without recording human confirmation."""
    proposed = batch.model_copy(deep=True)
    review = proposed.review
    review.prepared = False
    for entity in review.entities:
        if not entity.confirmed:
            entity.confirmed = (project_complete(entity.proposal.attributes) if entity.proposal.kind == 'PROJECT'
                                else material_complete(entity.proposal.attributes))
    for sub in review.submissions:
        for project in sub.projects:
            if project.current.project_ref and (project.current.association_explanation or project.edited_by_operator):
                project.confirmed = True
        for row in sub.rows:
            if row.decision != 'EXCLUDED':
                row.decision, row.assumptions_confirmed = 'ACCEPTED', True
                row.release_confirmed = row.current.record_kind == 'CONFIRMED_SURPLUS'
                if row.conversion:
                    row.conversion.confirmed = True
    return proposed
