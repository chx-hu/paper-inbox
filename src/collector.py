"""Local paper retrieval and interest ranking for Paper Inbox."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import socket
import sys
from app_settings import from_config, source_enabled, candidate_path, retrieval_fingerprint

BASE = Path(__file__).resolve().parents[1]


def read_corpus(db):
    # SQLite's read-only connection sees a consistent transaction, including WAL.
    with sqlite3.connect(Path(db).as_uri() + '?mode=ro', uri=True, timeout=10) as conn:
        rows = conn.execute('''
            SELECT i.key, i.dateAdded, v.value FROM items i
            JOIN itemTypes t USING(itemTypeID)
            JOIN libraries l USING(libraryID)
            JOIN itemData d USING(itemID) JOIN fields f USING(fieldID)
            JOIN itemDataValues v USING(valueID)
            WHERE l.type='user' AND t.typeName IN ('journalArticle','conferencePaper','preprint')
              AND f.fieldName='abstractNote' AND length(trim(v.value))>0
              AND NOT EXISTS (SELECT 1 FROM deletedItems x WHERE x.itemID=i.itemID)
        ''').fetchall()
    return [{'key': key, 'data': {'abstractNote': abstract,
             'dateAdded': added.replace(' ', 'T').removesuffix('Z') + 'Z'}}
            for key, added, abstract in rows]


def write_json(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def setup(config):
    project = Path(config['project'])
    sys.path.insert(0, str(project))
    os.environ['HF_HOME'] = config.get('embedding_cache', str(BASE / 'cache' / 'huggingface'))
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    socket.setdefaulttimeout(30)
    os.environ['SCHEDULE_UTC_HOUR'] = str(config['schedule_utc_hour'])
    os.environ['SCHEDULE_UTC_MINUTE'] = str(config['schedule_utc_minute'])
    return project


def run(config, args):
    settings = from_config(config)
    max_per_source = min(50, max(int(config.get('max_per_source', 10)), settings['daily_limit']))
    setup(config)
    corpus = read_corpus(config['zotero_db'])
    if not corpus:
        raise RuntimeError('No non-deleted Zotero articles with abstracts in local user library')
    if args.check:
        import biorxiv_demo, recommender, llm  # Verify existing runtime imports.
        print(json.dumps({'ready': True, 'corpus_count': len(corpus),
              'latest_item_added': max(p['data']['dateAdded'] for p in corpus),
              'zotero_db_mtime': datetime.fromtimestamp(Path(config['zotero_db']).stat().st_mtime).isoformat(),
              'arxiv': config['arxiv_query'], 'biorxiv': config['biorxiv_query'],
              'journals': config['journal_group'], 'delivery': 'Paper Inbox local database'}, ensure_ascii=False))
        return

    from schedule_window import get_scheduled_reference_utc, iso_target_dates_utc
    reference = get_scheduled_reference_utc()
    day = (reference + timedelta(hours=8)).date().isoformat()
    date_path = Path(*day.split('-'))
    cache_dir = BASE / 'cache' / 'runs' / date_path
    cache_dir.mkdir(parents=True, exist_ok=True)
    json_path = candidate_path(BASE / 'cache' / 'runs', day, config)
    if json_path.exists() and not args.force:
        print(json.dumps({'schedule_date_shanghai': day, 'cached': True,
                          'candidates': str(json_path)}, ensure_ascii=False))
        return

    from loguru import logger
    from biorxiv_demo import get_arxiv_paper, get_biorxiv_paper
    import biorxiv_demo
    import journal
    # Bound retry delays for unattended desktop runs.
    biorxiv_demo.BIORXIV_MAX_RETRIES = 2
    biorxiv_demo.BIORXIV_READ_TIMEOUT_SECONDS = 45
    journal.REQUEST_MAX_RETRIES = 1
    journal.REQUEST_READ_TIMEOUT_SECONDS = 30
    from recommender import rerank_paper
    warnings = []
    logger.add(lambda message: warnings.append(message.record['message']), level='WARNING')
    log_id = logger.add(cache_dir / 'run.log', level='INFO')
    def fetch_journals():
        def fetch_one(journal_config):
            with journal._build_session() as session:
                return journal._retrieve_journal_papers(session, journal_config,
                    config['lookback_days'], journal.DEFAULT_FETCH_PER_JOURNAL, False)
        papers, seen = [], set()
        with ThreadPoolExecutor(max_workers=4) as pool:
            for batch in pool.map(fetch_one, [item for item in journal.SUPPORTED_JOURNALS if item.key in settings['journals']]):
                for paper in batch:
                    if paper.paper_url.lower() not in seen:
                        seen.add(paper.paper_url.lower())
                        papers.append(paper)
        return sorted(papers, key=lambda paper: paper.published_at or '', reverse=True)
    sources = [
        ('arXiv', lambda: get_arxiv_paper(config['arxiv_query'])),
        ('bioRxiv', lambda: get_biorxiv_paper(config['biorxiv_query'])),
        ('期刊', fetch_journals)
    ]
    groups, source_status = [], {}
    # Fetch sources independently so one outage does not erase the other results.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [(name, pool.submit(fetch) if source_enabled(name, settings) else None) for name, fetch in sources]
        for name, future in futures:
            if future is None:
                groups.append([])
                source_status[name] = {'retrieved': 0, 'call_returned': False, 'enabled': False}
                continue
            try:
                found = future.result()
                groups.append(found)
                source_status[name] = {'retrieved': len(found), 'call_returned': True}
            except Exception as exc:
                groups.append([])
                source_status[name] = {'retrieved': 0, 'call_returned': False,
                                       'error_type': type(exc).__name__}
                warnings.append(f'{name} retrieval failed ({type(exc).__name__}); coverage incomplete.')

    try:
        groups = rerank_paper(*groups, corpus)
    except Exception as exc:
        warnings.append(f'Embedding ranking failed ({type(exc).__name__}); candidates retain source order, scores unavailable.')
    selected = []
    for (name, _), papers in zip(sources, groups):
        for paper in papers[:max_per_source]:
            url = (f'https://arxiv.org/abs/{paper.arxiv_id}' if name == 'arXiv' else paper.paper_url)
            item={'source': name, 'title': paper.title, 'url': url,
                  'abstract': paper.summary, 'score': paper.score}
            if name=='arXiv':
                item['authors']=[str(getattr(a,'name',a)) for a in paper.authors]
                published=getattr(getattr(paper,'_paper',None),'published',None)
                if published:item['published']=published.date().isoformat()
            if name == '期刊':
                item['journal'] = paper.journal
                item['journal_key'] = next((entry.key for entry in journal.SUPPORTED_JOURNALS if entry.name == paper.journal), '')
            selected.append(item)

    warnings = list(dict.fromkeys(warnings))
    result = {'schedule_date_shanghai': day, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'target_dates_utc': sorted(iso_target_dates_utc(config['lookback_days'])),
              'corpus_count': len(corpus), 'sources': source_status,
              'app_settings': settings, 'retrieval_fingerprint': retrieval_fingerprint(config),
              'status': 'partial' if warnings else 'complete', 'warnings': warnings, 'papers': selected}
    write_json(json_path, result)
    logger.remove(log_id)
    print(json.dumps({'status': result['status'], 'papers': len(selected),
                      'schedule_date_shanghai': day, 'candidates': str(json_path), 'warnings': len(warnings)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Offline configuration/runtime check; no API calls')
    parser.add_argument('--force', action='store_true', help='Replace an existing candidate snapshot for this schedule date')
    args = parser.parse_args()
    config = json.loads((BASE / 'sources.json').read_text())
    with (BASE / '.run.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('A local daily run is already in progress.')
            return
        run(config, args)


if __name__ == '__main__':
    main()
