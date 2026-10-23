"""Evidence-coverage guards. Never infer quantities, stock meaning or approval here."""

import re
from collections import Counter

from backend.app.services.ingestion_errors import IngestionError


ITEM_REFERENCE = re.compile(r"^\s*([A-Z]{1,4}[-.]?\d{2,4})\s+", re.MULTILINE)


def numbered_table_references(text: str) -> list[str]:
    """Optional audit for explicitly numbered tables, not a required upload template.

    Headers plus multiple consistent references avoid treating arbitrary dates,
    document codes or one standalone project ID as material-item requirements.
    Unnumbered/image-only pages use model page acknowledgement instead.
    """
    header = text.upper()
    if not (all(word in header for word in ("ITEM", "DESCRIPTION")) or
            all(word in header for word in ("REF", "MATERIAL", "QTY")) or
            all(word in header for word in ("REF", "MATERIAL", "UNIT", "CLOSE", "LOCAL NEED"))):
        return []
    references = list(dict.fromkeys(ITEM_REFERENCE.findall(text)))
    return references if len(references) >= 3 else []


def validate_pdf_coverage(draft, references_by_page, page_numbers, project_pages=None):
    covered = set(draft.page_coverage)
    problems, details = [], {}
    if covered != set(page_numbers):
        problems.append('The model did not acknowledge every supplied PDF page.')
        details.update(expected_pages=page_numbers, acknowledged_pages=sorted(covered))
    missing = []
    material_v2 = draft.extraction_version == 'MATERIAL_V2'
    entries = draft.source_items if material_v2 else draft.records
    entry_keys = [(entry.source_page, entry.source_item_ref) for entry in entries]
    if material_v2 and len(set(entry_keys)) != len(entry_keys):
        problems.append('Source-item accounting contains duplicate entries.')
        details['duplicate_source_items'] = [{'page': page, 'item_reference': ref}
            for (page, ref), count in Counter(entry_keys).items() if count > 1]
    for page, references in references_by_page.items():
        actual = {record.source_item_ref for record in entries if record.source_page == int(page)}
        missing.extend({"page": page, "item_reference": ref} for ref in references if ref not in actual)
    unknown_pages = sorted((({r.source_page for r in [*draft.records, *entries] if r.source_page is not None} |
                            {p for row in draft.records for p in row.additional_source_pages}) - set(page_numbers)) |
                           ({info.source_page for info in draft.project_info if info.source_page is not None} - set(project_pages or page_numbers)))
    if material_v2:
        ledger_keys = set(entry_keys)
        missing.extend({'page': row.source_page, 'item_reference': row.source_item_ref}
                       for row in draft.records if row.source_item_ref is not None
                       and (row.source_page, row.source_item_ref) not in ledger_keys)
    missing = list({(item['page'], item['item_reference']): item for item in missing}.values())
    if missing or unknown_pages:
        problems.append(f'The extraction omitted {len(missing)} source items or referenced invalid pages.')
        details.update(missing_source_items=missing, invalid_source_pages=unknown_pages)
    if problems:
        error = IngestionError("DOCUMENT_COVERAGE_INCOMPLETE", ' '.join(problems) + ' The candidate cannot be marked complete.')
        error.details = details
        raise error
    return {"page_count": len(page_numbers), "acknowledged_pages": sorted(covered),
            "numbered_source_items": sum(len(refs) for refs in references_by_page.values()),
            "numbered_items_accounted_for": True,
            "scope": "PAGE_AND_NUMBERED_ITEM_COVERAGE_NOT_SEMANTIC_VERIFICATION"}
