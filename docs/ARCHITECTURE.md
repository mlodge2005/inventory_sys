# Architecture

Cyberdeck Inventory is one FastAPI process and one SQLite database. The website, the `inventory` command, and CSV import all call `InventoryService` in `backend/app/services/inventory.py`. That service is the only place that changes stock, drawers, parts, categories, or settings. The HTTP routes and the CLI validate input and present results. They do not keep a second set of stock rules.

```text
browser  --->  FastAPI /api/v1  --+
                                  +--> InventoryService --> SQLite
inventory CLI --------------------+
CSV import -----------------------+
```

The CLI opens the database itself. It keeps working when the web process is stopped, as long as the file is readable by the `cyberdeck` group. Do not run the CLI and a manual SQLite editor at the same time; the application already serializes writers with `BEGIN IMMEDIATE`.

## Processes

Production runs one uvicorn worker (`python -m app.main`). A second worker would only add write contention on a Raspberry Pi 3. The built React files are served by that same process from `frontend/dist`. The Pi does not run Vite.

Development can run `uvicorn` on `127.0.0.1` and `npm run dev` in `frontend/`, which proxies `/api` to port 8765.

## Stock rules

Physical quantity is the sum of `slot_inventory.quantity`. `parts.initial_quantity` is a baseline for alerts. Restocking, adding, removing, transferring, and adjusting never write that column. A person can change it from the part page or `inventory part baseline`. That edit is an audit row, not a stock transaction.

Creating a part does not put pieces in a drawer. The optional allocation on create, or a later Initial allocation action, writes an `INITIAL_STOCK` transaction.

Threshold, using integer arithmetic:

```text
threshold = low_stock_override
            if it is set
            else ceil(initial_quantity * low_stock_percent / 100)
```

`ceil` is `(n * percent + 99) // 100`. Status is `OUT_OF_STOCK` at quantity 0, `LOW_STOCK` when quantity is above 0 and at or below a configured threshold, and `IN_STOCK` otherwise. A zero baseline with no override sets `threshold_configured` false and `baseline_state` to `BASELINE_NOT_SET`. Quantity 0 is still out of stock.

Quantities are whole pieces. Fractional units need a future schema migration; the integer columns are deliberate.

## Transactions

Every stock change inserts one `stock_transactions` row inside the same database transaction as the quantity change. Negative results are rejected and the transaction rolls back. History is not rewritten. A correction is a new `ADJUST` row.

`quantity_before` and `quantity_after` describe the primary drawer slot, not the part total. For a transfer, the primary slot is the source and `dest_quantity_before` / `dest_quantity_after` describe the destination. Slot numbers are copied onto the row so renaming drawer 110 does not change old history. The foreign keys point at the stable slot id.

## Scale

Status filters and dashboard totals are computed in the service after loading the matching parts and their allocations. That is the right tradeoff for a personal cabinet of thousands of part types, not a warehouse system. Transaction history is paged in SQL.

## Network

The installer binds `0.0.0.0` so one process can answer the LAN and Tailscale. The development default is `127.0.0.1`. There is no authentication in version 1. Mutating requests must send `X-Cyberdeck-Request: 1`. That is a browser cross-site check, not a password. CORS stays empty unless `INVENTORY_ALLOWED_ORIGINS` lists origins. `/docs` is a local HTML page. OpenAPI is `/openapi.json` and does not load a CDN.

## Updates

`scripts/update.sh` builds a new release directory and a new virtualenv before it stops the service. It swaps the `current` symlink only after migrations. If the new process fails its health check and the schema revision did not change, the previous release is restored. If the schema changed, the old code is not started, because a downgraded process would not match the database. The database file is not deleted. See `docs/RECOVERY.md`.

## What this application does not do

It does not edit nginx, Caddy, other systemd units, UFW, iptables, Tailscale, hostapd, or NetworkManager. It does not open a port on the router or enable Tailscale Funnel. It does not send telemetry.
