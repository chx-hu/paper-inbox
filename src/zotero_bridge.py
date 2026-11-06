"""Local Zotero Connector bridge. Never writes SQLite or requires cloud credentials.

save_paper accepts title,url,abstract,authors (names or creator dicts), published,
doi, pdf_url. Connector stores metadata; validated public PDF bytes are delivered
through its saveAttachment endpoint into Zotero's managed storage.
"""
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, unquote, urlencode
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError

DB = Path.home() / 'Zotero/zotero.sqlite'
BASE = 'http://127.0.0.1:23119'
COLLECTION = 'AI 文献收藏'
LOCK = threading.Lock()
SESSION_FILE = Path(__file__).resolve().parents[1] / 'cache' / 'zotero_sessions.json'
AUTH_FILE = SESSION_FILE.with_name('zotero_local_auth.json')
LOCAL = build_opener(ProxyHandler({}))


def _post(path, data, timeout=30, headers=None):
    payload = data if isinstance(data, bytes) else json.dumps(data).encode()
    h = {'Content-Type': 'application/json', 'X-Zotero-Connector-API-Version': '3',
         'X-Zotero-Version': '7.0'}
    h.update(headers or {})
    with LOCAL.open(Request(BASE + path, data=payload, headers=h), timeout=timeout) as r:
        raw = r.read()
        try: return json.loads(raw)
        except (ValueError, UnicodeDecodeError): return raw.decode('utf8', 'replace')


def _get(path):
    with LOCAL.open(Request(BASE + path, headers={'Zotero-API-Version':'3'}), timeout=15) as r:
        return json.load(r)


def _local_request(path, method='GET', data=None, headers=None, timeout=15):
    request_headers = {'Zotero-API-Version': '3'}
    request_headers.update(headers or {})
    payload = None
    if data is not None:
        payload = json.dumps(data).encode()
        request_headers['Content-Type'] = 'application/json'
    request = Request(BASE + path, data=payload, headers=request_headers, method=method)
    with LOCAL.open(request, timeout=timeout) as response:
        raw = response.read()
        try:
            result = json.loads(raw) if raw else None
        except (ValueError, UnicodeDecodeError):
            result = raw.decode('utf8', 'replace')
        return result, dict(response.headers.items())


def _server_id(headers):
    return next((value for key, value in headers.items()
                 if key.lower() == 'zotero-server-id'), None)


def authorize_local_writes():
    """Explicitly show Zotero's native access dialog. Never called by retries.

    Installed Zotero server_localAPI.js documents this endpoint. Persistent
    permission survives restart. One-time permission permits just one write.
    """
    with LOCK:
        try:
            _, headers = _local_request('/api/')
            server_id = _server_id(headers)
            if not server_id:
                return {'status': 'unsupported', 'message': '当前 Zotero 未提供本地写入授权接口，请更新 Zotero'}
            auth, _ = _local_request('/api/local/authorize', 'POST',
                                     {'appName': 'Paper Inbox'},
                                     {'Zotero-Server-ID': server_id}, timeout=300)
            if not auth or not auth.get('key'):
                return {'status': 'authorization_required', 'message': '尚未获得 Zotero 本地写入授权'}
            AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
            temp = AUTH_FILE.with_suffix('.tmp')
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, 'w') as handle:
                    json.dump({'server_id': server_id, 'key': auth['key']}, handle)
                temp.replace(AUTH_FILE)
            finally:
                temp.unlink(missing_ok=True)
            return {'status': 'authorized', 'persistent': bool(auth.get('remember')),
                    'message': 'Zotero 已授权本地分类同步'}
        except HTTPError as exc:
            return {'status': 'authorization_required' if exc.code in (401, 403) else 'pending',
                    'message': 'Zotero 本地授权尚未完成'}
        except Exception as exc:
            return {'status': 'pending', 'message': 'Zotero 本地授权待重试（%s）' % type(exc).__name__}


def remove_from_collection(paper):
    """Remove only AI collection membership using a versioned local API PATCH.

    Connector updateSession replaces all collections and cannot safely do this.
    No library item, attachment, tag, note, or other collection is deleted.
    Missing credentials stay pending until explicit native authorization.
    """
    return _change_collection(paper, False)


def add_to_collection(paper):
    """Restore AI membership without duplicating an existing library item."""
    return _change_collection(paper, True)


def _matches_paper(data, paper):
    supplied_doi = _doi(paper).casefold()
    actual_doi = _doi(data).casefold()
    if supplied_doi and actual_doi:
        return supplied_doi == actual_doi
    supplied_url = _canonical_url(paper.get('url'))
    actual_url = _canonical_url(data.get('url'))
    if supplied_url and actual_url and supplied_url == actual_url:
        return True
    if supplied_url.startswith('arxiv:') and actual_url.startswith('arxiv:'):
        return False
    title = str(paper.get('title', '')).strip().casefold()
    return bool(title and title == str(data.get('title', '')).strip().casefold())


def trash_paper(paper):
    """Move the verified personal-library item to Zotero trash, without purging."""
    return _change_deleted(paper, True)


def restore_paper(paper):
    """Restore the same saved item key. Collection synchronization is separate."""
    return _change_deleted(paper, False)


def _change_deleted(paper, deleted):
    with LOCK:
        try:
            return _set_deleted(paper, deleted)
        except HTTPError as exc:
            if exc.code == 404:
                return {'status': 'not_found', 'message': 'Zotero 中未找到此文献，保留原文献标识等待核实'}
            return {'status': 'authorization_required' if exc.code in (401, 403) else 'pending',
                    'message': 'Zotero 回收站状态待同步（HTTP %s）' % exc.code}
        except Exception as exc:
            return {'status': 'pending', 'message': 'Zotero 回收站状态待同步（%s）' % type(exc).__name__}


def _set_deleted(paper, deleted):
    key = paper.get('zotero_key')
    if not key:
        if not deleted:
            return {'status': 'not_found', 'message': '缺少原 Zotero 文献标识，等待核实后恢复'}
        existing = find_existing(paper)
        if not existing:
            return {'status': 'not_found', 'message': 'Zotero 中未找到此文献'}
        key = existing['key']
    if not isinstance(key, str) or not re.fullmatch(r'[A-Z0-9]{8}', key):
        return {'status': 'pending', 'message': 'Zotero 文献标识格式不正确，等待核实'}
    path = '/api/users/0/items/' + key
    success = {'status': 'trashed' if deleted else 'restored', 'key': key,
               'message': '已将此文献移入 Zotero 回收站' if deleted else '已从 Zotero 回收站恢复原文献'}
    for _ in range(3):
        row, headers = _local_request(path)
        if row.get('key') != key or not _matches_paper(row.get('data', {}), paper):
            return {'status': 'pending', 'key': key, 'message': 'Zotero 文献身份不一致，等待核实'}
        if bool(row['data'].get('deleted', False)) == deleted:
            return success
        server_id = _server_id(headers)
        if not server_id:
            return {'status': 'unsupported', 'key': key, 'message': '当前 Zotero 尚不支持安全的本地回收站同步'}
        try:
            auth = json.loads(AUTH_FILE.read_text())
        except (OSError, ValueError):
            auth = {}
        if auth.get('server_id') != server_id or not auth.get('key'):
            return {'status': 'authorization_required', 'key': key,
                    'message': '需在 Zotero 授权 Paper Inbox 本地写入后同步回收站状态'}
        try:
            _local_request(path, 'PATCH', {'version': row['version'], 'deleted': int(deleted)},
                           {'Zotero-API-Key': auth['key'], 'Zotero-Server-ID': server_id})
        except HTTPError as exc:
            if exc.code in (409, 412):
                continue
            raise
        verified, verify_headers = _local_request(path)
        if (_server_id(verify_headers) == server_id and verified.get('key') == key
                and _matches_paper(verified.get('data', {}), paper)
                and bool(verified['data'].get('deleted', False)) == deleted):
            return success
    return {'status': 'pending', 'key': key, 'message': 'Zotero 文献状态正在变化，稍后重新核实并同步'}


def _change_collection(paper, desired):
    with LOCK:
        try:
            return _set_collection_membership(paper, desired)
        except HTTPError as exc:
            status = 'authorization_required' if exc.code in (401, 403) else 'pending'
            return {'status': status, 'message': 'Zotero 收藏分类待同步（HTTP %s）' % exc.code}
        except Exception as exc:
            return {'status': 'pending', 'message': 'Zotero 收藏分类待同步（%s）' % type(exc).__name__}


def _set_collection_membership(paper, desired):
    existing = find_existing(paper)
    if not existing:
        if desired:
            return {'status': 'pending', 'message': 'Zotero 中未找到待恢复收藏的文献'}
        return {'status': 'not_member', 'message': 'Zotero 中未找到此文献，无需移除分类'}
    key = existing['key']
    if paper.get('zotero_key') and paper['zotero_key'] != key:
        return {'status': 'pending', 'key': key, 'message': 'Zotero 文献标识不一致，等待核实后移除分类'}
    if desired and existing.get('deleted'):
        return {'status': 'pending', 'key': key, 'message': '文献在 Zotero 回收站中，等待先恢复原文献'}
    rows = _get('/api/users/0/collections')
    collections = [row['key'] for row in rows if row.get('data', {}).get('name') == COLLECTION]
    if not collections:
        if desired:
            return {'status': 'pending', 'key': key, 'message': '请先创建 AI 文献收藏 分类'}
        return {'status': 'not_member', 'key': key, 'message': 'AI 文献收藏 分类不存在，无需移除'}
    if len(collections) != 1:
        return {'status': 'pending', 'key': key, 'message': '存在多个同名 AI 文献收藏 分类，等待核实'}
    collection_key = collections[0]
    path = '/api/users/0/items/' + key
    # Re-read after every version conflict so concurrent collection edits survive.
    for _ in range(3):
        row, headers = _local_request(path)
        current = row['data'].get('collections', [])
        if desired and collection_key in current:
            return {'status': 'saved', 'key': key, 'in_collection': True,
                    'message': '此文献已在 AI 文献收藏 中'}
        if not desired and collection_key not in current:
            return {'status': 'not_member', 'key': key, 'message': '此文献已不在 AI 文献收藏 中'}
        server_id = _server_id(headers)
        if not server_id:
            return {'status': 'unsupported', 'key': key, 'message': '当前 Zotero 尚不支持安全的本地分类移除，请更新 Zotero'}
        try:
            auth = json.loads(AUTH_FILE.read_text())
        except (OSError, ValueError):
            auth = {}
        if auth.get('server_id') != server_id or not auth.get('key'):
            return {'status': 'authorization_required', 'key': key,
                    'message': '收藏状态已记录，需在 Zotero 授权 Paper Inbox 本地写入后同步分类'}
        remaining = current + [collection_key] if desired else [value for value in current if value != collection_key]
        try:
            _local_request(path, 'PATCH', {'version': row['version'], 'collections': remaining},
                           {'Zotero-API-Key': auth['key'], 'Zotero-Server-ID': server_id})
        except HTTPError as exc:
            if exc.code in (409, 412):
                continue
            raise
        verified, verify_headers = _local_request(path)
        if (_server_id(verify_headers) == server_id
                and (collection_key in verified['data'].get('collections', [])) == desired):
            if desired:
                return {'status': 'saved', 'key': key, 'in_collection': True,
                        'message': '已加入 AI 文献收藏，原有分类已保留'}
            return {'status': 'removed', 'key': key,
                    'message': '已从 AI 文献收藏 移除，文献及其他分类已保留'}
    return {'status': 'pending', 'key': key, 'message': 'Zotero 分类正在变化，稍后重新核实并同步'}


def _collection():
    selected = _post('/connector/getSelectedCollection', {})
    target = next((x for x in selected.get('targets', []) if x.get('name') == COLLECTION and x['id'].startswith('C')), None)
    rows = _get('/api/users/0/collections?limit=100')
    row = next((x for x in rows if x.get('data',{}).get('name') == COLLECTION), None)
    if not target or not row: return None
    # Connector numeric IDs are internal; the local API uses stable collection keys.
    return {'collectionID':int(target['id'][1:]),'key':row['key'],'libraryID':1}


def _doi(paper):
    value = paper.get('doi') or paper.get('DOI') or ''
    if not value:
        url = paper.get('url', '')
        if 'doi.org/' in url: value = url.split('doi.org/', 1)[1]
        elif '/content/10.' in url: value = url.split('/content/', 1)[1]
    return re.sub(r'v\d+$', '', unquote(value).strip().removeprefix('https://doi.org/')).rstrip('/')


def _canonical_url(value):
    value = str(value or '').strip().rstrip('/')
    parts = urlsplit(value)
    if parts.hostname in ('arxiv.org', 'www.arxiv.org'):
        match = re.match(r'/(?:abs|pdf)/(.+)', parts.path)
        if match:
            return 'arxiv:' + re.sub(r'v\d+$', '', match.group(1).removesuffix('.pdf'))
    return value


def find_existing(paper):
    """Read running Zotero through its built-in local API, avoiding its DB lock."""
    key = paper.get('zotero_key')
    if key:
        if not isinstance(key, str) or not re.fullmatch(r'[A-Z0-9]{8}', key):
            raise ValueError('Invalid saved Zotero key')
        # Direct lookup includes trash, unlike items/top. Never fall back to a
        # new import when the original saved key is unavailable or mismatched.
        row = _get('/api/users/0/items/' + key)
        data = row.get('data', {})
        if row.get('key') != key or not _matches_paper(data, paper):
            raise ValueError('Saved Zotero item identity mismatch')
        children = _get('/api/users/0/items/' + key + '/children')
        return {'key': key, 'has_pdf': any(child.get('data', {}).get('contentType') == 'application/pdf'
                                         for child in children),
                'collections': data.get('collections', []), 'deleted': bool(data.get('deleted', False))}
    title = str(paper.get('title', '')).strip()
    doi = _doi(paper)
    url = str(paper.get('url', '')).strip()
    seen = set()
    for query in dict.fromkeys([doi, title, url, _canonical_url(url).removeprefix('arxiv:')]):
        if not query: continue
        rows = _get('/api/users/0/items/top?' + urlencode({'q':query,'qmode':'everything','limit':100}))
        for row in rows:
            d = row.get('data',{})
            if row['key'] in seen: continue
            seen.add(row['key'])
            match = ((doi and str(d.get('DOI','')).casefold() == doi.casefold())
                     or (title and str(d.get('title','')).strip().casefold() == title.casefold())
                     or (url and _canonical_url(d.get('url','')) == _canonical_url(url)))
            if match:
                children = _get('/api/users/0/items/' + row['key'] + '/children')
                return {'key':row['key'], 'has_pdf':any(x.get('data',{}).get('contentType') == 'application/pdf' for x in children),
                        'collections':d.get('collections',[])}
    return None


def probe():
    try:
        selected = _post('/connector/getSelectedCollection', {})
        col = _collection()
        return {'available': True, 'collection': COLLECTION, 'collection_ready': bool(col),
                'selected_library': selected.get('libraryName'),
                'personal_library_selected': bool(col and selected.get('libraryID') == col['libraryID']),
                'message': 'Zotero 已连接' if col else '请在本地 Zotero 创建 AI 文献收藏 分类'}
    except Exception as exc:
        return {'available': False, 'collection_ready': False,
                'message': 'Zotero 未连接，请启动 Zotero（%s）' % type(exc).__name__}


def _creators(authors):
    if isinstance(authors, str): authors = [s.strip() for s in authors.split(';') if s.strip()]
    out = []
    for a in authors or []:
        if isinstance(a, dict):
            name = a.get('name') or ''
            if a.get('lastName') or a.get('family'):
                out.append({'creatorType': 'author', 'firstName': a.get('firstName',a.get('given','')),
                            'lastName': a.get('lastName',a.get('family',''))})
            elif name: out.append({'creatorType':'author','lastName':name,'fieldMode':1})
        elif str(a).strip():
            # Preserve supplied order/name exactly; avoid guessing surname conventions.
            out.append({'creatorType':'author','lastName':str(a).strip(),'fieldMode':1})
    return out


def _pdf_url(paper):
    supplied = paper.get('pdf_url')
    url = paper.get('url', '')
    if not supplied and '/abs/' in url and urlsplit(url).hostname in ('arxiv.org','www.arxiv.org'):
        supplied = url.replace('/abs/','/pdf/')
    if not supplied and urlsplit(url).hostname in ('biorxiv.org','www.biorxiv.org'):
        supplied = url.rstrip('/') + '.full.pdf'
    if not supplied: return None
    parsed = urlsplit(supplied)
    # Restrict downloads to established paper repositories/publishers, never arbitrary local URLs.
    allowed = ('arxiv.org','biorxiv.org','medrxiv.org','pmc.ncbi.nlm.nih.gov',
               'europepmc.org','academic.oup.com','nature.com','science.org','cell.com',
               'journals.plos.org','elifesciences.org','pnas.org','link.springer.com',
               'onlinelibrary.wiley.com','pubs.acs.org','sciencedirect.com',
               'proceedings.mlr.press','jmlr.org','aclanthology.org','openreview.net',
               'static-content.springer-cdn.com','pmc.ncbi.nlm.nih.gov')
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or parsed.username or parsed.password or not any(host == h or host.endswith('.'+h) for h in allowed):
        return None
    return supplied


def _download_pdf(url):
    from urllib.request import build_opener, HTTPRedirectHandler
    class SafeRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not _pdf_url({'pdf_url':newurl}): raise ValueError('PDF redirect outside allowed repositories')
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    from fulltext import load_config
    proxy = load_config().get('network_proxy') or ''
    if proxy:
        parsed=urlsplit(proxy)
        if parsed.scheme not in ('http','https') or parsed.username or parsed.password: raise ValueError('Invalid configured proxy')
        opener=build_opener(ProxyHandler({'http':proxy,'https':proxy}),SafeRedirect())
    else:
        opener = build_opener(SafeRedirect())
    with opener.open(Request(url, headers={'User-Agent':'PaperInbox/0.1 scholarly personal library'}),timeout=45) as r:
        data = r.read(50 * 1024 * 1024 + 1)
    if len(data) > 50 * 1024 * 1024: raise ValueError('PDF exceeds 50 MB')
    if not data.lstrip().startswith(b'%PDF-'): raise ValueError('Source returned non-PDF content')
    return data


def _sessions():
    try: return json.loads(SESSION_FILE.read_text())
    except (OSError, ValueError): return {}


def _remember(key, session, connector_id):
    SESSION_FILE.parent.mkdir(parents=True,exist_ok=True)
    sessions = _sessions()
    sessions[key] = {'sessionID':session,'parentItemID':connector_id}
    temp = SESSION_FILE.with_suffix('.tmp')
    temp.write_text(json.dumps(sessions))
    os.chmod(temp,0o600)
    temp.replace(SESSION_FILE)


def _attach(paper, key, session, connector_id):
    pdf_url = _pdf_url(paper)
    if not pdf_url: return {'status':'saved','key':key,'has_pdf':False,'message':'已加入 AI 文献收藏；尚无可获取的开放 PDF'}
    try:
        pdf = _download_pdf(pdf_url)
        _post('/connector/saveAttachment',pdf,timeout=60,headers={
            'Content-Type':'application/pdf','X-Metadata':json.dumps({'sessionID':session,
            'parentItemID':connector_id,'title':'Full Text PDF','url':pdf_url})})
        verified = find_existing(paper)
        if not verified or not verified['has_pdf']: raise RuntimeError('Attachment not verified')
        return {'status':'saved','key':key,'has_pdf':True,'message':'题录与 PDF 已加入 AI 文献收藏'}
    except Exception as exc:
        return {'status':'saved','key':key,'has_pdf':False,'pdf_retryable':True,
                'message':'题录已入库；开放 PDF 未获取（%s），可重试；Zotero 重启后可能需手动补附件' % type(exc).__name__}


def save_paper(paper, on_submit=None, attach_pdf=True):
    with LOCK:
        try:
            return _save(paper, on_submit=on_submit, attach_pdf=attach_pdf)
        except Exception as exc:
            # Intentionally exclude HTTP bodies, user paths, and credential-like data.
            return {'status':'pending','message':'待同步：%s；启动 Zotero 后重试' % type(exc).__name__}


def _save(paper, on_submit=None, attach_pdf=True):
    if not paper.get('title') or not paper.get('url'):
        return {'status':'error','message':'题录缺少标题或来源链接'}
    existing = find_existing(paper)
    if existing:
        if existing.get('deleted'):
            return {'status': 'pending', 'key': existing['key'],
                    'message': '原文献在 Zotero 回收站中，等待恢复同一文献后继续同步'}
        col = _collection()
        member = bool(col and col['key'] in existing['collections'])
        session = _sessions().get(existing['key'])
        if attach_pdf and session and not existing['has_pdf'] and _pdf_url(paper):
            return _attach(paper, existing['key'], session['sessionID'], session['parentItemID'])
        return {'status':'existing','key':existing['key'],'has_pdf':existing['has_pdf'],
                'in_collection':member,'message':'Zotero 已有此文献，未重复导入' + ('' if member else '；原分类保持不变')}
    col = _collection()
    if not col: return {'status':'pending','message':'请先在本地 Zotero 创建“AI 文献收藏”分类'}
    selected = _post('/connector/getSelectedCollection', {})
    if selected.get('libraryID') != col['libraryID']:
        return {'status':'pending','message':'请在 Zotero 选中“我的文库”或“AI 文献收藏”，再重试收藏同步'}
    session = 'paper-inbox-' + uuid.uuid4().hex
    connector_id = uuid.uuid4().hex
    item = {'id':connector_id,'itemType':'journalArticle','title':paper['title'],
            'url':paper['url'],'abstractNote':paper.get('abstract',''),
            'creators':_creators(paper.get('authors',[])),'date':paper.get('published',''),
            'DOI':_doi(paper),'tags':[{'tag':'AI 文献收藏'}],'attachments':[]}
    if paper.get('journal'): item['publicationTitle'] = paper['journal']
    source_chat = str(paper.get('source_chat_url',''))
    chat_parts = urlsplit(source_chat)
    if chat_parts.scheme == 'https' and chat_parts.hostname == 'chatgpt.com' and not chat_parts.username and not chat_parts.password:
        item['extra'] = 'Source conversation: ' + source_chat.replace('\n','').replace('\r','')
    if on_submit is not None:
        on_submit({'sessionID': session, 'parentItemID': connector_id,
                   'collection_key': col['key'], 'collection_target': 'C' + str(col['collectionID'])})
    _post('/connector/saveItems', {'sessionID':session,'uri':paper['url'],'items':[item]},timeout=45)
    _post('/connector/updateSession', {'sessionID':session,'target':'C'+str(col['collectionID']),
                                       'tags':['AI 文献收藏']})
    found = None
    for _ in range(10):
        found = find_existing(paper)
        if found: break
        time.sleep(.2)
    if not found: return {'status':'pending','message':'Zotero 已接收题录，尚未确认入库，请稍后重试'}
    member = col['key'] in found['collections']
    if not member:
        return {'status':'metadata_saved','key':found['key'],'message':'题录已入库，但收藏分类尚未验证'}
    _remember(found['key'],session,connector_id)
    if attach_pdf:
        return _attach(paper,found['key'],session,connector_id)
    return {'status': 'saved', 'key': found['key'], 'has_pdf': found['has_pdf'],
            'in_collection': True, 'message': '题录、摘要与来源链接已加入 AI 文献收藏'}


if __name__ == '__main__':
    print(json.dumps(probe(),ensure_ascii=False))
