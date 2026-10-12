import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from terra.seeding import verify
from terra.local_adapter import LocalDataConnect
from terra.validation import load
if __name__=='__main__':print(json.dumps(verify(LocalDataConnect(),load()),indent=2))
