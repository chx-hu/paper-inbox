"""User-facing retrieval settings, stored alongside unchanged runtime config."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

SOURCES_FILE = Path(__file__).resolve().parents[1] / 'sources.json'
SOURCE_NAMES = ('arXiv', 'bioRxiv', 'Journals')
JOURNAL_CATALOG = (
    ('nature', 'Nature'),
    ('science', 'Science'),
    ('nature_biotechnology', 'Nature Biotechnology'),
    ('nature_methods', 'Nature Methods'),
    ('nature_chemical_biology', 'Nature Chemical Biology'),
    ('nature_structural_molecular_biology', 'Nature Structural & Molecular Biology'),
    ('nature_machine_intelligence', 'Nature Machine Intelligence'),
    ('nature_computational_science', 'Nature Computational Science'),
    ('science_advances', 'Science Advances'),
    ('cell_genomics', 'Cell Genomics'),
    ('neuron', 'Neuron'),
    ('ajhg', 'American Journal of Human Genetics'),
    ('trends_in_genetics', 'Trends in Genetics'),
    ('bioinformatics', 'Bioinformatics'),
    ('briefings_in_bioinformatics', 'Briefings in Bioinformatics'),
    ('nucleic_acids_research', 'Nucleic Acids Research'),
    ('genome_biology', 'Genome Biology'),
    ('genome_research', 'Genome Research'),
    ('genome_medicine', 'Genome Medicine'),
    ('nature_communications', 'Nature Communications'),
    ('nature_genetics', 'Nature Genetics'),
    ('genetics', 'GENETICS'),
    ('human_molecular_genetics', 'Human Molecular Genetics'),
    ('brain', 'Brain'),
    ('nature_neuroscience', 'Nature Neuroscience'),
    ('molecular_psychiatry', 'Molecular Psychiatry'),
    ('biological_psychiatry', 'Biological Psychiatry'),
    ('translational_psychiatry', 'Translational Psychiatry'),
)
JOURNAL_GROUPS = {'xx': ['nature',
        'science',
        'nature_biotechnology',
        'nature_methods',
        'nature_chemical_biology',
        'nature_structural_molecular_biology',
        'nature_machine_intelligence',
        'nature_computational_science',
        'science_advances',
        'bioinformatics',
        'briefings_in_bioinformatics',
        'nucleic_acids_research',
        'nature_communications'],
 'rr': ['nature',
        'science',
        'nature_methods',
        'science_advances',
        'cell_genomics',
        'neuron',
        'ajhg',
        'trends_in_genetics',
        'bioinformatics',
        'genome_biology',
        'genome_research',
        'genome_medicine',
        'nature_communications',
        'nature_genetics',
        'genetics',
        'human_molecular_genetics',
        'brain',
        'nature_neuroscience',
        'molecular_psychiatry',
        'biological_psychiatry',
        'translational_psychiatry'],
 'all': ['nature',
         'science',
         'nature_biotechnology',
         'nature_methods',
         'nature_chemical_biology',
         'nature_structural_molecular_biology',
         'nature_machine_intelligence',
         'nature_computational_science',
         'science_advances',
         'cell_genomics',
         'neuron',
         'ajhg',
         'trends_in_genetics',
         'bioinformatics',
         'briefings_in_bioinformatics',
         'nucleic_acids_research',
         'genome_biology',
         'genome_research',
         'genome_medicine',
         'nature_communications',
         'nature_genetics',
         'genetics',
         'human_molecular_genetics',
         'brain',
         'nature_neuroscience',
         'molecular_psychiatry',
         'biological_psychiatry',
         'translational_psychiatry']}
DEFAULTS = {'daily_limit': 10, 'arxiv_query': 'cs.AI+cs.LG+q-bio.BM',
            'biorxiv_query': 'bioinformatics+biophysics', 'journal_group': 'xx',
            'enabled_sources': list(SOURCE_NAMES), 'language': 'zh-Hans',
            'journals': list(JOURNAL_GROUPS['xx']), 'summary_provider':'codex',
            'summary_model':'gpt-5.4-mini','summary_effort':'none'}


def validate(value):
    required = set(DEFAULTS) - {'language', 'journals','summary_provider','summary_model','summary_effort'}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - set(DEFAULTS):
        raise ValueError('请提供完整的文献检索设置')
    limit = value['daily_limit']
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError('每日推荐数量应为1至50的整数')
    result = {'daily_limit': limit}
    for field in ('arxiv_query', 'biorxiv_query', 'journal_group'):
        text = value[field]
        maximum = 80 if field == 'journal_group' else 512
        if not isinstance(text, str) or not text.strip() or len(text) > maximum or any(ord(char) < 32 for char in text):
            raise ValueError('检索条件应为长度适当的单行文字')
        result[field] = text.strip()
    sources = value['enabled_sources']
    if (not isinstance(sources, list) or not sources
            or any(source not in SOURCE_NAMES for source in sources)
            or len(sources) != len(set(sources))):
        raise ValueError('至少启用一个有效文献来源')
    result['enabled_sources'] = list(sources)
    language = value.get('language', 'zh-Hans')
    if language not in ('zh-Hans', 'en'):
        raise ValueError('请选择中文或 English')
    result['language'] = language
    provider=value.get('summary_provider','codex')
    model=value.get('summary_model','gpt-5.4-mini')
    effort=value.get('summary_effort','none')
    models={'gpt-5.4-mini':('none','low','medium','high','xhigh'),
            'gpt-6-luna':('none','low','medium','high','xhigh','max'),
            'gpt-6.1-sol':('low','medium','high','xhigh','max'),
            'gpt-6-astra':('low','medium','high','xhigh','max')}
    if provider not in ('codex','openai') or model not in models or effort not in models[model]:
        raise ValueError('请选择有效的摘要模型与推理强度')
    result.update(summary_provider=provider,summary_model=model,summary_effort=effort)
    journals = value.get('journals', JOURNAL_GROUPS.get(result['journal_group'], JOURNAL_GROUPS['all']))
    known = {key for key, name in JOURNAL_CATALOG}
    if (not isinstance(journals, list) or any(not isinstance(key, str) or key not in known for key in journals)
            or len(journals) != len(set(journals)) or ('Journals' in sources and not journals)):
        raise ValueError('请选择有效期刊，启用期刊来源时至少选择一本')
    result['journals'] = [key for key, name in JOURNAL_CATALOG if key in journals]
    return result


def from_config(config):
    value = {field: config.get(field, default) for field, default in DEFAULTS.items() if field != 'journals'}
    if 'journals' in config:
        value['journals'] = [key for key in config['journals'] if key not in ('cell', 'cell_systems')]
    return validate(value)


def journal_options():
    return [{'id': key, 'name': name} for key, name in JOURNAL_CATALOG]


def load_config():
    try:
        config = json.loads(SOURCES_FILE.read_text(encoding='utf-8'))
        if not isinstance(config, dict):
            raise ValueError('configuration must be an object')
        return config
    except FileNotFoundError:
        # A clean checkout can display settings before local setup is complete.
        return json.loads(json.dumps(DEFAULTS))
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError('本机配置无法读取，请运行 sh setup.sh 重新完成设置。') from exc


def retrieval_python():
    value = load_config().get('retrieval_python')
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError('请先运行 sh setup.sh 完成本机环境配置，然后更新文献。')
    interpreter = Path(value).expanduser()
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise RuntimeError('检索环境不可用，请运行 sh setup.sh 修复后重试。')
    return str(interpreter)


def get_settings():
    return from_config(load_config())


def retrieval_fingerprint(config):
    relevant = _retrieval_settings(config)
    relevant.update(lookback_days=config.get('lookback_days', 1),
                    max_per_source=config.get('max_per_source', 10))
    return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()[:16]


def _retrieval_settings(config):
    return {key: value for key, value in from_config(config).items() if key not in ('language', 'journal_group','summary_provider','summary_model','summary_effort')}


def candidate_filename(config):
    # Preserve the existing default daily cache and keep other settings separate.
    if (_retrieval_settings(config) == _retrieval_settings(DEFAULTS) and config.get('lookback_days', 1) == 1
            and config.get('max_per_source', 10) == 10):
        return 'candidates-v2.json'
    return 'candidates-' + retrieval_fingerprint(config) + '.json'


def candidate_path(runs_directory, day, config):
    return Path(runs_directory) / Path(*day.split('-')) / candidate_filename(config)


def source_enabled(source, settings):
    name = {'期刊': 'Journals', 'journals': 'Journals'}.get(source, source)
    return name not in SOURCE_NAMES or name in settings['enabled_sources']


def save_settings(value):
    validate(value)
    supplied = dict(value)
    with SOURCES_FILE.with_suffix('.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = load_config()
        combined = dict(from_config(config), **supplied)
        if 'journals' not in supplied and supplied.get('journal_group') != config.get('journal_group', 'xx'):
            combined.pop('journals')
        value = validate(combined)
        config.update(value)
        fd, temporary = tempfile.mkstemp(prefix='.sources-', dir=SOURCES_FILE.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(config, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, SOURCES_FILE)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return value
