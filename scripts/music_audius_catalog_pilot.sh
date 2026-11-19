#!/usr/bin/env bash
# Private guild Audius catalog pilot. Persistent rollback timer; no .env edits.
set -euo pipefail
umask 077
SCRIPT_PATH="$(realpath -e -- "$0")"
cd /opt/abud

BASE=(docker compose -p abud -f compose.yaml -f compose.voice.yaml -f compose.music.yaml -f compose.music.youtube.yaml)
OLD=sha256:26585b1ea6b7ec70d5b0279be816c164e209210d1825f7a616fecadfd1d0f1e7
IMAGE=abud-staging-bot:music-v2-6658cc8
EXPECTED=sha256:f69a2d06f93ee6cd334381b875cdb0582ee7ba902241b37f90efac7dfbbad785
ROOT=/var/lib/abud-audius-pilot
UNIT=abud-audius-pilot-rollback
[[ $EUID == 0 ]]
install -d -m 700 "$ROOT"
exec 9>"$ROOT/lock"
flock -w 180 9

probe() {
    docker exec -i abud-bot python - "$1" <<'PY'
import os, sys, time, json, urllib.request
expected = sys.argv[1] == "pilot"
url = os.environ["ABUD_LAVALINK_URL"] + "/v4/info"
headers = {"Authorization": os.environ["ABUD_LAVALINK_PASSWORD"]}
for i in range(45):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=3) as r:
            sources = set(json.load(r)["sourceManagers"])
        break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit("FAIL: Lavalink not ready")
assert sources == ({"http"} if expected else {"bandcamp", "soundcloud", "youtube"})
assert (os.getenv("ABUD_MUSIC_AUDIUS_CATALOG", "false").lower() == "true") == expected
assert os.getenv("ABUD_MUSIC_AUDIUS_TEST", "false").lower() == "false"
print("PASS: expected sources", sorted(sources))
PY
    test -z "$(docker port abud-abud-lavalink-1)"
    curl -fsS --max-time 10 http://127.0.0.1:8000/health
    echo
}

restore() {
    if [[ ! -f "$ROOT/pending" ]]; then
        echo "No pending pilot."
        return
    fi
    echo "=== RESTORE PRODUCTION ==="
    "${BASE[@]}" stop abud-bot
    "${BASE[@]}" up -d --no-deps --no-build --pull never --force-recreate abud-lavalink
    "${BASE[@]}" -f "$ROOT/rollback.yaml" up -d --no-deps --no-build --pull never --force-recreate abud-bot
    test "$(docker inspect abud-bot --format '{{.Image}}')" = "$OLD"
    probe production
    rm -f "$ROOT/pending"
    systemctl disable --now "$UNIT.timer"
    echo "=== PRODUCTION RESTORED ==="
}

if [[ "${1:-}" == restore ]]; then
    restore
    exit
fi
[[ "${1:-}" == start ]]
[[ ! -e "$ROOT/pending" ]] || { echo "Existing pilot pending; restore first."; exit 1; }
test "$(git rev-parse HEAD)" = b6d4baaf0ba9c137090a7a69950f7dc47c056455
git diff --quiet
git diff --cached --quiet
test "$(docker inspect abud-bot --format '{{.Image}}')" = "$OLD"
test "$(docker image inspect "$IMAGE" --format '{{.Id}}')" = "$EXPECTED"
probe production

read -r -p "Private pilot Discord Server ID: " GUILD < /dev/tty
[[ "$GUILD" =~ ^[0-9]{17,20}$ ]]
read -r -p "Reviewed Audius terms and authorized playback in private guild? YES: " ACK < /dev/tty
[[ "$ACK" == YES ]]

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/opt/abud-backups/audius-catalog-$STAMP"
install -d -m 700 "$BACKUP"
DBTMP="/tmp/abud-catalog-backup-$STAMP"
docker exec -i abud-bot python - "$DBTMP" <<'PY'
import os, sqlite3, sys
dest = sys.argv[1]
os.mkdir(dest, 0o700)
for path in ["/app/tickets/tickets.db", "/app/onboarding/community.db",
             "/app/leveling/levels.db", "/app/notifications/creators.db"]:
    if not os.path.isfile(path):
        print("Absent:", os.path.basename(path))
        continue
    with sqlite3.connect("file:" + path + "?mode=ro", uri=True, timeout=10) as src:
        with sqlite3.connect(os.path.join(dest, os.path.basename(path))) as dst:
            src.backup(dst)
            assert dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    print("PASS:", os.path.basename(path))
PY
docker cp "abud-bot:$DBTMP/." "$BACKUP/"
docker exec abud-bot rm -rf "$DBTMP"
docker tag "$OLD" "abud-rollback-bot:catalog-$STAMP"

cat > "$ROOT/rollback.yaml" <<YAML
services:
  abud-bot:
    image: abud-rollback-bot:catalog-$STAMP
    environment:
      ABUD_MUSIC_AUDIUS_TEST: 'false'
      ABUD_MUSIC_AUDIUS_CATALOG: 'false'
YAML
cat > "$ROOT/pilot.yaml" <<YAML
services:
  abud-bot:
    image: $IMAGE
    environment:
      ABUD_MUSIC_ENABLED: 'true'
      ABUD_MUSIC_AUDIUS_TEST: 'false'
      ABUD_MUSIC_AUDIUS_CATALOG: 'true'
      ABUD_MUSIC_AUDIUS_GUILD: '$GUILD'
      ABUD_MUSIC_AUDIUS_TERMS_ACCEPTED: 'true'
      ABUD_MUSIC_PLAYBACK_FALLBACK: 'false'
  abud-lavalink:
    environment:
      LAVALINK_SERVER_SOURCES_HTTP: 'true'
      LAVALINK_SERVER_SOURCES_LOCAL: 'false'
      LAVALINK_SERVER_SOURCES_SOUNDCLOUD: 'false'
      LAVALINK_SERVER_SOURCES_BANDCAMP: 'false'
      PLUGINS_YOUTUBE_ENABLED: 'false'
YAML
"${BASE[@]}" -f "$ROOT/pilot.yaml" config --quiet
"${BASE[@]}" -f "$ROOT/rollback.yaml" config --quiet
install -m 700 "$SCRIPT_PATH" "$ROOT/control.sh"
DEADLINE="$(date -u -d '+20 minutes' '+%Y-%m-%d %H:%M:%S UTC')"
cat > "/etc/systemd/system/$UNIT.service" <<YAML
[Unit]
Description=Restore ABUD production after Audius catalog pilot
After=docker.service network-online.target
Requires=docker.service
ConditionPathExists=$ROOT/pending
[Service]
Type=oneshot
ExecStart=$ROOT/control.sh restore
TimeoutStartSec=420
Restart=on-failure
RestartSec=30
YAML
cat > "/etc/systemd/system/$UNIT.timer" <<YAML
[Unit]
Description=Persistent ABUD catalog pilot rollback deadline
[Timer]
OnCalendar=$DEADLINE
Persistent=true
AccuracySec=1s
Unit=$UNIT.service
[Install]
WantedBy=timers.target
YAML
touch "$ROOT/pending"
systemctl daemon-reload
systemctl enable --now "$UNIT.timer"
systemctl is-active --quiet "$UNIT.timer"
systemctl is-enabled --quiet "$UNIT.timer"
echo "Rollback armed: $DEADLINE"
systemctl list-timers "$UNIT.timer" --no-pager
# On error, queue independent systemd recovery. It acquires the lock after exit.
trap 'rc=$?; if (( rc != 0 )); then systemctl --no-block start "$UNIT.service" || true; fi' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
API_ID="$(docker inspect abud-api --format '{{.Id}}')"
VOICE_ID="$(docker inspect abud-abud-voice-1 --format '{{.Id}}')"
"${BASE[@]}" stop abud-bot
"${BASE[@]}" -f "$ROOT/pilot.yaml" up -d --no-deps --no-build --pull never --force-recreate abud-lavalink
"${BASE[@]}" -f "$ROOT/pilot.yaml" up -d --no-deps --no-build --pull never --force-recreate abud-bot
test "$(docker inspect abud-bot --format '{{.Image}}')" = "$EXPECTED"
probe pilot
test "$(docker inspect abud-api --format '{{.Id}}')" = "$API_ID"
test "$(docker inspect abud-abud-voice-1 --format '{{.Id}}')" = "$VOICE_ID"
echo "=== AUDIUS CATALOG PILOT READY ==="
echo "Private guild only. Deadline: $DEADLINE"
echo "Restore early: systemctl start $UNIT.service"
echo "Recovery log: journalctl -u $UNIT.service --no-pager -n 40"
echo "Backup: $BACKUP"
