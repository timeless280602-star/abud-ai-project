#!/usr/bin/env bash
# Time-limited SABR compatibility pilot for authorized playback. Shared rollback lock; no .env edits.
set -euo pipefail
umask 077
SCRIPT_PATH="$(realpath -e -- "$0")"
cd /opt/abud

BASE=(docker compose -p abud -f compose.yaml -f compose.voice.yaml -f compose.music.yaml -f compose.music.youtube.yaml)
OLD=sha256:26585b1ea6b7ec70d5b0279be816c164e209210d1825f7a616fecadfd1d0f1e7
IMAGE=abud-staging-bot:music-v2-bcb8a20
EXPECTED=sha256:fd53db5fd18f0c83bbf33176a7dacff7344b234f851a8bc23681396952c1bc89
SABR=02f536d9ac05b4bb0f91dedc19f964f30fc18559
JAR_SHA=693087b71b4acc78fdc2110b9f4ba39ce0ef61aeaeb34c2cd71820239a8d36e8
PILOT=(docker compose -p abud -f compose.yaml -f compose.voice.yaml -f compose.music.yaml)
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
version = "02f536d9ac05b4bb0f91dedc19f964f30fc18559" if expected else "1.18.2"
url = os.environ["ABUD_LAVALINK_URL"] + "/v4/info"
headers = {"Authorization": os.environ["ABUD_LAVALINK_PASSWORD"]}
for i in range(45):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=3) as r:
            info = json.load(r)
            sources = set(info["sourceManagers"])
        break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit("FAIL: Lavalink not ready")
assert sources == {"bandcamp", "soundcloud", "youtube"}
assert [p["version"] for p in info["plugins"] if p["name"] == "youtube-plugin"] == [version]
assert os.getenv("ABUD_MUSIC_AUDIUS_CATALOG", "false").lower() == "false"
print("PASS: YouTube plugin version", version)
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

check_memberships() {
    docker exec -i abud-bot python - "$GUILD" "$1" <<'PY'
import os, sys, json, urllib.request
req = urllib.request.Request(
    "https://discord.com/api/v10/users/@me/guilds",
    headers={"Authorization": "Bot " + os.environ["DISCORD_TOKEN"],
             "User-Agent": "DiscordBot (https://abud.web.id, 1.0)"})
with urllib.request.urlopen(req, timeout=15) as r:
    guilds = json.load(r)
ids = sorted(g["id"] for g in guilds)
if sys.argv[1] not in ids:
    raise SystemExit("FAIL: Bot is not a member of the pilot guild")
print(" ".join(ids))
PY
}

read -r -p "Private pilot Discord Server ID: " GUILD < /dev/tty
[[ "$GUILD" =~ ^[0-9]{17,20}$ ]]
read -r -p "Maintenance affects both guilds. Authorized by provider and rights holder to test playback? YES: " ACK < /dev/tty
[[ "$ACK" == YES ]]
BEFORE_GUILDS="$(check_memberships before)"
echo "PASS: pilot guild membership verified"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/opt/abud-backups/youtube-sabr-$STAMP"
install -d -m 700 "$BACKUP"
PLUGINS="$ROOT/sabr-$STAMP"
install -d -m 755 "$PLUGINS"
JAR="$PLUGINS/youtube-plugin-$SABR.jar"
curl -fsS --proto '=https' --max-time 60 --max-filesize 52428800 \
    "https://maven.lavalink.dev/snapshots/dev/lavalink/youtube/youtube-plugin/$SABR/youtube-plugin-$SABR.jar" -o "$JAR"
printf '%s  %s\n' "$JAR_SHA" "$JAR" | sha256sum --check -
chmod 644 "$JAR"
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
      ABUD_MUSIC_AUDIUS_CATALOG: 'false'
      ABUD_MUSIC_PROVIDERS: 'soundcloud,youtube,bandcamp'
      ABUD_MUSIC_PLAYBACK_FALLBACK: 'false'
  abud-lavalink:
    environment:
      LAVALINK_SERVER_SOURCES_HTTP: 'false'
      LAVALINK_SERVER_SOURCES_LOCAL: 'false'
      PLUGINS_YOUTUBE_ENABLED: 'true'
      PLUGINS_YOUTUBE_ALLOWSEARCH: 'true'
      PLUGINS_YOUTUBE_ALLOWDIRECTVIDEOIDS: 'false'
      PLUGINS_YOUTUBE_ALLOWDIRECTPLAYLISTIDS: 'false'
      PLUGINS_YOUTUBE_CLIENTS_0: MUSIC
      PLUGINS_YOUTUBE_CLIENTS_1: ANDROID_VR
      PLUGINS_YOUTUBE_CLIENTS_2: WEB
      PLUGINS_YOUTUBE_CLIENTS_3: WEBEMBEDDED
    volumes:
      - $PLUGINS:/opt/Lavalink/plugins:ro
YAML
"${PILOT[@]}" -f "$ROOT/pilot.yaml" config --quiet
"${BASE[@]}" -f "$ROOT/rollback.yaml" config --quiet
install -m 700 "$SCRIPT_PATH" "$ROOT/control.sh"
DEADLINE="$(date -u -d '+10 minutes' '+%Y-%m-%d %H:%M:%S UTC')"
cat > "/etc/systemd/system/$UNIT.service" <<YAML
[Unit]
Description=Restore ABUD production after YouTube SABR pilot
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
Description=Persistent ABUD SABR pilot rollback deadline
[Timer]
OnCalendar=$DEADLINE
Persistent=true
AccuracySec=1s
Unit=$UNIT.service
[Install]
WantedBy=timers.target
YAML
touch "$ROOT/pending"
# Queue independent rollback even if timer setup fails.
trap 'rc=$?; if (( rc != 0 )); then systemctl --no-block start "$UNIT.service" || true; fi' EXIT
systemctl daemon-reload
systemctl enable --now "$UNIT.timer"
systemctl is-active --quiet "$UNIT.timer"
systemctl is-enabled --quiet "$UNIT.timer"
echo "Rollback armed: $DEADLINE"
systemctl list-timers "$UNIT.timer" --no-pager
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
API_ID="$(docker inspect abud-api --format '{{.Id}}')"
VOICE_ID="$(docker inspect abud-abud-voice-1 --format '{{.Id}}')"
"${BASE[@]}" stop abud-bot
"${PILOT[@]}" -f "$ROOT/pilot.yaml" up -d --no-deps --no-build --pull never --force-recreate abud-lavalink
"${PILOT[@]}" -f "$ROOT/pilot.yaml" up -d --no-deps --no-build --pull never --force-recreate abud-bot
test "$(docker inspect abud-bot --format '{{.Image}}')" = "$EXPECTED"
probe pilot
READY=false
for i in $(seq 1 45); do
    if docker logs abud-bot 2>&1 | grep -F "Guild sync selesai:" >/dev/null; then
        READY=true
        break
    fi
    sleep 2
done
test "$READY" = true
test "$(check_memberships after)" = "$BEFORE_GUILDS"
echo "PASS: Discord login and guild membership unchanged"
test "$(docker inspect abud-api --format '{{.Id}}')" = "$API_ID"
test "$(docker inspect abud-abud-voice-1 --format '{{.Id}}')" = "$VOICE_ID"
echo "=== YOUTUBE SABR PILOT READY ==="
echo "Temporary test affects both guilds. Deadline: $DEADLINE"
echo "Restore early: systemctl start $UNIT.service"
echo "Recovery log: journalctl -u $UNIT.service --no-pager -n 40"
echo "Backup: $BACKUP"
