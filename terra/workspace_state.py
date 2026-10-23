"""Local source namespace is switched only by the explicit cutover tool."""
import json
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STATE_FILE=ROOT/'.local/workspace-state.json'

def current_source_root():
    explicit=os.environ.get('TERRA_INGESTION_DIR')
    if explicit:return Path(explicit).resolve()
    state=Path(os.environ.get('TERRA_WORKSPACE_STATE',str(STATE_FILE)))
    if state.is_file():return Path(json.loads(state.read_text(encoding='utf-8'))['source_root']).resolve()
    return ROOT/'.local/ingestion'
