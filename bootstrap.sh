#!/bin/sh
set -eu

REPO="AonoChano/claude-switch-tui"
LATEST_RELEASE_API="https://api.github.com/repos/${REPO}/releases/latest"
USER_AGENT="ClaudeSwitchBootstrap"

PYTHON=${PYTHON:-python3}
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "[csw] python3 was not found. Install Python 3.10+ first." >&2
    exit 1
fi

if ! "$PYTHON" -c 'import sys, zipfile, json, urllib.request; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    echo "[csw] Python 3.10+ is required." >&2
    exit 1
fi

download_stdout() {
    url="$1"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL -H "User-Agent: ${USER_AGENT}" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- --header="User-Agent: ${USER_AGENT}" "$url"
    else
        "$PYTHON" - "$url" "$USER_AGENT" <<'PY'
import sys
import urllib.request

url, user_agent = sys.argv[1], sys.argv[2]
request = urllib.request.Request(url, headers={"User-Agent": user_agent})
with urllib.request.urlopen(request, timeout=30) as response:
    sys.stdout.buffer.write(response.read())
PY
    fi
}

download_file() {
    url="$1"
    output="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL -H "User-Agent: ${USER_AGENT}" -o "$output" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$output" --header="User-Agent: ${USER_AGENT}" "$url"
    else
        "$PYTHON" - "$url" "$output" "$USER_AGENT" <<'PY'
import shutil
import sys
import urllib.request

url, output, user_agent = sys.argv[1], sys.argv[2], sys.argv[3]
request = urllib.request.Request(url, headers={"User-Agent": user_agent})
with urllib.request.urlopen(request, timeout=90) as response, open(output, "wb") as handle:
    shutil.copyfileobj(response, handle)
PY
    fi
}

TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/claude-switch-tui.XXXXXX")
cleanup() {
    rm -rf "$TMP_ROOT"
}
trap cleanup EXIT INT TERM

release_json="${TMP_ROOT}/release.json"
download_stdout "$LATEST_RELEASE_API" > "$release_json"

tag=$("$PYTHON" - "$release_json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
print(data.get("tag_name", ""))
PY
)
zip_url=$("$PYTHON" - "$release_json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
print(data.get("zipball_url", ""))
PY
)

if [ -z "$zip_url" ]; then
    echo "[csw] Latest release does not expose a source zip URL." >&2
    exit 1
fi

echo "[csw] Latest release: $tag"
zip_path="${TMP_ROOT}/source.zip"
extract_dir="${TMP_ROOT}/source"
mkdir -p "$extract_dir"

echo "[csw] Downloading release source zip..."
download_file "$zip_url" "$zip_path"

echo "[csw] Extracting release source zip..."
"$PYTHON" - "$zip_path" "$extract_dir" <<'PY'
import os
import sys
import zipfile
from pathlib import Path

zip_path = Path(sys.argv[1])
destination = Path(sys.argv[2]).resolve()
with zipfile.ZipFile(zip_path) as archive:
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if target != destination and not str(target).startswith(str(destination) + os.sep):
            raise SystemExit(f"Refusing to extract unsafe archive member: {member.filename}")
    archive.extractall(destination)
PY

source_dir=$(find "$extract_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)
if [ -z "$source_dir" ] || [ ! -f "${source_dir}/install.sh" ]; then
    echo "[csw] Release archive did not contain install.sh." >&2
    exit 1
fi

sh "${source_dir}/install.sh" "$@"
