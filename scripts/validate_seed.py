import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from terra.validation import load,validate,SEED
if __name__=='__main__':
    try: print(json.dumps(validate(load(sys.argv[1] if len(sys.argv)>1 else SEED)),indent=2))
    except (ValueError,KeyError,TypeError) as exc:print(f'Validation failed: {exc}',file=sys.stderr);sys.exit(1)
