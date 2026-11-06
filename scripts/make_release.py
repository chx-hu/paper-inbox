"""Build a source-only archive; never include runtime or personal data."""
from pathlib import Path
import sys
import zipfile

root = Path(__file__).resolve().parents[1]
out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root.parent / 'paper-inbox-source.zip'
files = [p for p in root.iterdir() if p.is_file() and (p.suffix in {'.py', '.swift', '.sh'} or p.name in {'.gitignore', 'LICENSE', 'NOTICE.md', 'README.md', 'prompt.md', 'config.example.json', 'sources.example.json'})]
for folder in ('src', 'tests', 'scripts', 'docs', 'skills', 'licenses'):
    files.extend(p for p in (root / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc', '.DS_Store'})
files.append(root / 'assets/make-icons.swift')
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(set(files)):
        data = path.read_bytes()
        if (b'/Users/' + Path.home().name.encode()) in data:
            raise SystemExit(f'Personal path detected in {path.relative_to(root)}')
        archive.write(path, 'paper-inbox/' + str(path.relative_to(root)))
print(f'{out}: {len(set(files))} source files')
