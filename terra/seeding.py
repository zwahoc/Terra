"""Validated local snapshot import and explicit reset, without event replay."""
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime
from filelock import FileLock, Timeout
from terra.validation import validate
from terra.local_adapter import LocalDataConnect,variables,equivalent

ROOT=Path(__file__).resolve().parents[1]

@contextmanager
def seed_lock():
    directory=ROOT/'.local';directory.mkdir(exist_ok=True)
    lock = FileLock(directory/'seed.lock', timeout=0)
    try:
        lock.acquire()
    except Timeout as exc:
        raise RuntimeError('Another local import/reset is active') from exc
    try:
        yield
    finally:
        lock.release()

def verify(adapter,seed):
    actual=adapter.snapshot()
    if not equivalent(actual,seed):raise ValueError('Read-back state differs from canonical baseline')
    expected=variables(seed)['demandCommitmentBalances']
    balances=adapter.execute('ListDemandCommitmentBalances')['demandCommitmentBalances']
    if balances!=expected:raise ValueError('Demand commitment balances differ from transfer histories')
    expected_heads=variables(seed)['impactAssessmentHeads']
    actual_heads=adapter.execute('ListImpactAssessmentHeads')['impactAssessmentHeads']
    for rows in (expected_heads,actual_heads):
        for row in rows:
            if row['updatedAt'] is not None:
                row['updatedAt']=datetime.fromisoformat(
                    row['updatedAt'].replace('Z','+00:00')).timestamp()
        rows.sort(key=lambda row:row['id'])
    if actual_heads!=expected_heads:raise ValueError('Impact assessment heads differ from baseline scopes')
    return {entity:len(rows) for entity,rows in actual.items()}

def seed_local(seed,adapter=None,reset_confirmation=None):
    validate(seed)
    adapter=adapter or LocalDataConnect()
    if reset_confirmation is not None and reset_confirmation!='demo-terra-local':
        raise ValueError('Reset requires --confirm demo-terra-local')
    with seed_lock():
        actual=adapter.snapshot()
        if reset_confirmation is not None:
            adapter.execute('ClearBaseline',write=True)
            if not adapter.execute('GetQuantityEncoding').get('quantityEncoding'):
                adapter.execute('InitializeExactQuantities',write=True)
            adapter.execute('ImportBaseline',variables(seed),write=True)
            action='reset and reseeded'
        elif equivalent(actual,seed):action='unchanged'
        elif any(actual.values()):raise ValueError('Local data differs from baseline. Refusing overwrite; use explicit reset only when intended.')
        else:
            if not adapter.execute('GetQuantityEncoding').get('quantityEncoding'):
                adapter.execute('InitializeExactQuantities',write=True)
            adapter.execute('ImportBaseline',variables(seed),write=True)
            action='seeded'
        counts=verify(adapter,seed)
    return {'action':action,'counts':counts}
