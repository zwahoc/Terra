"""Read-only local benchmark of JSON -> mapper -> candidates/MAX_REUSE plan."""
import argparse
from datetime import date
import json
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.domain.allocator import allocate_max_reuse
from backend.app.domain.snapshot_mapping import map_record_collections
from terra.validation import load


COLLECTIONS = ('projects', 'materials', 'documents', 'extracted_rows', 'supply_offers',
               'demand_requests', 'optimisation_runs', 'allocation_proposals', 'transfers', 'route_distances')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.runs <= 100:
        parser.error('--runs must be between 1 and 100')
    durations = []
    for _ in range(args.runs):
        started = perf_counter()
        records = load()
        snapshot = map_record_collections(
            as_of_date=date.fromisoformat(records['metadata']['as_of_date']),
            **{name: records[name] for name in COLLECTIONS},
        )
        plan = allocate_max_reuse(snapshot)
        durations.append(perf_counter() - started)
    print(json.dumps({
        'python': platform.python_version(), 'platform': platform.platform(),
        'processor': platform.processor(), 'runs': args.runs,
        'supplies': len(snapshot.supplies), 'demands': len(snapshot.demands),
        'allocations': len(plan.allocations), 'total_proposed_quantity_pcs': plan.total_proposed_quantity,
        'min_seconds': min(durations), 'median_seconds': statistics.median(durations),
        'max_seconds': max(durations), 'baseline_target_seconds': 10,
        'within_target_in_this_run': max(durations) <= 10,
        'scope': 'Local JSON read, mapping, candidate generation and MAX_REUSE allocation only; no API/database/carbon',
    }, indent=2))


if __name__ == '__main__':
    main()
