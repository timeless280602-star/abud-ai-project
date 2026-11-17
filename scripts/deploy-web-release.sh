#!/usr/bin/env bash
# Run from the production checkout with the reviewed release commit as argument.
set -euo pipefail

release="${1:?Provide the reviewed release commit SHA}"
compose=(docker compose -f compose.yaml)
voice=false
case "${2:-}" in
  --voice) voice=true ;;
  "") ;;
  *) echo "Usage: deploy-web-release.sh RELEASE_SHA [--voice]" >&2; exit 1 ;;
esac
cd /opt/abud

branch="$(git branch --show-current)"
if [[ -z "$branch" ]]; then
  echo "The production checkout is detached. Inspect git status -sb before deploying." >&2
  exit 1
fi
printf 'Production checkout branch: %s\n' "$branch"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Tracked files have local changes. Review them before deploying." >&2
  exit 1
fi
if [[ ! -r .env ]]; then
  echo "Production .env is missing or unreadable." >&2
  exit 1
fi
git merge-base --is-ancestor HEAD "$release" || {
  echo "The release does not include the current production checkout." >&2
  exit 1
}

api_container="$(docker compose -f compose.yaml ps --status running -q abud-api)"
if [[ -z "$api_container" ]]; then
  echo "No running abud-api found in this Compose project." >&2
  exit 1
fi

if [[ "$(docker inspect --format '{{.Name}}' "$api_container")" != /abud-api ]]; then
  echo "The running API container does not match production abud-api." >&2
  exit 1
fi

umask 077
stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
backup_dir="/opt/abud/backups/web-release-$stamp"
mkdir -p "$backup_dir"
git rev-parse HEAD > "$backup_dir/previous-commit.txt"
docker inspect --format '{{.Image}}' "$api_container" > "$backup_dir/previous-image-id.txt"
docker inspect --format '{{.Config.Image}}' "$api_container" > "$backup_dir/previous-image-ref.txt"
previous_image="abud-api:before-$stamp"
docker image tag "$(cat "$backup_dir/previous-image-id.txt")" "$previous_image"
printf '%s\n' "$previous_image" > "$backup_dir/previous-image-tag.txt"

# Build the new API before stopping the running container.
git merge --ff-only "$release"
if "$voice"; then
  compose+=(-f compose.voice.yaml)
fi
"${compose[@]}" config --quiet
if "$voice"; then
  "${compose[@]}" up -d --build abud-voice ollama
  model="$("${compose[@]}" config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["abud-api"]["environment"]["ABUD_VOICE_OLLAMA_MODEL"])')"
  "${compose[@]}" exec -T ollama ollama pull "$model"
  ready=false
  for attempt in {1..90}; do
    if "${compose[@]}" exec -T abud-voice python -c \
      'from urllib.request import urlopen; assert urlopen("http://127.0.0.1:8001/health", timeout=2).status == 200'       >/dev/null 2>&1; then
      ready=true
      break
    fi
    sleep 2
  done
  if ! "$ready"; then
    echo "Voice worker did not become ready. The running API was left in place." >&2
    exit 1
  fi
fi
"${compose[@]}" build abud-api
if "$voice"; then
  printf 'Warming the local voice model…\n'
  "${compose[@]}" run --rm --no-deps -T abud-api python -c \
    'import asyncio; from app.web_voice import warmup; asyncio.run(warmup())'
fi

# SQLite's backup API gives a consistent snapshot even with WAL and live writers.
docker exec -i "$api_container" python - > "$backup_dir/abud_memory.db.partial" <<'PYTHON'
import os
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

source = Path(os.environ["ABUD_DATABASE_PATH"]).resolve()
with tempfile.TemporaryDirectory() as directory:
    target = Path(directory) / "backup.db"
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as live:
        with closing(sqlite3.connect(target)) as snapshot:
            live.backup(snapshot)
    with target.open("rb") as file:
        shutil.copyfileobj(file, sys.stdout.buffer)
PYTHON
mv "$backup_dir/abud_memory.db.partial" "$backup_dir/abud_memory.db"
printf 'Backup: %s\n' "$backup_dir"

"${compose[@]}" up -d --no-deps --no-build abud-api
for attempt in {1..20}; do
  if curl --fail --silent --max-time 2 http://127.0.0.1:8000/health >/dev/null; then
    printf 'API healthy. Release: %s\n' "$release"
    exit 0
  fi
  sleep 2
done

echo "API did not answer /health. See Docker logs and the backup directory above." >&2
exit 1
