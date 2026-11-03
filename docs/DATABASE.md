# Database

SQLite file, WAL mode, `synchronous=FULL`, `busy_timeout=30000`, foreign keys on. The production path is `/var/lib/cyberdeck-inventory/inventory.db`. The repository does not contain a database.

## Permissions

The data directory is mode `2770`, owner `cyberdeck:cyberdeck`. The database and its `-wal`, `-shm`, and `-journal` files are mode `0660` with the same owner and group. Backups and their `.json` metadata use `0660` as well. Nothing in this tree is world-readable or world-writable.

SQLite requests mode `0644` for those files. Umask `0007` can only turn that into `0640`, and umask `0077` turns it into `0600`. Group write has to be added after SQLite creates the file. The service does that on every connection, and `scripts/install.sh`, `scripts/update.sh`, and `scripts/restore.sh` do it again so an existing installation is repaired without deleting rows. A member of group `cyberdeck` can then open the database with `inventory`. The account still has to log in again after being added to the group. Do not run the CLI as root to get around a mode `0600` file; restart `cyberdeck-inventory.service` or re-run the installer so the file owner can change the mode.

Alembic revision `262e4fbd99ff` creates the tables, the case-insensitive unique indexes, and the reference rows (nine categories and one settings row). It does not insert parts. `scripts/update.sh` and `scripts/install.sh` back up with SQLite's backup API before migrating, then run `PRAGMA integrity_check`.

## Tables

### categories

| Column | Notes |
| --- | --- |
| id | UUID string, primary key |
| name | Unique case-insensitively |
| description, color | Optional. Color is `#RRGGBB` when set |
| created_at, updated_at | UTC |

Seeded names: Fasteners, Threaded Inserts, Magnets, Electronic Components, Sensors, Motors, Wiring, Tools, Miscellaneous. They can be renamed or deleted. Deleting a category that still has parts returns 409 unless the caller reassigns or clears those links.

### parts

| Column | Notes |
| --- | --- |
| id | UUID string |
| sku | Optional, unique case-insensitively |
| name | Required. Not unique |
| category_id | Optional, `ON DELETE RESTRICT` |
| manufacturer, manufacturer_part_number, notes | Optional |
| specifications_json | JSON object, size-capped |
| unit | Default `pcs` |
| initial_quantity | Nonnegative baseline. Not a live count |
| low_stock_percent | Copied from the default at creation |
| low_stock_override | Optional absolute threshold |
| archived_at | Set when archived |

There is no `current_quantity` column. The API computes it as `SUM(slot_inventory.quantity)`.

### slots

| Column | Notes |
| --- | --- |
| id | Stable primary key |
| slot_number | Unique positive integer. User-editable |
| label, description, location | Optional |
| archived_at | Optional |

Drawer numbers are not assumed to be contiguous. Inventory rows reference `slots.id`, so changing 110 to 210 keeps the parts.

### slot_inventory

| Column | Notes |
| --- | --- |
| id | UUID |
| slot_id, part_id | Unique together. Both `ON DELETE RESTRICT` |
| quantity | Nonnegative integer |

A quantity of zero deletes the row. A part may appear in many drawers. A drawer may contain many parts.

### stock_transactions

Append-only through the application. Slot foreign keys are `ON DELETE SET NULL` so a drawer deleted after its stock was removed can disappear without deleting history. `from_slot_number` and `to_slot_number` keep the numbers that were current at the time.

| Column | Notes |
| --- | --- |
| transaction_type | `INITIAL_STOCK`, `ADD`, `REMOVE`, `TRANSFER`, `ADJUST`, `RESTOCK` |
| quantity | Pieces involved, nonnegative |
| quantity_delta | Signed change on the primary slot |
| quantity_before, quantity_after | Primary slot quantity, not the part total |
| dest_quantity_before, dest_quantity_after | Transfer destination only |
| source | `web`, `cli`, `api`, `migration`, or `import` |
| part_name_snapshot, part_sku_snapshot | Copied at write time |

The primary slot is the destination for `INITIAL_STOCK`, `ADD`, `RESTOCK`, and `ADJUST`. It is the source for `REMOVE` and `TRANSFER`.

### audit_events

Baseline and metadata edits. `changes_json` stores `{field: {old, new}}`. Stock movements do not go here.

### app_settings

A single row, `id = 1`. Application name, theme name, palette JSON, default low-stock percent, landing page, display preferences, and optional preferred public URL. No secrets. The listen port and database path live in `/etc/cyberdeck-inventory.env`.

## Migrations

```text
cd backend
alembic upgrade head
```

The installer sets `INVENTORY_DATABASE_PATH` first. Downgrade is implemented for development and is not used by `update.sh`. A failed production update does not run a schema downgrade.

## Backups

Copying `inventory.db` alone while WAL mode is on can miss committed pages. Use `scripts/backup.sh` or `python -m app.maintenance backup`. Each backup is a standalone database plus a `.json` sidecar with timestamp, application version, Alembic revision, size, and SHA-256.

## Fractional quantities

All quantity columns are integers. Supporting partial pieces later means a new Alembic revision that changes those columns and the service checks together. Do not store tenths of a piece in the integer fields.
