#!/bin/sh
set -eu
cd "$(dirname "$0")"
ROOT=$(pwd)
if [ "$(uname -s)" != Darwin ]; then
  echo 'Paper Inbox currently requires macOS.'; exit 1
fi
if [ "${1:-}" = --no-install ]; then
  exec python3 scripts/configure.py
fi
for tool in git uv codex; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing $tool. See README.md installation prerequisites."; exit 1
  fi
done
if ! xcrun --find swiftc >/dev/null 2>&1; then
  echo 'Install Apple Command Line Tools first: xcode-select --install'; exit 1
fi
REVISION=812c19dbbf0cd3273b077d3629d6ca9692884cb8
DEPENDENCY="$ROOT/vendor/zotero-arxiv-daily"
if [ ! -d "$DEPENDENCY/.git" ]; then
  mkdir -p "$ROOT/vendor"
  git clone --no-checkout https://github.com/chx-hu/zotero-arxiv-daily.git "$DEPENDENCY"
  git -C "$DEPENDENCY" checkout --detach "$REVISION"
fi
if [ "$(git -C "$DEPENDENCY" rev-parse HEAD)" != "$REVISION" ]; then
  echo 'Dependency checkout differs from the tested version. Keep your changes; use a fresh source folder to install.'; exit 1
fi
uv sync --project "$DEPENDENCY" --python 3.11 --frozen
"$DEPENDENCY/.venv/bin/python" scripts/configure.py
sh doctor.sh --offline
sh build.sh
printf '\nSetup complete. Open: %s/Paper Inbox.app\n' "$ROOT"
printf 'Keep this source folder in place: the application uses its runtime files.\n'
