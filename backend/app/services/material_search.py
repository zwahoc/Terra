"""Mechanical catalogue retrieval. The model, never this module, judges identity."""

import unicodedata

from backend.app.services.ingestion_errors import IngestionError


MATERIAL_SEARCH_FIELDS = ('id', 'canonical_name', 'reference_code', 'category', 'specifications', 'standard_unit')


def normalise_search_text(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def field_text(value):
    if value is None:
        return ''
    if isinstance(value, dict):
        return ' '.join(f'{key.replace("_", " ")} {field_text(item)}' for key, item in value.items())
    if isinstance(value, list):
        return ' '.join(field_text(item) for item in value)
    return str(value)


def flexible_material_page(read_page, *, terms, match_mode, search_fields, after='', limit=50):
    """Fill a match page, looking ahead one match to expose truthful continuation.

    read_page returns unfiltered ID-ordered repository pages, cached by the caller.
    There is no scan ceiling, relevance score, synonym generation or spec decision.
    """
    matches, cursor, scanned = [], after, 0
    while True:
        page = read_page(after=cursor, limit=100)
        records, following = page['records'], page['next_cursor']
        ids = [row['id'] for row in records]
        if (any(not isinstance(value, str) or value <= cursor for value in ids)
                or ids != sorted(set(ids))
                or following is not None and (not ids or following != ids[-1])):
            raise IngestionError('CONTEXT_INVALID', 'The material catalogue cursor did not advance in ID order.', 500)
        for row in records:
            scanned += 1
            texts = [normalise_search_text(field_text(row.get(field))) for field in search_fields]
            hits = [any(term in text for text in texts) for term in terms]
            matched = not terms or (any(hits) if match_mode == 'ANY' else all(hits))
            if matched:
                matches.append(row)
                if len(matches) > limit:
                    return _result(matches[:limit], matches[limit - 1]['id'], scanned,
                                   terms, match_mode, search_fields, after)
        if following is None:
            return _result(matches, None, scanned, terms, match_mode, search_fields, after)
        cursor = following


def _result(records, cursor, scanned, terms, mode, fields, after):
    return {'records': records, 'next_cursor': cursor, 'coverage': 'MATCH_PAGE',
            'search': {'terms': terms, 'match_mode': mode, 'fields': fields,
                       'after': after, 'complete': cursor is None, 'scanned_records': scanned,
                       'ordering': 'ID_ASCENDING_NO_RELEVANCE_RANKING',
                       'semantics': 'CASEFOLDED_SUBSTRING_PER_TERM; ANY_OR_ALL_ACROSS_FIELDS; NO_IDENTITY_JUDGEMENT'}}
