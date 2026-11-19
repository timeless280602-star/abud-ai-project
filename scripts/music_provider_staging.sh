#!/usr/bin/env bash
# Run from a detached staging worktree. Never uses the production bot token,
# .env, compose networks, database volumes or writable production files.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
BOT_IMAGE=abud-staging-bot:760cc10
LAVA_IMAGE=$(docker inspect abud-abud-lavalink-1 --format '{{.Image}}')
test "$(docker image inspect "$BOT_IMAGE" --format '{{.Id}}')" = "sha256:e345cba437d544a49cb5cc3c784242cfecf65989c10218a0a4ba32db716d372c"
available=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
if (( available < 800*1024 )); then
  echo "STOP: less than 800 MiB available; staging would compete with production"
  exit 1
fi
for name in music-provider-staging; do
  if docker container inspect "$name" >/dev/null 2>&1; then
    echo "STOP: staging container already exists"; exit 1
  fi
done
NET="abud-music-provider-staging-$$"
TMP=$(mktemp -d)
CREATED=0
cleanup() {
  if (( CREATED )); then
    docker rm -f music-provider-staging >/dev/null 2>&1 || true
  fi
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf -- "$TMP"
}
trap cleanup EXIT
chmod 755 "$TMP"
sed 's/^      local: false$/      local: true/' music/application.yml > "$TMP/application.yml"
grep -q '^      local: true$' "$TMP/application.yml"
chmod 644 "$TMP/application.yml"
docker run --rm --network none --memory 96m --entrypoint python "$BOT_IMAGE" -c '
import io, math, struct, sys, wave
b=io.BytesIO()
with wave.open(b,"wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
    w.writeframes(b"".join(struct.pack("<h",int(2000*math.sin(2*math.pi*440*i/48000))) for i in range(48000*3)))
sys.stdout.buffer.write(b.getvalue())
' > "$TMP/tone.wav"
chmod 644 "$TMP/tone.wav"
export STAGING_PASSWORD=$(openssl rand -hex 32)
export LAVALINK_SERVER_PASSWORD="$STAGING_PASSWORD"
docker network create "$NET" >/dev/null
echo "=== ISOLATED STAGING BASELINE ==="
API_ID=$(docker inspect abud-api --format '{{.Id}}')
BOT_ID=$(docker inspect abud-bot --format '{{.Id}}')
LAVA_ID=$(docker inspect abud-abud-lavalink-1 --format '{{.Id}}')
start_node() {
  docker run -d --name music-provider-staging --network "$NET" \
    --memory 640m --cpus 1 \
    -e LAVALINK_SERVER_PASSWORD -e '_JAVA_OPTIONS=-Xms96m -Xmx320m' \
    -e LAVALINK_PLUGINS_0_DEPENDENCY=dev.lavalink.youtube:youtube-plugin:1.18.2 \
    -e LAVALINK_PLUGINS_0_SNAPSHOT=false \
    -e PLUGINS_YOUTUBE_ENABLED=true \
    -e PLUGINS_YOUTUBE_ALLOWSEARCH=true \
    -e PLUGINS_YOUTUBE_ALLOWDIRECTVIDEOIDS=false \
    -e PLUGINS_YOUTUBE_ALLOWDIRECTPLAYLISTIDS=false \
    -e PLUGINS_YOUTUBE_CLIENTS_0=MUSIC \
    -e PLUGINS_YOUTUBE_CLIENTS_1="$1" \
    -e PLUGINS_YOUTUBE_CLIENTS_2="$2" \
    -e PLUGINS_YOUTUBE_CLIENTS_3=WEBEMBEDDED \
    --mount "type=bind,src=$TMP/application.yml,dst=/opt/Lavalink/application.yml,readonly" \
    --mount "type=bind,src=$TMP/tone.wav,dst=/diagnostic/tone.wav,readonly" \
    "$LAVA_IMAGE" >/dev/null
  CREATED=1
}
probe() {
  docker run --rm --network "$NET" --memory 128m \
    -e STAGING_PASSWORD -e BANDCAMP_TEST_URL \
    --mount "type=bind,src=$PWD/scripts/music_provider_probe.py,dst=/tmp/music_provider_probe.py,readonly" \
    -e PYTHONPATH=/app --entrypoint python "$BOT_IMAGE" /tmp/music_provider_probe.py
}
start_node ANDROID_VR WEB
probe
docker rm -f music-provider-staging >/dev/null
CREATED=0
echo "=== DOCUMENTED CLIENT CANDIDATE (metadata only) ==="
start_node TVHTML5_SIMPLY MWEB
probe
echo "=== VERIFY PRODUCTION UNCHANGED ==="
test "$(docker inspect abud-api --format '{{.Id}}')" = "$API_ID"
test "$(docker inspect abud-bot --format '{{.Id}}')" = "$BOT_ID"
test "$(docker inspect abud-abud-lavalink-1 --format '{{.Id}}')" = "$LAVA_ID"
curl -fsS http://127.0.0.1:8000/health
echo
echo "=== STAGING SOURCE PROBE COMPLETE ==="
