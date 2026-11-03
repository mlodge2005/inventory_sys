#!/usr/bin/env bash
# Exercises installer safety without touching the real /opt or systemd.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

for script in scripts/*.sh scripts/lib/*.sh; do
  bash -n "$script"
done

if grep -RInE --exclude-dir=tests 'git reset --hard|git clean|iptables|tailscale funnel|killall|nginx|hostapd' scripts; then
  fail "deployment scripts contain a command that would change unrelated services"
fi
ufw_files="$(grep -RIl --exclude-dir=tests 'ufw' scripts || true)"
[[ "$ufw_files" == "scripts/install.sh" ]] || fail "ufw should only appear in the install instructions the administrator runs"

# shellcheck disable=SC1091
source "$ROOT/scripts/lib/common.sh"
export INVENTORY_ROOT
INVENTORY_ROOT="$(mktemp -d)"
prefix_paths
ss_bin="$(mktemp)"
cat >"$ss_bin" <<'EOF'
#!/bin/bash
printf '%s\n' "LISTEN 0 128 0.0.0.0:8765"
EOF
chmod +x "$ss_bin"
export INVENTORY_SS_BIN="$ss_bin"
chosen="$(choose_port)"
[[ "$chosen" == "8766" ]] || fail "expected port 8766, got $chosen"
# The fake ss must still be executable; choose_port must not remove it.
[[ -x "$ss_bin" ]] || fail "port scan removed the port-check tool"

listener_port=8877
python3 - "$listener_port" <<'PY' &
import socket, sys, time
sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", int(sys.argv[1])))
sock.listen(1)
time.sleep(30)
PY
listener_pid=$!
sleep 0.2
unset INVENTORY_SS_BIN
port_in_use "$listener_port" || fail "expected the test listener to own port $listener_port"
kill "$listener_pid"
wait "$listener_pid" 2>/dev/null || true

setup_tree() {
  WORK="$(mktemp -d)"
  export INVENTORY_ROOT="$WORK"
  export INVENTORY_MIN_FREE_KB=1
  export INVENTORY_SKIP_PIP=1
  export INVENTORY_SKIP_FRONTEND=1
  export INVENTORY_SKIP_TESTS=1
  export INVENTORY_SKIP_MIGRATE=1
  export INVENTORY_SKIP_BACKUP=1
  export INVENTORY_HEALTH_ATTEMPTS=1
  export INVENTORY_PYTHONPATH="$ROOT/backend"
  unset INVENTORY_SCHEMA_CMD INVENTORY_CURL_BIN INVENTORY_SYSTEMCTL_BIN
  ORIGIN="$(mktemp -d)"
  git init -b main "$ORIGIN" >/dev/null
  echo first >"$ORIGIN/README.md"
  git -C "$ORIGIN" add README.md
  git -C "$ORIGIN" -c user.email=test@example.com -c user.name=test commit -m first >/dev/null
  mkdir -p "$WORK/opt"
  git clone "$ORIGIN" "$WORK/opt/repo" >/dev/null
  rev="$(git -C "$WORK/opt/repo" rev-parse HEAD)"
  mkdir -p "$WORK/opt/releases/$rev" "$WORK/opt/venv/bin" "$WORK/var/backups" "$WORK/etc" "$WORK/bin" "$WORK/systemd"
  ln -s "$WORK/opt/releases/$rev" "$WORK/opt/current"
  ln -s "$(command -v python3)" "$WORK/opt/venv/bin/python"
  printf 'database-bytes' >"$WORK/var/inventory.db"
  chmod 600 "$WORK/var/inventory.db"
  cat >"$WORK/etc/cyberdeck-inventory.env" <<EOF
INVENTORY_ENVIRONMENT=production
INVENTORY_DATABASE_PATH=$WORK/var/inventory.db
INVENTORY_BACKUP_DIR=$WORK/var/backups
INVENTORY_HOST=127.0.0.1
INVENTORY_PORT=8765
INVENTORY_GIT_REMOTE=origin
INVENTORY_GIT_BRANCH=main
EOF
  env_mode_before="$(stat -c %a "$WORK/etc/cyberdeck-inventory.env")"
  CTL="$(mktemp)"
  cat >"$CTL" <<EOF
#!/bin/bash
printf '%s\n' "\$*" >> "$WORK/systemctl.log"
if [[ "\$1" == "is-active" ]]; then
  exit 0
fi
exit 0
EOF
  chmod +x "$CTL"
  export INVENTORY_SYSTEMCTL_BIN="$CTL"
  CURL="$(mktemp)"
  printf '%s\n' '#!/bin/bash' 'exit 1' >"$CURL"
  chmod +x "$CURL"
  export INVENTORY_CURL_BIN="$CURL"
  REV_OUT="$rev"
}

setup_tree
rev1="$REV_OUT"
before_link="$(readlink -f "$WORK/opt/current")"
echo dirty >>"$WORK/opt/repo/README.md"
set +e
bash "$ROOT/scripts/update.sh" >"$WORK/update-dirty.out" 2>"$WORK/update-dirty.err"
dirty_code=$?
set -e
[[ "$dirty_code" -ne 0 ]] || fail "dirty update should fail"
[[ "$(readlink -f "$WORK/opt/current")" == "$before_link" ]] || fail "dirty update moved the current release"
grep -q 'Uncommitted' "$WORK/update-dirty.err" || fail "dirty update did not explain why it stopped"
cmp -s <(printf 'database-bytes') "$WORK/var/inventory.db" || fail "dirty update changed the database"

# Same schema, failed health: roll the symlink back and keep the database bytes.
setup_tree
rev1="$REV_OUT"
git -C "$ORIGIN" -c user.email=test@example.com -c user.name=test commit --allow-empty -m second >/dev/null
SCHEMA="$(mktemp)"
printf '%s\n' '#!/bin/bash' 'echo rev1' >"$SCHEMA"
chmod +x "$SCHEMA"
export INVENTORY_SCHEMA_CMD="$SCHEMA"
before_db="$(cat "$WORK/var/inventory.db")"
set +e
bash "$ROOT/scripts/update.sh" >"$WORK/update-rollback.out" 2>"$WORK/update-rollback.err"
rollback_code=$?
set -e
[[ "$rollback_code" -ne 0 ]] || fail "failed health check should be nonzero"
[[ "$(readlink -f "$WORK/opt/current")" == "$WORK/opt/releases/$rev1" ]] || fail "schema-stable failure should restore the previous release"
[[ "$(cat "$WORK/var/inventory.db")" == "$before_db" ]] || fail "failed update changed the database"
grep -q 'previous release' "$WORK/update-rollback.err" || fail "rollback did not explain recovery"
[[ "$(stat -c %a "$WORK/var")" == "2770" ]] || fail "update should leave the data directory at 2770"
[[ "$(stat -c %a "$WORK/var/backups")" == "2770" ]] || fail "update should leave the backup directory at 2770"
[[ "$(stat -c %a "$WORK/var/inventory.db")" == "660" ]] || fail "update should make the database group-writable"
grep -q 'umask 0007' "$WORK/opt/bin/serve" || fail "serve wrapper should set umask 0007"
grep -q 'umask 0007' "$WORK/bin/inventory" || fail "inventory wrapper should set umask 0007"
grep -q 'UMask=0007' "$WORK/systemd/cyberdeck-inventory.service" || fail "rootless unit should set UMask=0007"
env_mode_after="$(stat -c %a "$WORK/etc/cyberdeck-inventory.env")"
[[ "$env_mode_after" == "$env_mode_before" ]] || fail "update changed the env file mode"

# Schema change: keep the new release and tell the operator to restore a backup.
setup_tree
rev1="$REV_OUT"
git -C "$ORIGIN" -c user.email=test@example.com -c user.name=test commit --allow-empty -m migrated >/dev/null
newrev="$(git -C "$ORIGIN" rev-parse HEAD)"
COUNT="$WORK/schema-count"
echo 1 >"$COUNT"
SCHEMA="$(mktemp)"
cat >"$SCHEMA" <<EOF
#!/bin/bash
n=\$(cat "$COUNT")
echo "rev\$n"
echo \$((n + 1)) > "$COUNT"
EOF
chmod +x "$SCHEMA"
export INVENTORY_SCHEMA_CMD="$SCHEMA"
set +e
bash "$ROOT/scripts/update.sh" >"$WORK/update-migrate.out" 2>"$WORK/update-migrate.err"
migrate_code=$?
set -e
[[ "$migrate_code" -ne 0 ]] || fail "migrated health failure should be nonzero"
[[ "$(readlink -f "$WORK/opt/current")" == "$WORK/opt/releases/$newrev" ]] || fail "schema change should keep the new release"
grep -q 'does not downgrade' "$WORK/update-migrate.err" || fail "schema change should explain that the database is not downgraded"
grep -q 'restore.sh' "$WORK/update-migrate.err" || fail "schema change should print the restore command"
[[ "$(cat "$WORK/var/inventory.db")" == "database-bytes" ]] || fail "schema-change failure erased the database"

# fix_data_permissions is repeatable, keeps bytes, and does not follow a symlink
# out of the data directory or change the env file.
perm_root="$(mktemp -d)"
export INVENTORY_ROOT="$perm_root"
prefix_paths
mkdir -p "$VAR_DIR"
printf 'preserved-row' >"$DB_PATH"
chmod 600 "$DB_PATH"
printf 'wide' >"$VAR_DIR/wide.db"
chmod 666 "$VAR_DIR/wide.db"
secret="$(mktemp)"
chmod 600 "$secret"
ln -s "$secret" "$VAR_DIR/leak"
env_copy="$perm_root/etc/cyberdeck-inventory.env"
mkdir -p "$(dirname "$env_copy")"
printf 'token\n' >"$env_copy"
chmod 640 "$env_copy"
fix_data_permissions
fix_data_permissions
[[ "$(cat "$DB_PATH")" == "preserved-row" ]] || fail "permission repair changed database bytes"
[[ "$(stat -c %a "$DB_PATH")" == "660" ]] || fail "permission repair should set the database to 660"
[[ "$(stat -c %a "$VAR_DIR/wide.db")" == "660" ]] || fail "permission repair should clear world bits"
[[ "$(stat -c %a "$VAR_DIR")" == "2770" ]] || fail "permission repair should set the data directory to 2770"
[[ "$(stat -c %a "$BACKUP_DIR")" == "2770" ]] || fail "permission repair should set the backup directory to 2770"
[[ "$(stat -c %a "$secret")" == "600" ]] || fail "permission repair followed a symlink out of the data directory"
[[ "$(stat -c %a "$env_copy")" == "640" ]] || fail "permission repair changed the env file"
rm -rf "$perm_root"
rm -f "$secret"

awk '
  /saved_umask=/ { saved = 1 }
  /umask 0077/ { restrictive = 1 }
  /umask "\$saved_umask"/ { restored = 1 }
  END { exit !(saved && restrictive && restored) }
' "$ROOT/scripts/install.sh" || fail "install.sh must restore the caller's umask after writing the env file"

bash "$ROOT/scripts/tests/test_group_access.sh"

echo "deployment script checks passed"
