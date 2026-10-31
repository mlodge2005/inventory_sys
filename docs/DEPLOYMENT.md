# Deployment

This service is meant to sit beside other sites on the same Raspberry Pi. It installs only:

- `/opt/cyberdeck-inventory/` program files, releases, and a virtualenv
- `/var/lib/cyberdeck-inventory/` database and backups
- `/etc/cyberdeck-inventory.env`
- `/etc/systemd/system/cyberdeck-inventory.service`
- `/usr/local/bin/inventory`

It does not edit nginx, Caddy, other units, UFW, iptables, Tailscale, hostapd, or NetworkManager. It does not delete another process to free a port. If 8765 is taken, the first install picks the next free port from 8766 through 8799 and records it. Later installs keep the port already in the env file. If that port is later taken by something else, the installer stops and tells you to edit the file.

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

The data directory is `2770` and owned by `cyberdeck:cyberdeck`. SQLite's WAL and SHM files inherit the group. After installation, log in again before using `inventory` over SSH.
