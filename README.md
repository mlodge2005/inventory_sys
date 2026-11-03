# Cyberdeck Inventory

Local inventory for numbered drawers of fasteners, threaded inserts, magnets, electronic parts, and other hardware. It runs on a Raspberry Pi 3 (Debian 13, ARM64) as its own systemd service. The database stays on the Pi. There is no account system in version 1, no cloud database, and no telemetry.

The website and the `inventory` command share one stock service. Restocking never changes the original baseline. Every quantity change is a transaction.

## What you can do

- Create drawers such as 110 and 111, put more than one part in a drawer, and put one part in more than one drawer.
- Rename drawer 110 without losing its contents.
- Add, remove, transfer, and adjust pieces. A change that would go negative is rejected.
- See low-stock and out-of-stock parts. The default alert is 10% of the baseline, rounded up, unless you set an absolute override.
- Search, filter, and page the catalog in the browser or the terminal.
- Export and import CSV. An import is previewed and then committed as a whole.
- Change the site colors. Presets are Dark, Light, Cyberpunk, and High Contrast. A custom palette is checked for contrast.
- Print a QR code in the terminal that points at the site on your LAN or Tailscale address.

## Screens

The default theme is a dark technical dashboard.

- **Home** shows counts for active parts, occupied drawers, units, low stock, and out of stock. Each count opens the matching list. A stock form and the latest transactions sit underneath.
- **Parts** is a table with search, category, status, drawer, and sort. Creating a part asks for a baseline separately from an optional first allocation into a drawer.
- **Part detail** shows the baseline, the threshold, each drawer, specifications, stock history, and the audit trail for baseline edits.
- **Drawers** finds a drawer by number and lists what is inside. Renaming the number keeps the stock. Deleting a drawer that still has parts requires an explicit confirmation that writes removal transactions.
- **Alerts** lists out-of-stock parts first. Restock adds pieces and leaves the baseline alone.
- **History** filters the append-only transaction log.
- **Settings** edits the name, landing page, default percent for new parts, public URL, and colors. You can save colors for every browser or only this one.
- **Import** previews CSV and commits only after a clean preview.

On a phone, the side navigation becomes a bottom bar. Tables stack into labeled rows. Buttons and inputs are at least 44 pixels tall. Stock status uses the words "In stock", "Low stock", and "Out of stock" in addition to color.

## Requirements

- Raspberry Pi 3 or another Debian-family Linux host. The installer warns on anything that is not Debian 13 ARM64 and continues. Set `INVENTORY_ALLOW_UNSUPPORTED_OS=1` for a non-Debian system.
- Python 3.11 or newer, and Node.js 20 or newer to build the website. The Pi does not need Node after the build.
- `sudo` for the real install. The service then runs as the unprivileged user `cyberdeck`.
- A trusted LAN or Tailscale network. Do not publish the port.

This repository was developed on an x86_64 Linux host. Installation on Pi hardware, Tailscale reachability, and coexistence with a particular existing dashboard were not executed on a physical Raspberry Pi in this environment.

## Install

From a git checkout:

```bash
sudo ./scripts/install.sh
```

The script is safe to run again. It keeps an existing `/etc/cyberdeck-inventory.env` and the database. It will not stop another program that is using the selected port.

Then open a new SSH login so your user picks up the `cyberdeck` group, and run:

```bash
inventory status
```

Details are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Configuration

`/etc/cyberdeck-inventory.env` holds the listen address, port, database path, and git branch. The installer creates it and does not overwrite it. An example is `deploy/inventory.env.example`.

Application name, theme, and the preferred public URL are edited in the website Settings page or stored in the database. They are not secrets. There is nowhere to put a password because version 1 does not have one.

Suggested port is 8765. The first install selects another free port if 8765 is busy.

## Open the website

```bash
inventory qr
```

prints a QR code and a URL such as `http://192.168.1.20:8765`. Use the address it prints. The program detects Ethernet, Wi-Fi, a Pi hotspot, and Tailscale IPv4. It does not assume the default route is the right host. When several addresses exist, the menu lets you choose. Set `INVENTORY_PUBLIC_URL` or the Settings field "Preferred public URL" to pin one.

On the Pi itself: `http://127.0.0.1:8765`.

From another device on the same LAN, use the LAN URL. From a machine on your tailnet, use the Tailscale URL. Both hit the same process when the service is bound to `0.0.0.0`. Do not enable Tailscale Funnel and do not forward the port on your router.

## Terminal

```bash
inventory
inventory slot create 110
inventory part create --name "M3 screw" --sku M3-SCREW --initial 100 --allocate 110:100
inventory part create --name "M3 nut" --sku M3-NUT --initial 80 --allocate 110:80
inventory remove --slot 110 --part M3-SCREW --quantity 5
inventory slot create 111
inventory transfer --from 110 --to 111 --part M3-SCREW --quantity 10
inventory low
inventory history
```

`inventory` with no arguments opens the menu on a terminal. See [docs/CLI.md](docs/CLI.md).

## Backup, restore, and update

```bash
sudo ./scripts/backup.sh
sudo ./scripts/restore.sh /var/lib/cyberdeck-inventory/backups/inventory-TIMESTAMP.db --yes
sudo ./scripts/update.sh
sudo ./scripts/healthcheck.sh
```

Updates back up the database, migrate, and restart only `cyberdeck-inventory.service`. A failed update does not delete the database. If the schema changed, restore the pre-update backup instead of downgrading in place. See [docs/RECOVERY.md](docs/RECOVERY.md).

Uninstall keeps the data unless you ask to purge it:

```bash
sudo ./scripts/uninstall.sh
sudo ./scripts/uninstall.sh --purge --yes
```

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-dev.txt -r backend/requirements-cli.txt
python -m pytest
cd frontend && npm ci && npm test && npm run build
bash scripts/tests/test_deploy.sh
```

Demo rows, clearly marked DEMO and not real stock:

```bash
INVENTORY_ENVIRONMENT=development INVENTORY_DATABASE_PATH=./data/dev.db inventory init
INVENTORY_ENVIRONMENT=development INVENTORY_DATABASE_PATH=./data/dev.db inventory devseed
```

`devseed` refuses to run when the environment is `production`.

## API

`/api/v1/` and `/openapi.json`. Send `X-Cyberdeck-Request: 1` on any change. Examples are in [docs/API.md](docs/API.md). The shared rules are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Tables are in [docs/DATABASE.md](docs/DATABASE.md).

## Troubleshooting

- **Port already used.** Read the port in `/etc/cyberdeck-inventory.env`. The installer will not kill the other listener.
- **`inventory` says the database is read-only.** Log out and back in so the `cyberdeck` group applies.
- **Website has no styling.** The frontend was not built. Run `sudo ./scripts/update.sh` or rebuild `frontend/dist` and set `INVENTORY_FRONTEND_DIST`.
- **Health check fails after an update.** `journalctl -u cyberdeck-inventory.service -n 80 --no-pager` and [docs/RECOVERY.md](docs/RECOVERY.md).
- **Low stock did not move after a restock.** The baseline is fixed. Change it on the part page or with `inventory part baseline`.
- **Two part types in one drawer.** `inventory remove 110 5` exits with code 4 and lists them. Pass `--part`.

## Further reading

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/DATABASE.md](docs/DATABASE.md)
- [docs/API.md](docs/API.md)
- [docs/CLI.md](docs/CLI.md)
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- [docs/RECOVERY.md](docs/RECOVERY.md)
