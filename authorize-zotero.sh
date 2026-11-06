#!/bin/sh
set -eu
cd "$(dirname "$0")"
printf '%s\n' 'Zotero will ask whether Paper Inbox may update your library.' 'Choose Always Allow only if you want ongoing favorite/delete synchronization.'
python3 -B - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/"src"))
from zotero_bridge import authorize_local_writes
result = authorize_local_writes()
print(result.get('message', result['status']))
if result.get('status') == 'authorized' and not result.get('persistent'):
    print('Only one write was allowed. Run again and select Always Allow for ongoing sync.')
raise SystemExit(0 if result.get('status') == 'authorized' else 1)
PY
