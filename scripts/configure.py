"""Interactive local configuration. Never reads or asks for credentials."""
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def ask(label, default):
    answer = input(f'{label} [{default}]: ').strip()
    return answer or str(default)

def main():
    path = ROOT / 'sources.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    print('Paper Inbox 首次配置 / First-time setup\n直接回车保留默认值。不会索取密钥。')
    dependency = Path(ask('检索组件目录 / Retrieval runtime', previous.get('project', ROOT / 'vendor/zotero-arxiv-daily'))).expanduser().resolve()
    python = Path(ask('Python 路径 / Python executable', previous.get('retrieval_python', dependency / '.venv/bin/python'))).expanduser().resolve()
    zotero = Path(ask('Zotero 数据库 / Zotero database', previous.get('zotero_db', Path.home() / 'Zotero/zotero.sqlite'))).expanduser().resolve()
    reading = Path(ask('精读保存目录 / Reading folder', previous.get('reading_project', Path.home() / 'Documents/Paper Inbox Reading'))).expanduser().resolve()
    while True:
        try:
            count = int(ask('每日精选篇数 / Daily paper limit (1–50)', previous.get('daily_limit', 10)))
            if 1 <= count <= 50: break
        except ValueError: pass
        print('请输入 1–50 的整数。')
    language = ask('界面语言 / Language (zh-Hans/en)', previous.get('language','zh-Hans'))
    if language not in ('zh-Hans','en'): raise SystemExit('Unsupported language; use zh-Hans or en.')
    config = dict(previous)
    config.update(codex_binary=shutil.which('codex') or 'codex', project=str(dependency), retrieval_python=str(python), zotero_db=str(zotero),
                  reading_project=str(reading), reading_skill=str(ROOT/'skills/paper-explainer/SKILL.md'),
                  embedding_cache=str(ROOT/'cache/huggingface'), daily_limit=count, language=language)
    for key,value in {'arxiv_query':'cs.AI+cs.LG+q-bio.BM', 'biorxiv_query':'bioinformatics+biophysics',
                      'journal_group':'xx','lookback_days':1,'max_per_source':10,'schedule_utc_hour':22,
                      'schedule_utc_minute':0,'enabled_sources':['arXiv','bioRxiv','Journals']}.items():
        config.setdefault(key,value)
    reading.mkdir(parents=True,exist_ok=True)
    (ROOT/'cache').mkdir(exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    os.chmod(temporary,0o600)
    temporary.replace(path)
    print('已保存本机配置。来源、期刊和篇数可在应用设置中调整。\nLocal configuration saved; edit sources and counts in Settings.')

if __name__=='__main__': main()
