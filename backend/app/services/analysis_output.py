"""Recover presentation/number formatting and apply narrowly authorised output patches."""

import copy
import json
import math
import re
from decimal import Decimal, InvalidOperation

from backend.app.services.ingestion_errors import IngestionError


PLAIN_DECIMAL = re.compile(r'^[0-9]+(?:\.[0-9]+)?$')
GROUPED_DOT = re.compile(r'(?<!\d)\d{1,3}(?:,\d{3})+\.\d+(?!\d)')
GROUPED_COMMA = re.compile(r'(?<!\d)\d{1,3}(?:\.\d{3})+,\d+(?!\d)')


class AmbiguousJSON(ValueError):
    """Conflicting JSON values must not be resolved by a syntax-only repair."""


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise AmbiguousJSON('Duplicate JSON keys are ambiguous')
        result[key] = value
    return result


class _ObjectPairs(list):
    """Retain object members until duplicate values can be checked exactly."""


def _same_json(left, right):
    # Python equates True with 1; JSON types and exact numbers must agree.
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same_json(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    return left == right


def parse_object(text, *, recoveries=None):
    value = text.strip()
    fenced = re.fullmatch(r'```(?:json)?\s*\n([\s\S]*?)\n```', value, flags=re.IGNORECASE)
    if fenced:
        value = fenced[1].strip()
    def invalid_constant(_value):
        raise AmbiguousJSON('Nonfinite JSON is invalid')
    raw = json.loads(value, object_pairs_hook=_ObjectPairs, parse_float=Decimal, parse_constant=invalid_constant)
    events = []
    def members(node, path=''):
        if isinstance(node, _ObjectPairs):
            result = {}
            for key, child in node:
                location = path + pointer([key])
                child = members(child, location)
                if key in result:
                    if not _same_json(result[key], child):
                        raise AmbiguousJSON(f'Conflicting duplicate JSON key at {location}')
                    events.append({'action': 'REMOVED_IDENTICAL_DUPLICATE_KEY', 'path': location})
                else:
                    result[key] = child
            return result
        if isinstance(node, list):
            return [members(child, path + pointer([i])) for i, child in enumerate(node)]
        return node
    def numbers(node):
        if isinstance(node, dict):
            return {key: numbers(child) for key, child in node.items()}
        if isinstance(node, list):
            return [numbers(child) for child in node]
        if isinstance(node, Decimal):
            number = float(node)
            if not math.isfinite(number):
                raise AmbiguousJSON('Nonfinite JSON is invalid')
            return number
        return node
    # Check duplicates before float rounding could hide different source numbers.
    parsed = numbers(members(raw))
    if not isinstance(parsed, dict):
        raise ValueError('Expected exactly one JSON object')
    if recoveries is not None:
        recoveries.extend(events)
    return parsed, bool(fenced)


def recoverable_record_prefix(text):
    """Protect complete source records already present before a syntax defect."""
    match = re.search(r'"records"\s*:\s*\[', text)
    if match is None:
        return []
    decoder, rows, offset = json.JSONDecoder(object_pairs_hook=_pairs), [], match.end()
    while True:
        while offset < len(text) and text[offset].isspace():
            offset += 1
        if offset >= len(text) or text[offset] != '{':
            return rows
        try:
            row, offset = decoder.raw_decode(text, offset)
        except ValueError:
            return rows
        rows.append(row)
        while offset < len(text) and text[offset].isspace():
            offset += 1
        if offset >= len(text) or text[offset] != ',':
            return rows
        offset += 1


def normalise_quantities(candidate, evidence):
    """Only standardised quantity changes. Raw source strings remain byte-for-byte intact."""
    result, changes = copy.deepcopy(candidate), []
    dot_grouping = bool(GROUPED_DOT.search(evidence))
    comma_grouping = bool(GROUPED_COMMA.search(evidence))
    # Multiple ordinary fractional values also establish a document convention.
    dot_fraction = len(re.findall(r'(?<![\d,.])\d+\.\d{1,2}(?![\d,.])', evidence)) >= 2
    comma_fraction = len(re.findall(r'(?<![\d,.])\d+,\d{1,2}(?![\d,.])', evidence)) >= 2
    dot = (dot_grouping or dot_fraction) and not (comma_grouping or comma_fraction)
    comma = (comma_grouping or comma_fraction) and not (dot_grouping or dot_fraction)
    records = result.get('records', [])
    if not isinstance(records, list):
        return result, changes
    for index, row in enumerate(records):
        if not isinstance(row, dict) or not isinstance(row.get('quantity'), str):
            continue
        original = row['quantity']
        value = original.strip()
        if ',' in value or re.fullmatch(r'\d{1,3}(?:\.\d{3})+', value):
            if dot and re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', value):
                value = value.replace(',', '')
            elif comma and re.fullmatch(r'(?:\d{1,3}(?:\.\d{3})+|\d+),\d+', value):
                value = value.replace('.', '').replace(',', '.')
            elif comma and re.fullmatch(r'\d{1,3}(?:\.\d{3})+', value):
                value = value.replace('.', '')
            elif ',' in value:
                # Do not guess whether a lone comma groups thousands or decimals.
                if row.get('issues') is None:
                    row['issues'] = []
                if isinstance(row.get('issues', []), list):
                    row.setdefault('issues', []).append('Quantity punctuation is ambiguous; verify the original number convention before using this quantity.')
                    row['quantity'] = None
                    changes.append({'path':f'/records/{index}/quantity', 'before': original, 'after':None,
                                    'action':'AMBIGUOUS_NUMBER_REQUIRES_REVIEW'})
                continue
        try:
            # Exact numeric notation only; no unit/currency stripping or arithmetic.
            if not re.fullmatch(r'\+?\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?', value):
                continue
            number = Decimal(value)
            if not number.is_finite() or number < 0:
                continue
            if abs(number.adjusted()) > 1000:
                continue
            canonical = format(number, 'f')
        except (InvalidOperation, ValueError):
            continue
        if not PLAIN_DECIMAL.fullmatch(canonical):
            continue
        if original != canonical:
            row['quantity'] = canonical
            changes.append({'path':f'/records/{index}/quantity', 'before':original, 'after':canonical,
                            'action':'EXACT_NUMBER_FORMAT_NORMALISATION'})
    return result, changes


def pointer(location):
    return '/' + '/'.join(str(part).replace('~', '~0').replace('/', '~1') for part in location)


def apply_corrections(candidate, corrections, allowed_paths):
    result = copy.deepcopy(candidate)
    for correction in corrections.corrections:
        if correction.path not in allowed_paths or not correction.path.startswith('/'):
            raise IngestionError('REPAIR_SCOPE_INVALID', 'A repair attempted to change an unrelated field. The candidate was retained.')
        parts = [part.replace('~1', '/').replace('~0', '~') for part in correction.path[1:].split('/')]
        parent = result
        try:
            for part in parts[:-1]:
                parent = parent[int(part)] if isinstance(parent, list) else parent[part]
            key = parts[-1]
            if correction.op == 'REMOVE':
                if isinstance(parent, list):
                    raise ValueError('Removing source rows is not an authorised repair')
                parent.pop(key, None)
            else:
                def invalid_constant(_value):
                    raise ValueError('Nonfinite JSON')
                value = json.loads(correction.value_json, object_pairs_hook=_pairs, parse_constant=invalid_constant)
                if isinstance(parent, list):
                    if key == '-':
                        parent.append(value)
                    else:
                        parent[int(key)] = value
                else:
                    parent[key] = value
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise IngestionError('REPAIR_SCOPE_INVALID', 'The targeted correction could not be safely applied. The candidate was retained.') from exc
    return result
