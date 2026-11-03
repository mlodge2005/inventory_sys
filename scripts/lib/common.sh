# Shared paths and checks for Cyberdeck Inventory maintenance scripts.
# Source this file. Do not execute it directly.

if [[ -n "${_CYBERDECK_COMMON:-}" ]]; then
  return 0
fi
_CYBERDECK_COMMON=1

set -euo pipefail

APP_USER="${INVENTORY_APP_USER:-cyberdeck}"
APP_GROUP="${INVENTORY_APP_GROUP:-cyberdeck}"
SERVICE_NAME="${INVENTORY_SERVICE_NAME:-cyberdeck-inventory.service}"
DEFAULT_PORT=8765
MIN_FREE_KB="${INVENTORY_MIN_FREE_KB:-700000}"

log() { printf '%s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

prefix_paths() {
  if [[ -n "${INVENTORY_ROOT:-}" ]]; then
    ROOTLESS=1
    OPT_DIR="$INVENTORY_ROOT/opt"
    VAR_DIR="$INVENTORY_ROOT/var"
    ENV_FILE="$INVENTORY_ROOT/etc/cyberdeck-inventory.env"
    UNIT_DIR="$INVENTORY_ROOT/systemd"
    BIN_DIR="$INVENTORY_ROOT/bin"
  else
    ROOTLESS=0
    OPT_DIR=/opt/cyberdeck-inventory
    VAR_DIR=/var/lib/cyberdeck-inventory
    ENV_FILE=/etc/cyberdeck-inventory.env
    UNIT_DIR=/etc/systemd/system
    BIN_DIR=/usr/local/bin
  fi
  REPO_DIR="$OPT_DIR/repo"
  RELEASES_DIR="$OPT_DIR/releases"
  CURRENT_LINK="$OPT_DIR/current"
  VENV_DIR="$OPT_DIR/venv"
  VENV_STAGING="$OPT_DIR/venv-staging"
  VENV_PREVIOUS="$OPT_DIR/venv-previous"
  LOCK_DIR="$OPT_DIR/.update.lock"
  BACKUP_DIR="$VAR_DIR/backups"
  DB_PATH="$VAR_DIR/inventory.db"
  SERVE_BIN="$OPT_DIR/bin/serve"
}

require_linux() {
  [[ "$(uname -s)" == "Linux" ]] || die "Cyberdeck Inventory installs on Linux."
}

check_os() {
  require_linux
  if [[ ! -r /etc/os-release ]]; then
    [[ "${INVENTORY_ALLOW_UNSUPPORTED_OS:-0}" == 1 ]] || die "Missing /etc/os-release. Set INVENTORY_ALLOW_UNSUPPORTED_OS=1 to continue."
    return 0
  fi
  # shellcheck disable=SC1091
  . /etc/os-release
  local like="${ID_LIKE:-}"
  if [[ "${ID:-}" != "debian" && "$like" != *debian* ]]; then
    [[ "${INVENTORY_ALLOW_UNSUPPORTED_OS:-0}" == 1 ]] || die "Unsupported OS ${ID:-unknown}. Debian is required unless INVENTORY_ALLOW_UNSUPPORTED_OS=1."
  fi
  if [[ "${ID:-}" != "debian" || "${VERSION_CODENAME:-}" != "trixie" ]]; then
    log "warning: target OS is Debian 13 (Trixie). This host reports ${PRETTY_NAME:-unknown}."
  fi
  if [[ "$(uname -m)" != "aarch64" ]]; then
    log "warning: target CPU is Raspberry Pi 3 (aarch64). This host is $(uname -m)."
  fi
}

require_root_if_needed() {
  if [[ "$ROOTLESS" == 0 && "${EUID:-$(id -u)}" -ne 0 ]]; then
    die "Run this script as root, for example: sudo $0"
  fi
}

python_ok() {
  command -v python3 >/dev/null 2>&1 || die "python3 is not installed."
  python3 - <<'PY' || die "Python 3.11 or newer is required."
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

node_ok() {
  command -v node >/dev/null 2>&1 || return 1
  node -e 'const major = Number(process.versions.node.split(".")[0]); process.exit(major >= 20 ? 0 : 1)'
}

port_in_use() {
  local port="$1"
  local ss_bin="${INVENTORY_SS_BIN:-ss}"
  if [[ -x "$ss_bin" || "$(command -v "$ss_bin" || true)" != "" ]]; then
    "$ss_bin" -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(^|[:.])${port}$"
    return $?
  fi
  python3 - "$port" <<'PY'
import socket, sys
port = int(sys.argv[1])
sock = socket.socket()
sock.settimeout(0.2)
try:
    sock.connect(("127.0.0.1", port))
except OSError:
    sys.exit(1)
else:
    sys.exit(0)
PY
}

choose_port() {
  local port="$DEFAULT_PORT"
  if port_in_use "$port"; then
    log "Port ${port} is in use. Looking for another port. The occupant will be left running."
    local candidate
    for candidate in $(seq 8766 8799); do
      if ! port_in_use "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
    done
    die "No free TCP port from 8765 through 8799."
  fi
  printf '%s\n' "$port"
}

env_value() {
  local key="$1"
  [[ -f "$ENV_FILE" ]] || return 0
  python3 - "$ENV_FILE" "$key" <<'PY'
import sys
path, key = sys.argv[1], sys.argv[2]
for raw in open(path, encoding="utf-8"):
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    name, value = line.split("=", 1)
    if name.strip() == key:
        print(value.strip().strip("\"'"))
        break
PY
}

acquire_lock() {
  mkdir -p "$(dirname "$LOCK_DIR")"
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    die "Another install or update holds $LOCK_DIR. If no script is running, remove that directory."
  fi
  trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
}

disk_ok() {
  local avail
  mkdir -p "$OPT_DIR"
  avail="$(df -Pk "$OPT_DIR" | awk 'NR==2 {print $4}')"
  if [[ -z "$avail" || "$avail" -lt "$MIN_FREE_KB" ]]; then
    die "Need at least ${MIN_FREE_KB} KB free on $(df -P "$OPT_DIR" | awk 'NR==2 {print $6}'), found ${avail:-0} KB."
  fi
}

repo_dirty() {
  [[ -d "$REPO_DIR/.git" ]] || return 1
  [[ -n "$(git -C "$REPO_DIR" status --porcelain)" ]]
}

systemctl_bin() {
  if [[ -n "${INVENTORY_SYSTEMCTL_BIN:-}" ]]; then
    printf '%s\n' "$INVENTORY_SYSTEMCTL_BIN"
  elif [[ "${ROOTLESS:-0}" == 1 ]]; then
    printf '%s\n' ""
  elif command -v systemctl >/dev/null 2>&1; then
    printf '%s\n' systemctl
  else
    printf '%s\n' ""
  fi
}

service_is_active() {
  local bin pid
  bin="$(systemctl_bin)"
  if [[ -n "$bin" ]] && "$bin" is-active --quiet "$SERVICE_NAME"; then
    return 0
  fi
  if [[ -f "$OPT_DIR/service.pid" ]]; then
    pid="$(cat "$OPT_DIR/service.pid")"
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
    return $?
  fi
  return 1
}

stop_service() {
  local bin
  bin="$(systemctl_bin)"
  if [[ -n "$bin" ]]; then
    "$bin" stop "$SERVICE_NAME" || true
    return 0
  fi
  if [[ -f "$OPT_DIR/service.pid" ]]; then
    local pid
    pid="$(cat "$OPT_DIR/service.pid")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" || true
      wait "$pid" 2>/dev/null || true
    fi
    rm -f "$OPT_DIR/service.pid"
  fi
}

start_service() {
  local bin
  bin="$(systemctl_bin)"
  if [[ -n "$bin" ]]; then
    if [[ "$ROOTLESS" == 0 ]]; then
      "$bin" enable "$SERVICE_NAME"
    fi
    "$bin" restart "$SERVICE_NAME"
    return 0
  fi
  # Rootless foreground fallback used by the unprivileged installer test.
  # shellcheck disable=SC1090
  set -a
  source "$ENV_FILE"
  set +a
  export PYTHONPATH="$CURRENT_LINK/backend:$CURRENT_LINK/cli${PYTHONPATH:+:$PYTHONPATH}"
  nohup "$VENV_DIR/bin/python" -m app.main >"$OPT_DIR/service.log" 2>&1 &
  echo $! >"$OPT_DIR/service.pid"
}

health_once() {
  local port="$1"
  if [[ -n "${INVENTORY_CURL_BIN:-}" ]]; then
    "$INVENTORY_CURL_BIN" -fsS "http://127.0.0.1:${port}/api/v1/health"
    return $?
  fi
  python3 - "$port" <<'PY'
import json, sys, urllib.request
port = sys.argv[1]
url = f"http://127.0.0.1:{port}/api/v1/health"
try:
    with urllib.request.urlopen(url, timeout=2) as response:
        raw = response.read().decode()
        print(raw)
        body = json.loads(raw)
        sys.exit(0 if response.status == 200 and body.get("status") == "ok" else 1)
except Exception as exc:
    print(exc, file=sys.stderr)
    sys.exit(1)
PY
}

wait_for_health() {
  local port="$1"
  local attempt
  local attempts="${INVENTORY_HEALTH_ATTEMPTS:-30}"
  for attempt in $(seq 1 "$attempts"); do
    if health_once "$port"; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

stage_tree() {
  local dest="$1"
  local revision="$2"
  rm -rf "$dest"
  mkdir -p "$dest"
  git -C "$REPO_DIR" archive --format=tar "$revision" | tar -C "$dest" -xf -
}

build_frontend() {
  local dest="$1"
  if [[ "${INVENTORY_SKIP_FRONTEND:-0}" == 1 ]]; then
    mkdir -p "$dest/frontend/dist"
    if [[ ! -f "$dest/frontend/dist/index.html" ]]; then
      printf '%s\n' '<!DOCTYPE html><title>Cyberdeck Inventory</title><p>Frontend build skipped.</p>' >"$dest/frontend/dist/index.html"
    fi
    return 0
  fi
  [[ -f "$dest/frontend/package.json" ]] || die "Release is missing frontend/package.json."
  node_ok || die "Node.js 20 or newer is required to build the website. Install it, then rerun. This installer does not add a third-party Node repository."
  (cd "$dest/frontend" && npm ci && npm test && npm run build && rm -rf node_modules)
}

make_venv() {
  local dest="$1"
  rm -rf "$dest"
  if [[ "${INVENTORY_SKIP_PIP:-0}" == 1 ]]; then
    mkdir -p "$dest/bin"
    ln -sfn "$(command -v python3)" "$dest/bin/python"
    ln -sfn "$(command -v python3)" "$dest/bin/python3"
    return 0
  fi
  python3 -m venv "$dest"
  "$dest/bin/pip" install --upgrade pip
  "$dest/bin/pip" install -r "$2/backend/requirements.txt" -r "$2/backend/requirements-cli.txt" -r "$2/backend/requirements-dev.txt"
}

run_release_tests() {
  local release="$1"
  local python="$2"
  if [[ "${INVENTORY_SKIP_TESTS:-0}" == 1 ]]; then
    log "warning: automated tests skipped because INVENTORY_SKIP_TESTS=1."
    return 0
  fi
  local tmp
  tmp="$(mktemp)"
  INVENTORY_ENVIRONMENT=test \
    INVENTORY_DATABASE_PATH="$tmp" \
    INVENTORY_FRONTEND_DIST="$release/frontend/dist" \
    PYTHONPATH="$release/backend:$release/cli" \
    "$python" -m pytest "$release/backend/tests" "$release/cli/tests" -q
  rm -f "$tmp" "$tmp-wal" "$tmp-shm" "$tmp.json"
}

schema_of() {
  if [[ -n "${INVENTORY_SCHEMA_CMD:-}" ]]; then
    "$INVENTORY_SCHEMA_CMD"
    return 0
  fi
  local python="$1"
  local release="$2"
  PYTHONPATH="${INVENTORY_PYTHONPATH:-$release/backend}" \
    INVENTORY_DATABASE_PATH="$DB_PATH" \
    INVENTORY_ENVIRONMENT=production \
    "$python" -m app.maintenance revision --database "$DB_PATH"
}

apply_migrations() {
  local python="$1"
  local release="$2"
  if [[ "${INVENTORY_SKIP_MIGRATE:-0}" == 1 ]]; then
    return 0
  fi
  PYTHONPATH="${INVENTORY_PYTHONPATH:-$release/backend}" \
    INVENTORY_DATABASE_PATH="$DB_PATH" \
    INVENTORY_BACKUP_DIR="$BACKUP_DIR" \
    INVENTORY_ENVIRONMENT=production \
    INVENTORY_FRONTEND_DIST="$release/frontend/dist" \
    "$python" - <<'PY'
from app.core.config import get_settings
from app.db.session import init_database
get_settings.cache_clear()
init_database(get_settings(), migrate=True)
PY
}

backup_now() {
  local python="$1"
  local release="$2"
  local dest="$3"
  if [[ "${INVENTORY_SKIP_BACKUP:-0}" == 1 ]]; then
    printf '%s\n' "$dest"
    return 0
  fi
  mkdir -p "$BACKUP_DIR"
  PYTHONPATH="${INVENTORY_PYTHONPATH:-$release/backend}" \
    INVENTORY_DATABASE_PATH="$DB_PATH" \
    INVENTORY_ENVIRONMENT=production \
    "$python" -m app.maintenance backup --database "$DB_PATH" --dest "$dest" >/dev/null
  printf '%s\n' "$dest"
}

activate_release() {
  local release="$1"
  local staged_venv="$2"
  ln -sfn "$release" "$OPT_DIR/current.next"
  mv -Tf "$OPT_DIR/current.next" "$CURRENT_LINK"
  if [[ -d "$VENV_DIR" ]]; then
    rm -rf "$VENV_PREVIOUS"
    mv "$VENV_DIR" "$VENV_PREVIOUS"
  fi
  mv "$staged_venv" "$VENV_DIR"
}

rollback_release() {
  local previous_release="$1"
  ln -sfn "$previous_release" "$OPT_DIR/current.next"
  mv -Tf "$OPT_DIR/current.next" "$CURRENT_LINK"
  if [[ -d "$VENV_PREVIOUS" ]]; then
    rm -rf "$OPT_DIR/venv-failed"
    mv "$VENV_DIR" "$OPT_DIR/venv-failed"
    mv "$VENV_PREVIOUS" "$VENV_DIR"
  fi
}

# Own the data directory as the service account and make every database file
# group-writable. Idempotent. Does not follow symlinks and does not touch the
# env file, which stays outside this directory at mode 0640.
fix_data_permissions() {
  mkdir -p "$VAR_DIR" "$BACKUP_DIR"
  if [[ "${ROOTLESS:-0}" == 0 ]]; then
    chown --no-dereference "$APP_USER:$APP_GROUP" "$VAR_DIR"
    find "$VAR_DIR" -xdev \( -type d -o -type f \) -print0 |
      xargs -0 -r chown --no-dereference "$APP_USER:$APP_GROUP"
  fi
  find "$VAR_DIR" -xdev -type d -print0 | xargs -0 -r chmod 2770
  find "$VAR_DIR" -xdev -type f -print0 | xargs -0 -r chmod 660
}

publish_runtime() {
  write_serve_wrapper
  write_cli_wrapper
  install_unit
  fix_data_permissions
  if [[ "${ROOTLESS:-0}" == 0 ]]; then
    systemctl daemon-reload
  fi
}

write_serve_wrapper() {
  mkdir -p "$OPT_DIR/bin"
  cat >"$SERVE_BIN" <<EOF
#!/usr/bin/env bash
set -euo pipefail
# SQLite requests mode 0644. This umask clears world bits. Group write is
# applied with chmod 0660 after SQLite creates the database, WAL, and SHM.
umask 0007
set -a
source "$ENV_FILE"
set +a
cd "$CURRENT_LINK/backend"
export PYTHONPATH="$CURRENT_LINK/backend:$CURRENT_LINK/cli\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$VENV_DIR/bin/python" -m app.main
EOF
  chmod 755 "$SERVE_BIN"
}

write_cli_wrapper() {
  mkdir -p "$BIN_DIR"
  cat >"$BIN_DIR/inventory" <<EOF
#!/usr/bin/env bash
set -euo pipefail
# Match the service umask so a WAL created by the CLI is not world-readable.
# app.db.permissions then adds group write (mode 0660).
umask 0007
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
export PYTHONPATH="$CURRENT_LINK/backend:$CURRENT_LINK/cli\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$VENV_DIR/bin/python" -m inventory_cli "\$@"
EOF
  chmod 755 "$BIN_DIR/inventory"
}

install_unit() {
  mkdir -p "$UNIT_DIR"
  local unit="$UNIT_DIR/$SERVICE_NAME"
  if [[ "$ROOTLESS" == 1 ]]; then
    cat >"$unit" <<EOF
[Unit]
Description=Cyberdeck Inventory
[Service]
Type=simple
EnvironmentFile=$ENV_FILE
WorkingDirectory=$CURRENT_LINK/backend
ExecStart=$SERVE_BIN
UMask=0007
[Install]
WantedBy=multi-user.target
EOF
  else
    sed \
      -e "s|^EnvironmentFile=.*|EnvironmentFile=$ENV_FILE|" \
      -e "s|^WorkingDirectory=.*|WorkingDirectory=$CURRENT_LINK/backend|" \
      -e "s|^ExecStart=.*|ExecStart=$SERVE_BIN|" \
      -e "s|^ReadWritePaths=.*|ReadWritePaths=$VAR_DIR|" \
      -e "s|^User=.*|User=$APP_USER|" \
      -e "s|^Group=.*|Group=$APP_GROUP|" \
      "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/deploy/cyberdeck-inventory.service" >"$unit"
  fi
}

prune_releases() {
  local keep_a="$1"
  local keep_b="${2:-}"
  local dir base
  [[ -d "$RELEASES_DIR" ]] || return 0
  for dir in "$RELEASES_DIR"/*; do
    [[ -d "$dir" ]] || continue
    base="$(basename "$dir")"
    if [[ "$base" == "$keep_a" || "$base" == "$keep_b" ]]; then
      continue
    fi
    rm -rf "$dir"
  done
}

print_urls() {
  local port="$1"
  local python="${2:-python3}"
  local release="${3:-$CURRENT_LINK}"
  PYTHONPATH="${INVENTORY_PYTHONPATH:-$release/backend}" \
    INVENTORY_PORT="$port" \
    INVENTORY_HOST="${4:-0.0.0.0}" \
    "$python" - <<'PY' || true
from app.services.network import detect_addresses, exposure_warnings
import os
port = int(os.environ["INVENTORY_PORT"])
host = os.environ.get("INVENTORY_HOST", "0.0.0.0")
addresses = detect_addresses()
print("Detected website URLs:")
if not addresses:
    print(f"  http://127.0.0.1:{port}")
for address in addresses:
    print(f"  {address.kind:10} {address.url(port)}  ({address.interface})")
for warning in exposure_warnings(host, addresses):
    print("warning:", warning)
PY
}
