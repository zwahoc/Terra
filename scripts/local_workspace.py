"""Archive or explicitly cut over the local demo workspace, using REST only."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from terra.workspace_archive import archive_workspace,cutover_workspace,verify_archive
from terra.local_adapter import LocalDataConnect
from terra.validation import load

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('archive','verify-archive','cutover'))
    parser.add_argument('--host',default='127.0.0.1:9399')
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--label',default='Local workspace before reset')
    parser.add_argument('--confirm')
    args=parser.parse_args()
    if args.action=='archive':
        manifest,folder=archive_workspace(LocalDataConnect(args.host),label=args.label)
        result={'archive_id':manifest['id'],'path':str(folder),'verified':True,'batch_count':len(manifest['batches'])}
    else:
        if args.archive is None:parser.error('--archive is required')
        if args.action=='verify-archive':
            manifest=verify_archive(args.archive);result={'archive_id':manifest['id'],'verified':True}
        else:result=cutover_workspace(load(),args.archive,LocalDataConnect(args.host),confirmation=args.confirm)
    print(json.dumps(result,indent=2))
