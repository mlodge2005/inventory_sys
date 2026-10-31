#!/usr/bin/env bash
# Update Cyberdeck Inventory without touching other services or deleting the database.
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$SOURCE_DIR/scripts/lib/common.sh"
prefix_paths
require_root_if_needed
require_linux
[[ -d "$REPO_DIR/.git" ]] || die "No installation repository at $REPO_DIR. Run scripts/install.sh first."
[[ -f "$ENV_FILE" ]] || die "Missing $ENV_FILE."

acquire_lock
old_revision="$(git -C "$REPO_DIR" rev-parse HEAD)"
log "Installed commit: $old_revision"
if repo_dirty; then
  git -C "$REPO_DIR" status --porcelain >&2
  die "Uncommitted changes in $REPO_DIR. Commit or stash them before updating. The updater will not discard local edits."
fi

remote="$(env_value INVENTORY_GIT_REMOTE)"
branch="$(env_value INVENTORY_GIT_BRANCH)"
remote="${remote:-${INVENTORY_GIT_REMOTE:-origin}}"
branch="${branch:-${INVENTORY_GIT_BRANCH:-main}}"
log "Fetching $remote $branch"
if ! git -C "$REPO_DIR" fetch "$remote" "$branch"; then
  die "Could not fetch $remote $branch. Check the network and $ENV_FILE."
fi
new_revision="$(git -C "$REPO_DIR" rev-parse "$remote/$branch")"
log "Available commit: $new_revision"
disk_ok

port="$(env_value INVENTORY_PORT)"
port="${port:-$DEFAULT_PORT}"
if port_in_use "$port" && ! service_is_active; then
  die "Port $port is used by another program. Edit $ENV_FILE. This updater will not stop that program."
fi

release="$RELEASES_DIR/$new_revision"
stage_tree "$release" "$new_revision"
build_frontend "$release"
make_venv "$VENV_STAGING" "$release"
run_release_tests "$release" "$VENV_STAGING/bin/python"

previous_release=""
if [[ -L "$CURRENT_LINK" ]]; then
  previous_release="$(readlink -f "$CURRENT_LINK" || true)"
fi
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_path="$BACKUP_DIR/pre-update-$stamp.db"
if [[ -f "$DB_PATH" ]]; then
  backup_now "$VENV_STAGING/bin/python" "$release" "$backup_path" >/dev/null
  log "Pre-update backup: $backup_path"
else
  log "No database yet at $DB_PATH"
fi

schema_before="$(schema_of "$VENV_DIR/bin/python" "${previous_release:-$release}")"
stop_service
apply_migrations "$VENV_STAGING/bin/python" "$release"
schema_after="$(schema_of "$VENV_STAGING/bin/python" "$release")"
activate_release "$release" "$VENV_STAGING"
start_service

if wait_for_health "$port"; then
  git -C "$REPO_DIR" merge --ff-only "$remote/$branch"
  prune_releases "$(basename "$release")" "$(basename "${previous_release:-$release}")"
  printf 'Updated %s -> %s\n' "$old_revision" "$new_revision"
  print_urls "$port" "$VENV_DIR/bin/python" "$CURRENT_LINK" "$(env_value INVENTORY_HOST)"
  exit 0
fi

log "Health check failed after activating $new_revision."
action="$(
  SCHEMA_BEFORE="$schema_before" SCHEMA_AFTER="$schema_after" \
    PYTHONPATH="${INVENTORY_PYTHONPATH:-$release/backend}" \
    "$VENV_DIR/bin/python" - <<'PY'
import os
from app.deploy_policy import health_failure_action
print(health_failure_action(schema_before=os.environ.get("SCHEMA_BEFORE", ""), schema_after=os.environ.get("SCHEMA_AFTER", "")))
PY
)"

log "Recovery action: $action"
log "The database was not deleted: $DB_PATH"
if [[ "$action" == "rollback_release" && -n "$previous_release" ]]; then
  log "Schema revision is unchanged ($schema_before). Restoring the previous release."
  stop_service
  rollback_release "$previous_release"
  start_service || true
  if wait_for_health "$port"; then
    log "Previous release is serving again. The failed release remains at $release."
  else
    log "Previous release did not become healthy. Inspect $OPT_DIR/service.log or journalctl -u $SERVICE_NAME -n 80 --no-pager"
  fi
else
  log "Schema changed from ${schema_before:-none} to ${schema_after:-none}."
  log "The new release stays active because starting the old code could misread the migrated database."
  log "This updater does not downgrade a database."
  log "To return to the previous data, restore the pre-migration backup:"
  log "  sudo $SOURCE_DIR/scripts/restore.sh $backup_path"
  log "Then check out the previous commit and reinstall that release only after the restore."
fi
log "Diagnostics: journalctl -u $SERVICE_NAME -n 80 --no-pager"
log "Diagnostics: python3 -m app.maintenance integrity --database $DB_PATH"
exit 1
