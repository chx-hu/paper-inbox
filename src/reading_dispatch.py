"""Durable favorite-to-Codex dispatch over the supported app-server stdio API.

New jobs use v4 while already-authorized v3 jobs remain available. Submission boundaries are persisted before
RPC writes. An uncertain submission is inspected, never automatically repeated.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import unquote

BASE = Path(__file__).resolve().parents[1]
QUEUE_DIR = BASE / 'cache' / 'codex_reading_v4'
LEGACY_QUEUE_DIR = BASE / 'cache' / 'codex_reading_v3'
INBOX_DB = BASE / 'cache' / 'inbox.sqlite'
def _runtime_config():
    try:
        return json.loads((BASE / 'sources.json').read_text())
    except (OSError, ValueError):
        return {}

PROJECT_DIR = Path(_runtime_config().get('reading_project', str(Path.home() / 'Documents/Paper Inbox Reading'))).expanduser()
PROJECT_ID = None
SKILL_PATH = _runtime_config().get('reading_skill', str(BASE / 'skills/paper-explainer/SKILL.md'))
DEFAULT_SETTINGS = {'model': 'gpt-6-astra', 'effort': 'high'}
MODEL_EFFORTS = {model: ('low', 'medium', 'high', 'xhigh', 'max', 'ultra')
                 for model in ('gpt-6-astra', 'gpt-6.1-sol')}
ACTIVE = {'creating', 'thread_created', 'submitting', 'running', 'needs_attention'}


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _identity(paper):
    doi = unquote(str(paper.get('doi') or paper.get('DOI') or '')).strip().lower()
    doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', doi).rstrip('/')
    if doi:
        return 'doi:' + doi
    url = str(paper.get('url') or '').strip().rstrip('/')
    arxiv = re.search(r'arxiv\.org/(?:abs|pdf)/([^/?]+)', url)
    if arxiv:
        return 'arxiv:' + re.sub(r'v\d+$', '', arxiv.group(1).removesuffix('.pdf'))
    if url:
        return 'url:' + url
    title = str(paper.get('title') or '').strip().casefold()
    if not title:
        raise ValueError('精读任务需要论文 DOI、链接或标题')
    return 'title:' + title


def job_id(paper):
    return hashlib.sha256(_identity(paper).encode()).hexdigest()[:24]


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.reading-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def validate_settings(value):
    if not isinstance(value, dict) or set(value) != {'model', 'effort'}:
        raise ValueError('请选择模型和推理强度')
    if value['model'] not in MODEL_EFFORTS or value['effort'] not in MODEL_EFFORTS[value['model']]:
        raise ValueError('不支持的模型或推理强度')
    return dict(value)


def get_settings():
    path = QUEUE_DIR / 'settings.json'
    if not path.exists():
        path = LEGACY_QUEUE_DIR / 'settings.json'
    try:
        return validate_settings(json.loads(path.read_text())) if path.exists() else dict(DEFAULT_SETTINGS)
    except (OSError, ValueError, TypeError):
        return dict(DEFAULT_SETTINGS)


def save_settings(value):
    value = validate_settings(value)
    _write(QUEUE_DIR / 'settings.json', value)
    return value


def build_prompt(paper):
    fields = ('id', 'title', 'doi', 'DOI', 'url', 'pdf_url', 'authors', 'published', 'abstract')
    data = {key: paper[key] for key in fields if paper.get(key) is not None}
    return (BASE / 'prompt.md').read_text().replace('{{skill_path}}', str(SKILL_PATH)).replace('{{paper_json}}', json.dumps(data, ensure_ascii=False, indent=2))



def completion_instructions(paper):
    receipt_path = PROJECT_DIR / '.paper-inbox' / (job_id(paper) + '.json')
    return ('Paper Inbox 后台完成信息：读完正文、Methods 和全部正文图及其 panel 后，将 JSON 单独写入 '
            + str(receipt_path) + '（按需创建目录），不要附在报告或最终答复中，报告以 Take-home message 结束。'
            '字段：full_text_read、all_main_panels_read 为实际完成布尔值；coverage 为正文图列表，'
            '每项含 figure、panels 标签列表、complete；method_name 为作者明确提出的方法原名或 null；'
            'method_evidence 为含 quote（包含名称的原文短引文）、locator、source_url 的对象或 null。'
            '正文阅读完成即可，仅在理解正文主要发现确有需要时查阅对应 SI、附录或 Extended Data 内容，不要求完整覆盖补充材料。'
            '另写 motivation 和 take_home_message 两个简短字符串，前者用1至2句说明研究动机，后者用2至3句概括主要发现，仅保留理解结论必需的条件。'
            '摘要字段仅写纯文本句子，不使用 Markdown 加粗、标题、列表或代码围栏。'
            '同时提供 motivation_zh、motivation_en、take_home_message_zh、take_home_message_en 四个字符串，中英内容对应；原字段保留中文。每种语言分别遵守上述句数限制，须来自实际全文阅读并与报告一致。'
            '无命名方法时不编造名称。派发器负责改名和 Zotero 入库，不自行操作这两项或 Codex 数据库。')


def _response(job):
    fields = ('status', 'message', 'thread_id', 'method_name', 'method_evidence', 'model', 'effort', 'zotero_status', 'zotero_message', 'zotero_key', 'motivation', 'take_home_message', 'motivation_zh', 'motivation_en', 'take_home_message_zh', 'take_home_message_en')
    result = {key: job.get(key) for key in fields}
    if job.get('status') == 'completed' and (not result['motivation'] or not result['take_home_message']):
        try:
            fallback = _report_summaries(Path(job['report_path']).read_text(encoding='utf-8'))
        except (KeyError, OSError, UnicodeError):
            fallback = {}
        for field in ('motivation', 'take_home_message'):
            result[field] = result[field] or fallback.get(field, '')
    result['thread_url'] = 'codex://threads/' + job['thread_id'] if job.get('thread_id') else None
    return result


def reading_for(paper):
    for directory in (QUEUE_DIR, LEGACY_QUEUE_DIR):
        path = directory / (job_id(paper) + '.json')
        if path.exists():
            return _response(json.loads(path.read_text()))
    return None


def enqueue(paper, settings=None):
    settings = validate_settings(settings or get_settings())
    legacy = LEGACY_QUEUE_DIR / (job_id(paper) + '.json')
    if legacy.exists():
        return _response(json.loads(legacy.read_text()))
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    path = QUEUE_DIR / (job_id(paper) + '.json')
    with (QUEUE_DIR / '.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not path.exists() or json.loads(path.read_text()).get('status') == 'not_requested':
            previous = json.loads(path.read_text()) if path.exists() else {}
            _write(path, {**previous, 'schema_version': 4, 'id': job_id(paper), 'identity': _identity(paper),
                          'paper': paper, 'prompt': build_prompt(paper), **settings,
                          'receipt_path': str(PROJECT_DIR / '.paper-inbox' / (job_id(paper) + '.json')),
                          'completion_instructions': completion_instructions(paper),
                          'status': 'pending', 'message': '已排队，等待 Codex 逐图精读',
                          'project_path': str(PROJECT_DIR), 'project_id': PROJECT_ID,
                          'created_at': _now(), 'updated_at': _now(), 'thread_id': None})
        return _response(json.loads(path.read_text()))


def _update(path, **fields):
    with (path.parent / '.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        job = json.loads(path.read_text())
        job.update(fields, updated_at=_now())
        _write(path, job)
        return job


def set_favorite(paper, desired, settings, revision):
    if desired:
        enqueue(paper, settings)
    path = next((directory / (job_id(paper) + '.json') for directory in (QUEUE_DIR, LEGACY_QUEUE_DIR)
                 if (directory / (job_id(paper) + '.json')).exists()), None)
    if path is None:
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        path = QUEUE_DIR / (job_id(paper) + '.json')
        with (path.parent / '.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not path.exists():
                _write(path, {'id': job_id(paper), 'paper': paper, 'status': 'not_requested',
                              'thread_id': None, 'created_at': _now()})
    with (path.parent / '.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        job = json.loads(path.read_text())
        if revision >= job.get('favorite_revision', -1):
            job.update(desired_favorite=bool(desired), favorite_revision=revision,
                       zotero_next_retry=0, updated_at=_now())
            if desired and job.get('zotero_status') in ('removed', 'not_member', 'existing_elsewhere', 'trashed', 'not_found'):
                job['zotero_status'] = 'pending'
            _write(path, job)
    return _response(job)


def _desired_favorite(job):
    # The transactional inbox intent is authoritative, including toggles that
    # arrived while a Zotero request was already in flight.
    if INBOX_DB.exists():
        connection = sqlite3.connect('file:' + str(INBOX_DB) + '?mode=ro', uri=True, timeout=20)
        try:
            row = connection.execute('SELECT desired FROM reading_requests_v3 WHERE paper_id=?',
                                     (job['paper'].get('id'),)).fetchone()
            if row is not None:
                return bool(row[0])
            row = connection.execute('SELECT favorite FROM papers WHERE id=?',
                                     (job['paper'].get('id'),)).fetchone()
            if row is not None:
                return bool(row[0])
        finally:
            connection.close()
    return job.get('desired_favorite', True)


class AppServer:
    """One JSON-RPC connection with asynchronous notifications and bounded reads."""
    def __init__(self, log_path):
        self.log = log_path.open('a')
        cli = _runtime_config().get('codex_binary') or shutil.which('codex') or 'codex'
        self.proc = subprocess.Popen([cli, 'app-server', '--stdio'], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self.log, text=True, bufsize=1)
        self.incoming = queue.Queue()
        self.serial = 0
        self.events = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.proc.stdout:
                try:
                    self.incoming.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            self.incoming.put(None)

    def send(self, value):
        self.proc.stdin.write(json.dumps(value) + '\n')
        self.proc.stdin.flush()

    def receive(self, timeout=60):
        message = self.incoming.get(timeout=timeout)
        if message is None:
            raise ConnectionError('Codex app-server 已断开')
        if 'method' in message and 'id' in message:
            # Approval and user-input requests belong to the user in Codex.
            # Never approve tool execution or answer a user question here.
            self.events.append({'method': 'reading/needsAttention', 'params': {'method': message['method']}})
            self.send({'id': message['id'], 'error': {'code': -32000, 'message': 'Please continue this request in the Codex app.'}})
        return message

    def rpc(self, method, params, timeout=60):
        self.serial += 1
        request_id = self.serial
        self.send({'id': request_id, 'method': method, 'params': params})
        deadline = time.monotonic() + timeout
        while True:
            message = self.receive(max(0.01, deadline - time.monotonic()))
            if message.get('id') == request_id and 'method' not in message:
                if 'error' in message:
                    raise RuntimeError('Codex RPC ' + method + ' 失败 ' + json.dumps(message['error'], ensure_ascii=False)[:300])
                return message.get('result', {})
            if message.get('method') == 'reading/needsAttention':
                self.events.append(message)

    def initialize(self):
        self.rpc('initialize', {'clientInfo': {'name': 'paper_inbox', 'version': '3.0'}})
        self.send({'method': 'initialized', 'params': {}})

    def close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc.stdout.close()
        self.log.close()


def _receipt(text):
    matches = re.findall(r'```reading_receipt\s*\n(.*?)\n```', text, re.S)
    if len(matches) != 1:
        return None
    try:
        result = json.loads(matches[0])
    except (ValueError, TypeError):
        return None
    if not isinstance(result, dict):
        return None
    if result.get('full_text_read') is not True or result.get('all_main_panels_read') is not True:
        return None
    if not isinstance(result.get('coverage'), list) or not result['coverage']:
        return None
    if any(not isinstance(item, dict) or not item.get('figure') or not item.get('panels') or item.get('complete') is not True for item in result['coverage']):
        return None
    return result


def _summary_text(value, sentence_limit, truncate=False):
    if not isinstance(value, str) or '```' in value:
        return ''
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', value)
    text = re.sub(r'(?m)^\s*[-*+]\s+', '', text)
    text = re.sub(r'[*`]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if not text or any(key in text for key in ('full_text_read', 'all_main_panels_read', 'reading_receipt')):
        return ''
    sentences = re.split(r'(?<=[。！？!?])\s*|(?<=[.])\s+(?=[A-Z])', text)
    sentences = [sentence for sentence in sentences if sentence]
    if truncate:
        text = ' '.join(sentences[:sentence_limit])
    elif len(sentences) > sentence_limit:
        return ''
    return text if len(text) <= 1000 else ''


def _report_summaries(report):
    # Remove complete and unfinished fences before looking for visible headings.
    report = re.sub(r'(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?(?:^\s*\1\s*$|\Z)', '', report)
    headings = list(re.finditer(r'(?m)^\s{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$', report))
    aliases = {'motivation': ('motivation', '研究动机'),
               'take_home_message': ('take-home message', 'take home message', '核心结论')}
    summaries = {}
    for index, heading in enumerate(headings):
        label = re.sub(r'^\d+[.、)）]\s*', '', heading.group(2)).strip(' *_:：').casefold()
        field = next((key for key, names in aliases.items() if label in names), None)
        if field is None or field in summaries:
            continue
        end = next((other.start() for other in headings[index + 1:]
                    if len(other.group(1)) <= len(heading.group(1))), len(report))
        section = report[heading.end():end]
        # Child heading labels are navigation, not summary prose.
        section = re.sub(r'(?m)^\s{0,3}#{1,6}[ \t]+.*$', '', section)
        summaries[field] = _summary_text(section, 2 if field == 'motivation' else 3, truncate=True)
    return summaries


def _finish(client, path, turn):
    if turn.get('status') != 'completed':
        _update(path, status='failed', message='Codex 精读未完成，请打开原任务继续', turn_status=turn.get('status'))
        return
    texts = [item.get('text', '') for item in turn.get('items', []) if item.get('type') == 'agentMessage' and item.get('phase') != 'commentary']
    report = '\n\n'.join(texts)
    if not report.strip():
        _update(path, status='needs_attention', message='任务结束，尚未读取到完整报告，请打开原任务检查')
        return
    report_path = QUEUE_DIR / (path.stem + '.md')
    report_path.write_text(report, encoding='utf-8')
    job_before = json.loads(path.read_text())
    if job_before.get('receipt_path'):
        try:
            receipt_file = Path(job_before['receipt_path'])
            raw_receipt = receipt_file.read_text(encoding='utf-8') if receipt_file.stat().st_size <= 100000 else ''
            receipt = _receipt('```reading_receipt\n' + raw_receipt + '\n```')
        except (OSError, UnicodeError):
            receipt = None
    else:
        # Existing submitted jobs still use the previous inline receipt format.
        receipt = _receipt(report)
    if not receipt:
        _update(path, status='incomplete', message='已有阅读结果，全文或逐图覆盖尚未确认', report_path=str(report_path))
        return
    summaries = _report_summaries(report)
    for field, limit in (('motivation', 2), ('take_home_message', 3)):
        summaries[field] = _summary_text(receipt.get(field), limit) or summaries.get(field, '')
    for field, limit in (('motivation', 2), ('take_home_message', 3)):
        for language in ('zh', 'en'):
            key = field + '_' + language
            summaries[key] = _summary_text(receipt.get(key), limit) or None
        summaries[field] = summaries[field + '_zh'] or summaries.get(field, '')
    job = _update(path, **summaries, status='completed', message='正文与正文图精读已完成', report_path=str(report_path), reading_receipt=receipt,
                  zotero_status='pending', zotero_message='精读已完成，等待保存到 AI 文献收藏')
    method = receipt.get('method_name')
    evidence = receipt.get('method_evidence')
    if not isinstance(method, str) or not method.strip() or len(method) > 120:
        return
    if not isinstance(evidence, dict) or not all(isinstance(evidence.get(key), str) and evidence[key].strip() for key in ('quote', 'locator', 'source_url')):
        return
    if method.casefold() not in evidence['quote'].casefold() or not evidence['source_url'].startswith(('https://', 'http://')):
        return
    # Persist the supported name first so a failed rename can be retried safely.
    _update(path, method_name=method.strip(), method_evidence=evidence, rename_pending=True)
    client.rpc('thread/name/set', {'threadId': job['thread_id'], 'name': method.strip()})
    _update(path, rename_pending=False)


def _run_one(path, client):
    created_here = False
    job = json.loads(path.read_text())
    if job.get('rename_pending') and job.get('thread_id'):
        client.rpc('thread/name/set', {'threadId': job['thread_id'], 'name': job['method_name']})
        _update(path, rename_pending=False)
        return
    if job['status'] not in ACTIVE and job['status'] != 'pending':
        return
    if job['status'] == 'creating':
        _update(path, status='submission_unknown', message='创建回执不确定，已停止自动重试以避免重复任务')
        return
    if job['status'] == 'pending':
        if not PROJECT_DIR.is_dir():
            raise RuntimeError('精读项目目录尚未就绪')
        _update(path, status='creating', message='正在创建 Codex 精读任务')
        result = client.rpc('thread/start', {'cwd': str(PROJECT_DIR), 'model': job['model'],
                                           'ephemeral': False, 'sandbox': 'workspace-write',
                                           'approvalPolicy': 'on-request',
                                           'config': {'model_reasoning_effort': job['effort']},
                                           'developerInstructions': job.get('completion_instructions')})
        created_here = True
        thread_id = result['thread']['id']
        job = _update(path, status='thread_created', thread_id=thread_id, message='已创建 Codex 任务')
    if job['status'] == 'thread_created':
        if not created_here:
            try:
                client.rpc('thread/resume', {'threadId': job['thread_id']})
            except RuntimeError as exc:
                if 'no rollout found' in str(exc).lower():
                    _update(path, status='submission_unknown', message='原空任务未形成持久记录，已保留回执等待人工检查；不会自动重复创建')
                    return
                raise
        _update(path, status='submitting', message='正在提交全文逐图精读')
        result = client.rpc('turn/start', {'threadId': job['thread_id'], 'model': job['model'], 'effort': job['effort'],
                                          'input': [{'type': 'text', 'text': job['prompt']},
                                                    {'type': 'skill', 'name': 'paper-explainer', 'path': SKILL_PATH}]})
        job = _update(path, status='running', turn_id=result['turn']['id'], message='Codex 正在阅读全文并逐图精读')
        try:
            client.rpc('thread/name/set', {'threadId': job['thread_id'], 'name': '精读 · ' + str(job['paper'].get('title', '论文'))[:150]})
        except RuntimeError as exc:
            _update(path, initial_name_error=str(exc)[:300])
    if not job.get('thread_id'):
        return
    # Read only existing history after restart. Never send a second turn/start.
    thread = client.rpc('thread/read', {'threadId': job['thread_id'], 'includeTurns': True})['thread']
    _update(path, last_polled_at=_now(), runtime_thread_status=thread.get('status', {}).get('type'))
    turns = thread.get('turns', [])
    target = next((turn for turn in turns if turn.get('id') == job.get('turn_id')), None)
    if target is None and job['status'] == 'submitting' and turns:
        target = turns[-1]
        job = _update(path, turn_id=target['id'], status='running')
    if target and target.get('status') != 'inProgress':
        _finish(client, path, target)
    elif job['status'] == 'submitting' and not turns:
        _update(path, status='submission_unknown', message='提交回执不确定，请检查原任务；不会重复提交')
    elif target and thread.get('status', {}).get('type') in ('notLoaded', 'idle', 'systemError'):
        _update(path, status='needs_attention', message='原任务尚未完成，执行连接已停止，请在 Codex 中继续')


def _zotero_due(job):
    if time.time() < job.get('zotero_next_retry', 0):
        return False
    if not _desired_favorite(job):
        return job.get('zotero_status') not in ('trashed', 'not_found')
    receipt = job.get('reading_receipt') or {}
    verified = (receipt.get('full_text_read') is True and receipt.get('all_main_panels_read') is True
                and bool(receipt.get('coverage'))
                and all(item.get('complete') is True for item in receipt['coverage']))
    return (job.get('status') == 'completed' and verified
            and job.get('zotero_status') not in ('saved', 'existing', 'existing_elsewhere')
            and time.time() >= job.get('zotero_next_retry', 0))


def _sync_zotero(path):
    """Reconcile saved, restored, or trashed items against durable favorite intent."""
    import zotero_bridge as zotero
    job = json.loads(path.read_text())
    if not _zotero_due(job):
        return
    if not _desired_favorite(job):
        _trash_zotero(path, job, zotero)
        return
    # PDF retrieval remains optional. This step commits metadata, abstract and URL.
    paper = dict(job['paper'])
    paper.pop('pdf_url', None)
    # Prevent the helper from deriving an implicit PDF URL for this metadata save.
    def submitted(receipt):
        if not _desired_favorite(json.loads(path.read_text())):
            raise RuntimeError('收藏已取消，停止新的 Zotero 提交')
        _update(path, zotero_submission=receipt, zotero_status='saving',
                zotero_message='正在保存精读论文题录')
    try:
        submission = job.get('zotero_submission')
        if job.get('zotero_key'):
            known_paper = dict(paper, zotero_key=job['zotero_key'])
            result = zotero.restore_paper(known_paper)
            if result.get('status') == 'restored':
                if _desired_favorite(json.loads(path.read_text())):
                    result = zotero.add_to_collection(known_paper)
                else:
                    _trash_zotero(path, json.loads(path.read_text()), zotero)
                    return
        elif submission:
            existing = zotero.find_existing(paper)
            if not existing:
                _update(path, zotero_status='submission_unknown', zotero_next_retry=time.time() + 60,
                        zotero_message='Zotero 提交回执待核实，保留原提交并等待确认，避免重复条目',
                        message='精读完成，Zotero 入库回执待核实')
                return
            if submission['collection_key'] not in existing.get('collections', []):
                result = zotero.add_to_collection(dict(paper, zotero_key=existing['key']))
            else:
                result = {'status': 'saved', 'key': existing['key'], 'in_collection': True,
                          'message': '精读论文已保存到 AI 文献收藏'}
        else:
            result = zotero.save_paper(paper, on_submit=submitted, attach_pdf=False)
        if result.get('key'):
            _update(path, zotero_key=result['key'], zotero_submission_resolved=True)
        latest = json.loads(path.read_text())
        if not _desired_favorite(latest):
            _trash_zotero(path, latest, zotero)
            return
        if result.get('status') == 'existing' and not result.get('in_collection'):
            result = zotero.add_to_collection(dict(paper, zotero_key=result.get('key')))
        status = result.get('status', 'pending')
        retry_delay = 60
        if status == 'pending' and not job.get('zotero_launch_attempted'):
            availability = zotero.probe()
            if not availability.get('available'):
                _update(path, zotero_launch_attempted=True, zotero_launch_requested_at=_now())
                try:
                    launch = subprocess.run(['open', '-g', '-a', 'Zotero'],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                    if launch.returncode == 0:
                        result['message'] = '已请求后台启动 Zotero，连接后自动保存精读论文'
                        retry_delay = 5
                except (OSError, subprocess.TimeoutExpired):
                    pass
        if status == 'existing' and not result.get('in_collection'):
            status = 'existing_elsewhere'
        success = status in ('saved', 'existing', 'added', 'already_member')
        _update(path, zotero_status='saved' if success else status, zotero_key=result.get('key') or job.get('zotero_key'),
                zotero_message=result.get('message', '等待 Zotero 确认'),
                zotero_next_retry=0 if success else time.time() + retry_delay,
                message='精读完成，已保存至 AI 文献收藏' if success else '精读完成，' + result.get('message', '等待 Zotero 确认'))
        latest = json.loads(path.read_text())
        if not _desired_favorite(latest):
            _trash_zotero(path, latest, zotero)
    except Exception as exc:
        _update(path, zotero_status='pending', zotero_next_retry=time.time() + 60,
                zotero_message='Zotero 未连接或保存待确认，启动 Zotero 后自动重试（' + type(exc).__name__ + '）',
                message='精读完成，等待 Zotero 保存；将自动重试')


def _trash_zotero(path, job, zotero):
    paper = dict(job['paper'], zotero_key=job.get('zotero_key'))
    result = zotero.trash_paper(paper)
    status = result.get('status', 'pending')
    if status == 'not_found' and job.get('zotero_submission') and not job.get('zotero_submission_resolved'):
        status = 'trash_pending'
        result['message'] = '取消收藏已记录，原提交仍待核实，继续检查并将可能延迟出现的文献移至回收站'
    success = status in ('trashed', 'not_found')
    _update(path, zotero_status=status, zotero_key=result.get('key') or job.get('zotero_key'),
            zotero_message=result.get('message', 'Zotero 回收站操作待同步'),
            zotero_next_retry=0 if success else time.time() + 60)


def _eligible(job):
    return (job['status'] == 'pending' or job['status'] in ACTIVE
            or job.get('rename_pending') or _zotero_due(job))


def _worker():
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    with (QUEUE_DIR / '.worker.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        client = None
        try:
            while True:
                paths = [path for path in QUEUE_DIR.glob('*.json') if path.stem != 'settings']
                pending = [path for path in paths if _eligible(json.loads(path.read_text()))]
                if not pending:
                    return
                for path in pending:
                    try:
                        job = json.loads(path.read_text())
                        if _zotero_due(job):
                            _sync_zotero(path)
                        if job['status'] == 'pending' or job['status'] in ACTIVE or job.get('rename_pending'):
                            if client is None:
                                client = AppServer(QUEUE_DIR / 'app-server.log')
                                client.initialize()
                            _run_one(path, client)
                    except (ConnectionError, EOFError, queue.Empty) as exc:
                        # A broken connection requires reopening the app-server.
                        # Preserve the durable submission boundary for reconciliation.
                        _update(path, message='精读连接待检查 ' + type(exc).__name__, last_error=str(exc)[:400])
                        return
                    except Exception as exc:
                        job = json.loads(path.read_text())
                        # A paper-specific error must not close other running turns.
                        # Completed reading remains available for Zotero synchronization.
                        completed = job.get('status') == 'completed'
                        _update(path, status='completed' if completed else 'failed', rename_pending=False,
                                message='精读已完成，后续处理异常，请查看原任务' if completed else '精读处理异常，请打开原任务检查',
                                last_error=str(exc)[:400])
                if client is None:
                    continue
                # Notifications keep the submitted turns alive on this connection.
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        # Poll authoritative turn history in the next guarded pass.
                        # Notifications may omit items needed to verify the report.
                        client.receive(timeout=max(.01, deadline - time.monotonic()))
                    except queue.Empty:
                        break
                if any(event.get('method') == 'reading/needsAttention' for event in client.events):
                    for path in pending:
                        job = json.loads(path.read_text())
                        if job['status'] == 'running':
                            _update(path, status='needs_attention', message='Codex 请求人工处理，请打开原任务继续')
                    client.events.clear()
        finally:
            if client:
                client.close()


def _process_queue(directory, legacy=False):
    directory.mkdir(parents=True, exist_ok=True)
    paths = [p for p in directory.glob('*.json') if p.stem != 'settings']
    eligible = any(_eligible(json.loads(p.read_text())) for p in paths)
    if not eligible:
        return {'status': 'idle'}
    with (directory / '.worker.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'running'}
    with (directory / 'worker.log').open('a') as log:
        subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--worker'] + (['--legacy'] if legacy else []),
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, cwd=BASE)
    return {'status': 'dispatching'}


def process_pending():
    """Run new jobs independently while draining already-authorized v3 jobs."""
    if LEGACY_QUEUE_DIR.exists() and LEGACY_QUEUE_DIR != QUEUE_DIR:
        _process_queue(LEGACY_QUEUE_DIR, legacy=True)
    return _process_queue(QUEUE_DIR)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--legacy', action='store_true')
    parser.add_argument('--process-pending', action='store_true')
    args = parser.parse_args()
    if args.worker:
        if args.legacy:
            QUEUE_DIR = LEGACY_QUEUE_DIR
        _worker()
    elif args.process_pending:
        print(json.dumps(process_pending(), ensure_ascii=False))
