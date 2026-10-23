"""Exact operational quantities; SQL stores integer millionths, never floats.

The canonical seed stays in normal units. Six decimal places and signed Int64
range are the explicit runtime storage boundary, not a document extraction cap.
"""
from decimal import Decimal, InvalidOperation

SCALE = 1_000_000
MAX_MICROS = 2**63 - 1
ENCODING = 'millionths-v1'
ALIASES = {'m³': 'm3', 'm^3': 'm3', 'm²': 'm2', 'm^2': 'm2',
           'pieces': 'pcs', 'piece': 'pcs', 'pc': 'pcs', 'bags': 'bag',
           'metres': 'm', 'meters': 'm', 'kilograms': 'kg', 'tonnes': 'tonne'}
DISCRETE = {'pcs', 'bag', 'sheet', 'roll', 'length'}
AMOUNT_KEYS = {'quantity', 'expectedQuantity', 'expectedUsedQuantity', 'expectedDispatchedQuantity','expectedReceivedQuantity', 'previousUsedQuantity', 'newUsedQuantity', 'committedQuantity',
               'declaredQuantity', 'confirmedQuantity', 'reservedActiveQuantity',
               'transferredOutQuantity', 'requiredQuantity', 'fulfilledQuantity',
               'proposedQuantity', 'approvedQuantity', 'reservedQuantity',
               'dispatchedQuantity', 'receivedQuantity', 'actuallyUsedQuantity', 'quantityAssessed'}
JSON_KEYS = {'payload', 'batchPayload', 'receipt', 'handoff', 'handoffPayload',
             'inputSnapshot', 'assumptions', 'specifications', 'parsedFields',
             'eventPayload', 'location', 'sourceInput', 'factorSnapshots'}

def unit(value):
    text = str(value).strip().lower()
    return ALIASES.get(text, text)

def amount(value, *, unit_name=None):
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError('Operational quantities require an integer or exact decimal string.')
    try: result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError('Invalid quantity.') from exc
    if not result.is_finite() or result < 0:
        raise ValueError('Quantity must be finite and nonnegative.')
    scaled = result * SCALE
    if scaled != scaled.to_integral_value() or scaled > MAX_MICROS:
        raise ValueError('Operational quantities support six decimal places within Int64 millionths range.')
    if unit_name and unit(unit_name) in DISCRETE and result != result.to_integral_value():
        raise ValueError(f'{unit_name} quantities must be whole counts.')
    return result

def text(value):
    d = Decimal(value)
    return format(d, 'f').rstrip('0').rstrip('.') if d != d.to_integral_value() else str(int(d))

def ordinary(value):
    d = Decimal(value)
    return int(d) if d == d.to_integral_value() else d

def wire(value, *, encode, scale=SCALE):
    """Transform typed scalar quantities, leaving JSON evidence untouched."""
    if isinstance(value, list): return [wire(v, encode=encode, scale=scale) for v in value]
    if not isinstance(value, dict): return value
    result = {}
    for key, item in value.items():
        if key in JSON_KEYS:
            result[key] = item
        elif key in AMOUNT_KEYS and item is not None:
            result[key] = str(int(amount(item) * scale)) if encode else ordinary(Decimal(str(item)) / scale)
        else:
            result[key] = wire(item, encode=encode, scale=scale)
    return result

def json_default(value):
    if isinstance(value, Decimal): return text(value)
    raise TypeError(f'Not JSON serialisable: {type(value).__name__}')
