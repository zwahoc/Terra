"""Prepare a new local clone; never resets or exports an existing workspace."""
import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from terra.demo_workspace import build_demo, validate_demo, bootstrap_demo, ZONE, TEMPLATE, TEMPLATE_DATE
from terra.quantities import json_default


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['validate','seed','check-template','write-template'])
    parser.add_argument('--as-of',type=date.fromisoformat,help='Optional reproducible scenario date; default is today in Malaysia')
    parser.add_argument('--dry-run',action='store_true',help='Offline validation only, no database calls')
    args=parser.parse_args()
    if args.command in ('check-template','write-template'):
        value=json.dumps(build_demo(TEMPLATE_DATE),indent=2,ensure_ascii=False,default=json_default)+'\n'
        if args.command=='write-template':TEMPLATE.write_text(value,encoding='utf-8',newline='\n')
        elif TEMPLATE.read_text(encoding='utf-8')!=value:raise ValueError('Demo template differs from deterministic generator')
        print('Demo template matches');return
    if args.command=='validate' or args.dry_run:
        result=validate_demo(build_demo(args.as_of or datetime.now(ZONE).date()))
    else:result=bootstrap_demo(as_of=args.as_of)
    print(json.dumps(result,indent=2,default=json_default))

if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,KeyError) as exc:
        print(f'Failed: {exc}',file=sys.stderr);sys.exit(1)
