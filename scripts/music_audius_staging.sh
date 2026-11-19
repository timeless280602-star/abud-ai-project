#!/usr/bin/env bash
# Isolated proof of REST source loading only; no Discord login or production mounts.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOT=abud-staging-bot:provider-a503eec
LAVA=ghcr.io/lavalink-devs/lavalink:4.2.2
VOICE=abud-abud-voice-1
NAME="abud-audius-probe-$$"
NET="abud-audius-net-$$"
TMP="$(mktemp -d /tmp/abud-audius.XXXXXX)"
PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
VOICE_PAUSED=0
cleanup() {
    local rc=$?
    trap - EXIT
    set +e
    docker rm -f "$NAME" >/dev/null 2>&1
    docker network rm "$NET" >/dev/null 2>&1
    rm -rf -- "$TMP"
    if (( VOICE_PAUSED )); then
        echo "=== RESTORE VOICE WORKER ==="
        docker start "$VOICE" || rc=1
    fi
    echo "=== PRODUCTION HEALTH ==="
    curl -fsS --max-time 10 http://127.0.0.1:8000/health || rc=1
    echo
    echo "=== STAGING CLEANUP COMPLETE ==="
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "=== AUDIUS ACCESS RECHECK ==="
PYTHONPATH="$ROOT" PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import asyncio
from app.music_audius import AudiusCatalog
async def main():
    t = await AudiusCatalog().track("V66vyPP")
    print("PASS: Public track metadata", t.id, t.title, t.duration)
asyncio.run(main())
PY

echo "=== MEMORY CHECK ==="
if (( $(awk '/MemAvailable/ {print $2}' /proc/meminfo) < 870400 )); then
    if [[ "${ABUD_STAGE_PAUSE_VOICE:-0}" == 1 ]] && [[ "$(docker inspect "$VOICE" --format '{{.State.Running}}')" == true ]]; then
        VOICE_PAUSED=1
        docker stop -t 20 "$VOICE"
        sleep 5
    fi
fi
free -h
if (( $(awk '/MemAvailable/ {print $2}' /proc/meminfo) < 870400 )); then
    echo "Insufficient RAM: only retry with ABUD_STAGE_PAUSE_VOICE=1 during a voice maintenance window."
    exit 1
fi

API_ID="$(docker inspect abud-api --format '{{.Id}}')"
BOT_ID="$(docker inspect abud-bot --format '{{.Id}}')"
LAVA_ID="$(docker inspect abud-abud-lavalink-1 --format '{{.Id}}')"

chmod 755 "$TMP"
cat > "$TMP/application.yml" <<'YAML'
server:
  port: 2333
  address: 0.0.0.0
lavalink:
  server:
    sources:
      youtube: false
      soundcloud: false
      bandcamp: false
      twitch: false
      vimeo: false
      nico: false
      local: false
      http: true
logging:
  level:
    root: WARN
    lavalink: WARN
  request:
    enabled: false
    includeHeaders: false
    includeQueryString: false
    includePayload: false
YAML
chmod 644 "$TMP/application.yml"
docker network create "$NET" >/dev/null
docker run -d --pull never --name "$NAME" --network "$NET" --memory 640m \
    -e LAVALINK_SERVER_PASSWORD="$PASSWORD" \
    -e _JAVA_OPTIONS="-Xms96m -Xmx320m" \
    -v "$TMP/application.yml:/opt/Lavalink/application.yml:ro" "$LAVA" >/dev/null

echo "=== ISOLATED LAVALINK AUDIO SOURCE TEST ==="
if ! docker run --rm -i --pull never --network "$NET" --memory 96m \
    -e TARGET="$NAME" -e PASSWORD="$PASSWORD" --entrypoint python "$BOT" - <<'PY'
import json, os, time, urllib.parse, urllib.request
base = "http://" + os.environ["TARGET"] + ":2333"
headers = {"Authorization": os.environ["PASSWORD"]}
def get(path, timeout):
    with urllib.request.urlopen(urllib.request.Request(base + path, headers=headers), timeout=timeout) as r:
        return json.load(r)
for i in range(60):
    try:
        info = get("/v4/info", 3)
        break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit("FAIL: isolated Lavalink not ready")
assert "http" in info["sourceManagers"] and "local" not in info["sourceManagers"]
print("PASS: isolated HTTP source ready")
target = "https://api.audius.co/v1/tracks/V66vyPP/stream"
try:
    result = get("/v4/loadtracks?" + urllib.parse.urlencode({"identifier": target}), 35)
except Exception as error:
    raise SystemExit("FAIL: loadtracks request: " + type(error).__name__) from None
print("Load type:", result.get("loadType"))
if result.get("loadType") != "track":
    if result.get("loadType") == "error":
        print("Severity:", result.get("data", {}).get("severity"))
    raise SystemExit("FAIL: Audius stream not loaded by Lavalink")
track = result["data"]
info = track["info"]
assert track.get("encoded")
print("Source:", info.get("sourceName"))
print("Duration ms:", info.get("length"))
print("Is stream:", info.get("isStream"))
print("PASS: Lavalink accepted Audius stream")
PY
then
    docker inspect "$NAME" --format 'Staging={{.State.Status}} OOM={{.State.OOMKilled}}'
    exit 1
fi
test "$(docker inspect abud-api --format '{{.Id}}')" = "$API_ID"
test "$(docker inspect abud-bot --format '{{.Id}}')" = "$BOT_ID"
test "$(docker inspect abud-abud-lavalink-1 --format '{{.Id}}')" = "$LAVA_ID"
echo "=== AUDIUS LAVALINK SOURCE PROBE COMPLETE ==="
