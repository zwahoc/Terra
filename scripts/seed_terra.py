import sys,json,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from terra.validation import load,validate,SEED
from terra.seeding import seed_local,verify
from terra.local_adapter import LocalDataConnect,AdapterError

def main():
    parser=argparse.ArgumentParser(description='Terra local emulator seed. Cloud endpoints are refused.')
    parser.add_argument('command',choices=['validate','seed','reset','verify'])
    parser.add_argument('--seed-file',type=Path,default=SEED)
    parser.add_argument('--dry-run',action='store_true',help='Offline validation only; performs no HTTP requests')
    parser.add_argument('--confirm',help='Destructive reset requires the exact demo project ID')
    args=parser.parse_args();seed=load(args.seed_file)
    if args.command=='validate' or args.dry_run:result=validate(seed)
    elif args.command=='verify':validate(seed);result=verify(LocalDataConnect(),seed)
    elif args.command=='reset':
        if args.confirm!='demo-terra-local':parser.error('reset requires --confirm demo-terra-local')
        result=seed_local(seed,reset_confirmation=args.confirm)
    else:result=seed_local(seed)
    print(json.dumps(result,indent=2))
if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,KeyError) as exc:print(f'Failed: {exc}',file=sys.stderr);sys.exit(1)
