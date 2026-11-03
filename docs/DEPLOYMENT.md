# Deployment

This service is meant to sit beside other sites on the same Raspberry Pi. It installs only:

- `/opt/cyberdeck-inventory/` program files, releases, and a virtualenv
- `/var/lib/cyberdeck-inventory/` database and backups
- `/etc/cyberdeck-inventory.env`
- `/etc/systemd/system/cyberdeck-inventory.service`
- `/usr/local/bin/inventory`

The installer also installs `iproute2` when it is missing. `inventory qr` reads interface addresses from `ip addr` and does not assume the default route is the site address. It does not edit nginx, Caddy, other units, UFW, iptables, Tailscale, hostapd, or NetworkManager. It does not delete another process to free a port. If 8765 is taken, the first install picks the next free port from 8766 through 8799 and records it. Later installs keep the port already in the env file. If that port is later taken by something else, the installer stops and tells you to edit the file.

## Layout

```text
/opt/cyberdeck-inventory/repo          git checkout used by update.sh
/opt/cyberdeck-inventory/releases/SHA  unpacked release
/opt/cyberdeck-inventory/current       symlink to the active release
/opt/cyberdeck-inventory/venv          dependencies only; code comes from current
/var/lib/cyberdeck-inventory/inventory.db
```

The systemd unit runs as user `cyberdeck`, not root. `MemoryDenyWriteExecute` is omitted because CPython cannot start with it. `ProtectSystem=strict` and `ReadWritePaths=/var/lib/cyberdeck-inventory` keep the process away from other site data. One worker. Logs go to the journal:

```bash
journalctl -u cyberdeck-inventory.service -n 80 --no-pager
```

## Network

`INVENTORY_HOST=0.0.0.0` listens on every IPv4 interface. That is what lets a phone on the LAN and a laptop on Tailscale use one process. It also listens on any public address that is configured on the Pi. The installer prints those addresses when it finds them. Do not forward the port on the router. Do not run `tailscale funnel`.

Version 1 has no passwords. Treat the LAN and your tailnet as the trust boundary.

IPv6 is not bound. If you filter with UFW, apply the rule yourself. Replace `PORT` with the value in `/etc/cyberdeck-inventory.env`:

```bash
sudo ufw allow from 10.0.0.0/8 to any port PORT proto tcp
sudo ufw allow from 192.168.0.0/16 to any port PORT proto tcp
sudo ufw allow from 172.16.0.0/12 to any port PORT proto tcp
sudo ufw allow from 100.64.0.0/10 to any port PORT proto tcp
```

The installer never runs those commands.

## Updates

`scripts/update.sh` fetches `INVENTORY_GIT_REMOTE` / `INVENTORY_GIT_BRANCH` from the env file (default `origin` / `main`). It refuses a dirty `/opt/cyberdeck-inventory/repo`. It does not run `git reset --hard` or `git clean`. It builds the new release in `releases/SHA` while the old process is still running, tests against a temporary database, backs up the live database, stops only `cyberdeck-inventory.service`, migrates, switches the symlink, and starts only that unit.

Set `INVENTORY_SKIP_TESTS=1` only when you must update without the test run. The database is still backed up first.

## Uninstall

```bash
sudo ./scripts/uninstall.sh
```

This removes the unit, the `/opt` tree, and `/usr/local/bin/inventory`. The database, backups, and env file stay. To delete those as well:

```bash
sudo ./scripts/uninstall.sh --purge --yes
```

## Reinstall

Run `install.sh` again. An existing env file and database are kept. Migrations run again. The service restarts.

## Permissions

| Path | Owner | Mode |
| --- | --- | --- |
| `/var/lib/cyberdeck-inventory` | `cyberdeck:cyberdeck` | `2770` |
| `/var/lib/cyberdeck-inventory/backups` | `cyberdeck:cyberdeck` | `2770` |
| `inventory.db` | `cyberdeck:cyberdeck` | `0660` |
| `inventory.db-wal`, `inventory.db-shm`, `inventory.db-journal` | `cyberdeck:cyberdeck` | `0660` |
| Backup `*.db` files and the `.json` metadata beside them | `cyberdeck:cyberdeck` | `0660` |
| `/etc/cyberdeck-inventory.env` | `root:cyberdeck` | `0640` |

`2770` means the service account and the `cyberdeck` group can read, write, and search the directory. The setgid bit puts new files in group `cyberdeck`. `0660` means the owner and that group can read and write the file. No other user can read or write the directory, the database, the WAL, the shared-memory file, or a backup.

SQLite creates the database, WAL, and shared-memory files with mode `0644`. A process umask can only remove bits, so it cannot add group write. `UMask=0007` therefore leaves those files at `0640` (group read, no group write). `umask 0077`, which the installer used to leave in effect while creating the database, leaves them at `0600`. That is the failure on an existing Pi: `cyberdeck-inventory.service` runs as `cyberdeck` and can open the file, while `admin` is only in the group and cannot. The unit and the `serve` and `inventory` wrappers still set umask `0007`, so files this process creates are not world-readable. `app.db.permissions` then sets mode `0660` after SQLite creates or reopens the database and its sidecar files.

`scripts/install.sh`, `scripts/update.sh`, and `scripts/restore.sh` run `fix_data_permissions`, which is safe to repeat. It chowns the data directory to `cyberdeck:cyberdeck`, sets directories to `2770`, and sets regular files under that directory to `0660`. It does not follow symlinks out of the directory and does not change `/etc/cyberdeck-inventory.env`. Restarting the service repairs the same files when the service account owns them. None of these paths delete inventory rows.

`admin` still has to be in group `cyberdeck` and has to log in again after that membership is added. Do not run the `inventory` command as root.
