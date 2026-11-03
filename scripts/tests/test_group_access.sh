#!/usr/bin/env bash
# Prove a second member of the application group can use the CLI, and that
# an account outside the group cannot read the database.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

if [[ "$(id -u)" -ne 0 ]]; then
  if ! sudo -n true 2>/dev/null; then
    if [[ -n "${CI:-}" ]]; then
      fail "group-access test needs passwordless sudo"
    fi
    printf 'SKIP: group-access test needs passwordless sudo\n'
    exit 0
  fi
  exec sudo -n env \
    CI="${CI:-}" \
    INVENTORY_TEST_PYTHON="${INVENTORY_TEST_PYTHON:-}" \
    bash "$0"
fi

tag="$$"
group="cdg${tag}"
owner="cdo${tag}"
cli_user="cdc${tag}"
outsider="cdx${tag}"
WORK=""
holder_pid=""

cleanup() {
  if [[ -n "$holder_pid" ]]; then
    kill "$holder_pid" 2>/dev/null || true
    wait "$holder_pid" 2>/dev/null || true
  fi
  local user
  for user in "$cli_user" "$owner" "$outsider"; do
    if id "$user" >/dev/null 2>&1; then
      userdel "$user" >/dev/null 2>&1 || true
    fi
  done
  if getent group "$group" >/dev/null 2>&1; then
    groupdel "$group" >/dev/null 2>&1 || true
  fi
  if [[ -n "$WORK" && -d "$WORK" ]]; then
    rm -rf "$WORK"
  fi
}
trap cleanup EXIT

groupadd --system "$group"
useradd --system --gid "$group" --no-create-home --shell /usr/sbin/nologin "$owner"
useradd --system --no-create-home --shell /usr/sbin/nologin "$cli_user"
usermod -aG "$group" "$cli_user"
useradd --system --no-create-home --shell /usr/sbin/nologin "$outsider"

id_groups="$(sudo -u "$cli_user" id -nG)"
[[ "$id_groups" == *"$group"* ]] || fail "CLI user is missing supplementary group $group"
[[ "$(sudo -u "$cli_user" id -gn)" != "$group" ]] || fail "CLI user should use the application group as a supplementary group"
if sudo -u "$outsider" id -nG | tr ' ' '\n' | grep -qx "$group"; then
  fail "outsider is in the application group"
fi

WORK="$(mktemp -d /tmp/cd-group-XXXXXX)"
chmod 755 "$WORK"
mkdir -p "$WORK/home"
chmod 777 "$WORK/home"
export PYTHONDONTWRITEBYTECODE=1
export HOME="$WORK/home"
DATA="$WORK/data"
mkdir -p "$DATA"
chown "$owner:$group" "$DATA"
chmod 2770 "$DATA"

PY="${INVENTORY_TEST_PYTHON:-}"
if [[ -z "$PY" && -x /tmp/cd-perm-venv/bin/python ]]; then
  chmod -R a+rX /tmp/cd-perm-venv
  PY="/tmp/cd-perm-venv/bin/python"
fi
if [[ -z "$PY" ]]; then
  PY="$(command -v python3)"
fi
if ! sudo -u "$cli_user" "$PY" -c 'import sqlalchemy, typer, rich' >/dev/null 2>&1; then
  python3 -m venv "$WORK/venv"
  "$WORK/venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt" -r "$ROOT/backend/requirements-cli.txt"
  chmod -R a+rX "$WORK/venv"
  PY="$WORK/venv/bin/python"
fi
sudo -u "$cli_user" "$PY" -c 'import sqlalchemy, typer, rich' >/dev/null

if sudo -u "$cli_user" test -r "$ROOT/backend/app/db/permissions.py"; then
  SRC="$ROOT"
else
  mkdir -p "$WORK/src"
  cp -a "$ROOT/backend" "$ROOT/cli" "$WORK/src/"
  chmod -R a+rX "$WORK/src"
  SRC="$WORK/src"
fi
export PYTHONPATH="$SRC/backend:$SRC/cli"

cat >"$WORK/create_private.py" <<'PY'
import os
import sqlite3
import sys

os.umask(0o077)
path = sys.argv[1]
connection = sqlite3.connect(path)
connection.execute("PRAGMA journal_mode=WAL")
connection.execute("CREATE TABLE marker (n INTEGER)")
connection.execute("INSERT INTO marker VALUES (42)")
connection.commit()
print(os.getpid(), flush=True)
sys.stdin.readline()
connection.close()
PY

mkfifo "$WORK/hold"
sudo --preserve-env=PYTHONDONTWRITEBYTECODE,HOME -u "$owner" "$PY" "$WORK/create_private.py" "$DATA/marker.db" <"$WORK/hold" >"$WORK/create.out" &
holder_pid=$!
exec 3>"$WORK/hold"
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  if [[ -s "$WORK/create.out" ]]; then
    break
  fi
  sleep 0.1
done
[[ -s "$WORK/create.out" ]] || fail "private database was not created"
python_pid="$(awk 'NR==1 { print $1 }' "$WORK/create.out")"
[[ "$(stat -c %a "$DATA/marker.db")" == "600" ]] || fail "expected the unrepaired database to be mode 600"
[[ "$(stat -c %a "$DATA/marker.db-wal")" == "600" ]] || fail "expected the unrepaired WAL to be mode 600"
[[ "$(stat -c %a "$DATA/marker.db-shm")" == "600" ]] || fail "expected the unrepaired SHM to be mode 600"
if sudo --preserve-env=PYTHONDONTWRITEBYTECODE,HOME -u "$cli_user" "$PY" -c 'import sqlite3,sys; sqlite3.connect(sys.argv[1]).execute("select n from marker")' "$DATA/marker.db" >/dev/null 2>&1; then
  fail "group member opened a mode 600 database"
fi

sudo --preserve-env=PYTHONDONTWRITEBYTECODE,PYTHONPATH,HOME -u "$owner" "$PY" - "$DATA/marker.db" <<'PY'
import sys
from pathlib import Path
from app.db.permissions import ensure_database_permissions
ensure_database_permissions(Path(sys.argv[1]))
ensure_database_permissions(Path(sys.argv[1]))
PY
[[ "$(stat -c %a "$DATA/marker.db")" == "660" ]] || fail "repaired database should be mode 660"
[[ "$(stat -c %a "$DATA/marker.db-wal")" == "660" ]] || fail "repaired WAL should be mode 660"
[[ "$(stat -c %a "$DATA/marker.db-shm")" == "660" ]] || fail "repaired SHM should be mode 660"
marker="$(sudo --preserve-env=PYTHONDONTWRITEBYTECODE,HOME -u "$owner" "$PY" -c 'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("select n from marker").fetchone()[0])' "$DATA/marker.db")"
[[ "$marker" == "42" ]] || fail "permission repair changed the stored row"

exec 3>&-
wait "$holder_pid" 2>/dev/null || true
holder_pid=""
kill "$python_pid" 2>/dev/null || true

sudo --preserve-env=PYTHONDONTWRITEBYTECODE,PYTHONPATH,HOME -u "$cli_user" "$PY" - "$DATA/marker.db" <<'PY'
import os
import stat
import sys
from pathlib import Path
from app.db.session import make_engine

path = Path(sys.argv[1])
engine = make_engine(path)
with engine.connect() as connection:
    connection.exec_driver_sql("UPDATE marker SET n = 43")
    connection.commit()
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{path}{suffix}")
        mode = stat.S_IMODE(candidate.stat().st_mode)
        if mode != 0o660:
            raise SystemExit(f"{candidate} mode is {mode:04o}")
        if mode & 0o007:
            raise SystemExit(f"{candidate} is world-accessible")
engine.dispose()
PY
seen="$(sudo --preserve-env=PYTHONDONTWRITEBYTECODE,HOME -u "$owner" "$PY" -c 'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("select n from marker").fetchone()[0])' "$DATA/marker.db")"
[[ "$seen" == "43" ]] || fail "service owner could not read the group member's write"
if sudo --preserve-env=PYTHONDONTWRITEBYTECODE,HOME -u "$outsider" "$PY" -c 'import sqlite3,sys; sqlite3.connect(sys.argv[1]).execute("select n from marker")' "$DATA/marker.db" >/dev/null 2>&1; then
  fail "outsider read the database"
fi

sudo --preserve-env=PYTHONDONTWRITEBYTECODE,PYTHONPATH,INVENTORY_DATABASE_PATH,INVENTORY_ENVIRONMENT,HOME -u "$owner" \
  env INVENTORY_DATABASE_PATH="$DATA/inventory.db" INVENTORY_ENVIRONMENT=development \
  "$PY" - <<'PY'
import os
from pathlib import Path
from app.core.config import Settings, get_settings
from app.db.session import init_database

os.umask(0o077)
get_settings.cache_clear()
init_database(
    Settings(environment="development", database_path=Path(os.environ["INVENTORY_DATABASE_PATH"])),
    migrate=True,
)
PY
[[ "$(stat -c %a "$DATA/inventory.db")" == "660" ]] || fail "migrated database should be mode 660"
[[ "$(stat -c %a "$DATA")" == "2770" ]] || fail "data directory should stay 2770"

status_out="$(sudo --preserve-env=PYTHONDONTWRITEBYTECODE,PYTHONPATH,HOME -u "$cli_user" \
  env INVENTORY_DATABASE_PATH="$DATA/inventory.db" INVENTORY_ENVIRONMENT=development \
  "$PY" -m inventory_cli status)"
printf '%s\n' "$status_out" | grep -q 'Cyberdeck Inventory' || fail "group member CLI could not read status"
printf '%s\n' "$status_out" | grep -q 'Active parts' || fail "group member CLI did not report stock counts"

sudo --preserve-env=PYTHONDONTWRITEBYTECODE,PYTHONPATH,HOME -u "$cli_user" \
  env INVENTORY_DATABASE_PATH="$DATA/inventory.db" INVENTORY_ENVIRONMENT=development \
  "$PY" - <<'PY'
from inventory_cli.context import open_service

with open_service() as service:
    service.create_slot(slot_number=110, label="group-write")
PY
label="$(sudo --preserve-env=PYTHONDONTWRITEBYTECODE,HOME -u "$owner" "$PY" -c 'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("select label from slots where slot_number=110").fetchone()[0])' "$DATA/inventory.db")"
[[ "$label" == "group-write" ]] || fail "service owner could not see the drawer created by the CLI user"
set +e
outsider_out="$(sudo --preserve-env=PYTHONDONTWRITEBYTECODE,PYTHONPATH,HOME -u "$outsider" \
  env INVENTORY_DATABASE_PATH="$DATA/inventory.db" INVENTORY_ENVIRONMENT=development \
  "$PY" -m inventory_cli status 2>&1)"
outsider_code=$?
set -e
[[ "$outsider_code" -ne 0 ]] || fail "outsider CLI opened the database"
printf '%s\n' "$outsider_out" | grep -q 'Cannot open the inventory database' || fail "outsider should see a permission message"
if printf '%s\n' "$outsider_out" | grep -q 'Traceback'; then
  fail "outsider should not see a traceback"
fi
for file in "$DATA/inventory.db" "$DATA/inventory.db-wal" "$DATA/inventory.db-shm"; do
  if [[ -e "$file" ]]; then
    mode="$(stat -c %a "$file")"
    [[ "$mode" == "660" ]] || fail "$file mode is $mode"
  fi
done

printf 'group-access checks passed\n'
