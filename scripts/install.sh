#!/usr/bin/env bash
# Idempotent installer for Cyberdeck Inventory.
# Production: sudo ./scripts/install.sh
# Unprivileged layout test: INVENTORY_ROOT=/tmp/inventory-test ./scripts/install.sh
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$SOURCE_DIR/scripts/lib/common.sh"
prefix_paths
require_root_if_needed
check_os
python_ok

if [[ "$ROOTLESS" == 0 ]]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y python3 python3-venv python3-pip sqlite3 ca-certificates iproute2
  if ! node_ok; then
    apt-get install -y nodejs npm || true
    node_ok || die "Node.js 20 or newer is required to build the website. Install it from Debian packages if they are new enough. This installer does not configure a third-party Node repository and does not change other websites."
  fi
else
  node_ok || log "warning: Node.js 20 was not found. Set INVENTORY_SKIP_FRONTEND=1 only for a layout test."
fi

acquire_lock
disk_ok

mkdir -p "$OPT_DIR" "$RELEASES_DIR" "$VAR_DIR" "$BACKUP_DIR" "$OPT_DIR/bin" "$(dirname "$ENV_FILE")"
if [[ "$ROOTLESS" == 0 ]]; then
  if ! getent group "$APP_GROUP" >/dev/null; then
    groupadd --system "$APP_GROUP"
  fi
  if ! id "$APP_USER" >/dev/null 2>&1; then
    useradd --system --gid "$APP_GROUP" --home-dir "$VAR_DIR" --shell /usr/sbin/nologin "$APP_USER"
  fi
  if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
    usermod -aG "$APP_GROUP" "$SUDO_USER" || true
    log "Added $SUDO_USER to group $APP_GROUP. Open a new login before using the inventory command."
  fi
  chown "$APP_USER:$APP_GROUP" "$VAR_DIR" "$BACKUP_DIR"
  chmod 2770 "$VAR_DIR" "$BACKUP_DIR"
  chmod 2755 "$OPT_DIR"
fi

if [[ ! -d "$REPO_DIR/.git" ]]; then
  if [[ -n "${INVENTORY_GIT_URL:-}" ]]; then
    git clone --branch "${INVENTORY_GIT_BRANCH:-main}" "$INVENTORY_GIT_URL" "$REPO_DIR"
  elif git -C "$SOURCE_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git clone "$SOURCE_DIR" "$REPO_DIR"
    origin_url="$(git -C "$SOURCE_DIR" remote get-url origin 2>/dev/null || true)"
    if [[ -n "$origin_url" && "$origin_url" != "$SOURCE_DIR" ]]; then
      git -C "$REPO_DIR" remote set-url origin "$origin_url"
    fi
  else
    die "Install from a git checkout, or set INVENTORY_GIT_URL."
  fi
fi

if repo_dirty; then
  log "warning: $REPO_DIR has uncommitted changes. The release is built from the last commit, not from those edits."
fi

revision="$(git -C "$REPO_DIR" rev-parse HEAD)"
release="$RELEASES_DIR/$revision"
if [[ ! -f "$release/backend/pyproject.toml" && "${INVENTORY_SKIP_FRONTEND:-0}" != 1 ]]; then
  stage_tree "$release" "$revision"
elif [[ ! -d "$release" ]]; then
  stage_tree "$release" "$revision"
fi
if [[ ! -f "$release/backend/app/main.py" ]]; then
  stage_tree "$release" "$revision"
fi
build_frontend "$release"

if [[ ! -x "$VENV_STAGING/bin/python" ]]; then
  make_venv "$VENV_STAGING" "$release"
fi
run_release_tests "$release" "$VENV_STAGING/bin/python"

host="0.0.0.0"
port=""
if [[ -f "$ENV_FILE" ]]; then
  host="$(env_value INVENTORY_HOST)"
  port="$(env_value INVENTORY_PORT)"
  host="${host:-0.0.0.0}"
  port="${port:-$DEFAULT_PORT}"
  if port_in_use "$port" && ! service_is_active; then
    die "Configured port $port is used by another program. Edit $ENV_FILE. This installer will not stop that program."
  fi
  log "Keeping existing configuration in $ENV_FILE"
else
  port="$(choose_port)"
  # Restrict the env file only. Restore the previous umask before SQLite or
  # Alembic runs, or the database is created mode 0600 and the CLI cannot open it.
  saved_umask="$(umask)"
  umask 0077
  cat >"$ENV_FILE" <<EOF
INVENTORY_ENVIRONMENT=production
INVENTORY_DATABASE_PATH=$DB_PATH
INVENTORY_BACKUP_DIR=$BACKUP_DIR
INVENTORY_HOST=$host
INVENTORY_PORT=$port
INVENTORY_FRONTEND_DIST=$CURRENT_LINK/frontend/dist
INVENTORY_LOG_LEVEL=info
INVENTORY_ALLOWED_ORIGINS=
INVENTORY_PUBLIC_URL=
INVENTORY_GIT_REMOTE=${INVENTORY_GIT_REMOTE:-origin}
INVENTORY_GIT_BRANCH=${INVENTORY_GIT_BRANCH:-main}
EOF
  umask "$saved_umask"
  if [[ "$ROOTLESS" == 0 ]]; then
    chown root:"$APP_GROUP" "$ENV_FILE"
    chmod 640 "$ENV_FILE"
  fi
  log "Wrote $ENV_FILE with port $port."
fi

if [[ -f "$DB_PATH" ]]; then
  log "Database already exists and will be kept: $DB_PATH"
fi
stop_service
apply_migrations "$VENV_STAGING/bin/python" "$release"
activate_release "$release" "$VENV_STAGING"
publish_runtime
start_service

if ! wait_for_health "$port"; then
  log "Health check failed. Recent diagnostics:"
  log "  journalctl -u $SERVICE_NAME -n 80 --no-pager"
  log "  $BIN_DIR/inventory status"
  log "The database was not deleted: $DB_PATH"
  exit 1
fi

printf '\nCyberdeck Inventory is running.\n'
printf 'Environment: %s\n' "$ENV_FILE"
printf 'Database: %s\n' "$DB_PATH"
printf 'Command: inventory\n'
print_urls "$port" "$VENV_DIR/bin/python" "$CURRENT_LINK" "$host"
cat <<'EOF'

Binding to 0.0.0.0 answers every IPv4 interface, which is how one process serves
both the LAN and Tailscale. Do not forward this port on your router and do not
enable Tailscale Funnel. Version 1 has no login.

This installer does not change other websites, reverse proxies, firewalls,
Tailscale, or NetworkManager. If you use a firewall, allow the chosen port from
trusted networks yourself, for example:

  sudo ufw allow from 10.0.0.0/8 to any port PORT proto tcp
  sudo ufw allow from 192.168.0.0/16 to any port PORT proto tcp
  sudo ufw allow from 172.16.0.0/12 to any port PORT proto tcp
  sudo ufw allow from 100.64.0.0/10 to any port PORT proto tcp

Replace PORT with the value in the environment file. Open a new login so your
user can use the inventory command as a member of the cyberdeck group. The
database, WAL, and shared-memory files are mode 0660 for that group. Re-running
this installer repairs an older mode 0600 database without deleting it.
EOF
