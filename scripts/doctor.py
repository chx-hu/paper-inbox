"""Read-only preflight; --offline avoids networking, model downloads and login changes."""
import argparse
import importlib.util
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline',action='store_true')
    parser.parse_args()
    problems=[]
    def check(ok,label,hint=''):
        print(('OK  ' if ok else 'FIX ') + label + (': '+hint if not ok else ''))
        if not ok:problems.append(label)
    config=ROOT/'sources.json'
    check(config.is_file(),'Local configuration','Run ./setup.sh first')
    if not config.is_file():return 1
    try:d=json.loads(config.read_text())
    except ValueError:print('FIX Invalid sources.json');return 1
    for tool in ['codex','git','swiftc','pdftoppm']:
        check(bool(shutil.which(tool)),tool,'Install prerequisites from README')
    python=Path(d.get('retrieval_python',''))
    check(python.is_file(),'Retrieval Python','Run ./setup.sh')
    if python.is_file():
        code="import importlib.util,json,sys; print(json.dumps({'python_ok':sys.version_info>=(3,11),'missing':[m for m in ['torch','sentence_transformers','arxiv','aiohttp','yaml','tqdm'] if importlib.util.find_spec(m) is None]}))"
        try:
            result=subprocess.run([str(python),'-c',code],capture_output=True,text=True,timeout=20,check=True)
            info=json.loads(result.stdout)
            check(info['python_ok'] and not info['missing'],'Python 3.11+ dependencies',str(info['missing']))
        except Exception:check(False,'Retrieval environment','Re-run setup; inspect its installation errors')
    project=Path(d.get('project',''))
    check(all((project/(m+'.py')).is_file() for m in ['biorxiv_demo','journal','recommender','schedule_window']), 'Retrieval source','Run ./setup.sh')
    db=Path(d.get('zotero_db','')).expanduser()
    check(db.is_file(),'Zotero library','Start Zotero or correct its database path in sources.json')
    if db.is_file():
        try:
            with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as connection:
                n=connection.execute("SELECT count(*) FROM itemData d JOIN fields f USING(fieldID) JOIN itemDataValues v USING(valueID) WHERE f.fieldName='abstractNote' AND length(trim(v.value))>0").fetchone()[0]
            check(n>0,'Abstracts for interest ranking','Import papers with abstracts into Zotero')
        except sqlite3.Error:check(False,'Zotero read access','Check macOS Files and Folders permission')
    check(Path(d.get('reading_skill','')).is_file(),'Reading skill','Keep bundled skills/ directory')
    print('Codex: run `codex login status`; use `codex login` if needed. No API key is requested here.')
    print('首次检索需联网下载嵌入模型；本检查不下载模型，也不创建任务。')
    return 1 if problems else 0
if __name__=='__main__':raise SystemExit(main())
