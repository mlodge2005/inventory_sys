# Recovery

## Backup

```bash
sudo ./scripts/backup.sh
sudo ./scripts/backup.sh /var/lib/cyberdeck-inventory/backups/manual.db
```

The copy is made with SQLite's backup API, then `PRAGMA integrity_check`. A sidecar `manual.db.json` stores the UTC timestamp, application version, Alembic revision, byte size, and SHA-256. Do not copy only `inventory.db` while the service is running. Pages can still be in the WAL.

Backups are also written to `/var/lib/cyberdeck-inventory/backups/pre-update-TIMESTAMP.db` before a migration.

## Restore

Stop is handled by the script. You must pass `--yes`.

```bash
sudo ./scripts/restore.sh /var/lib/cyberdeck-inventory/backups/pre-update-TIMESTAMP.db --yes
```

The script checks the checksum when the sidecar is present, writes the backup into place with the backup API, and keeps the previous database as `inventory.before-restore-TIMESTAMP.db`. That safety copy is a full snapshot. The old WAL is moved aside under a name SQLite will not replay onto the snapshot. Nothing is deleted automatically.

Confirm with:

```bash
sudo ./scripts/healthcheck.sh
sudo python3 -m app.maintenance integrity --database /var/lib/cyberdeck-inventory/inventory.db
```

The second command needs `PYTHONPATH` pointed at the active `backend` directory, or run it with the virtualenv after `cd /opt/cyberdeck-inventory/current/backend` and the env file loaded. `healthcheck.sh` already does both the HTTP check and the integrity check.

## Failed update

`update.sh` returns nonzero. It does not delete `inventory.db`.

- If the Alembic revision is the same as before the attempt, the previous release symlink and virtualenv are put back and the service is started again.
- If the revision changed, the new code stays. The previous code is not started, because it may not understand the new schema. The script prints the pre-update backup path. Restore that file with `restore.sh` if you need the old data. Do not run `alembic downgrade` against a database you have not restored. A downgrade is not part of the recovery path.

Useful commands after a failure:

```bash
journalctl -u cyberdeck-inventory.service -n 80 --no-pager
sudo ./scripts/healthcheck.sh
ls -l /var/lib/cyberdeck-inventory /var/lib/cyberdeck-inventory/backups
readlink -f /opt/cyberdeck-inventory/current
```

The lock directory `/opt/cyberdeck-inventory/.update.lock` is removed when the script exits. If a script was killed and the next run says the lock is held, remove that directory only after you are sure no install or update is running.

## Service restart

```bash
sudo systemctl restart cyberdeck-inventory.service
```

The database is a file. A restart does not empty it. Confirm with `inventory status` or the health URL.

## Disk full during an update

The update stops before it replaces the live release when free space is under `INVENTORY_MIN_FREE_KB` (default 700000 KB, because `npm ci` is large). The running service is left as it was.
