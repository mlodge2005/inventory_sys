# HTTP API

Base path: `/api/v1/`. Machine-readable schema: `/openapi.json`. A short offline page is `/docs` (no CDN).

Version 1 has no login. Do not expose the port to the public internet. Every `POST`, `PATCH`, and `DELETE` needs:

```text
X-Cyberdeck-Request: 1
Content-Type: application/json
```

If the browser sends `Origin`, it must match the request host or `INVENTORY_ALLOWED_ORIGINS`. Errors use one envelope:

```json
{"error": {"code": "negative_stock", "message": "Cannot remove 15 screws from drawer 110. Only 8 are available.", "field": "quantity", "guidance": "Only 8 are available.", "details": {}}}
```

List responses are `{ "items", "total", "limit", "offset" }`. `limit` is at most 100 except low-stock, which allows 500.

## Health and stats

```bash
curl -s http://127.0.0.1:8765/api/v1/health
curl -s http://127.0.0.1:8765/api/v1/stats
```

`health` returns 200 when the database answers and 503 when it does not. `stats` includes `active_part_types`, `occupied_slots`, `total_units`, `low_stock_part_types`, `out_of_stock_part_types`, `archived_part_types`, and `drawer_count`.

## Parts

```bash
curl -s 'http://127.0.0.1:8765/api/v1/items?search=M3&category=Fasteners&status=LOW_STOCK&slot=110'
curl -s http://127.0.0.1:8765/api/v1/items/PART_ID
curl -s -X POST http://127.0.0.1:8765/api/v1/items \
  -H 'Content-Type: application/json' -H 'X-Cyberdeck-Request: 1' \
  -d '{"name":"M3 x 10mm screw","sku":"M3-10","initial_quantity":100,"allocations":[{"slot_number":110,"quantity":100}]}'
curl -s -X PATCH http://127.0.0.1:8765/api/v1/items/PART_ID \
  -H 'Content-Type: application/json' -H 'X-Cyberdeck-Request: 1' \
  -d '{"initial_quantity":80,"low_stock_percent":10}'
```

`initial_quantity` on create is the baseline. `allocations` are the only way that request creates physical stock (`INITIAL_STOCK`). A later add or restock does not change the baseline.

Part JSON includes `current_quantity`, `threshold`, `threshold_configured`, `baseline_state` (`OK` or `BASELINE_NOT_SET`), `status`, and `slots`.

```text
POST   /api/v1/items/{id}/archive     {"confirm_remove_stock": false}
POST   /api/v1/items/{id}/unarchive
DELETE /api/v1/items/{id}              409 if any stock or history remains
GET    /api/v1/items/{id}/transactions
GET    /api/v1/items/{id}/audit
```

## Drawers

```bash
curl -s -X POST http://127.0.0.1:8765/api/v1/slots \
  -H 'Content-Type: application/json' -H 'X-Cyberdeck-Request: 1' \
  -d '{"slot_number":110,"label":"Screws"}'
curl -s http://127.0.0.1:8765/api/v1/slots/110
curl -s -X PATCH http://127.0.0.1:8765/api/v1/slots/110 \
  -H 'Content-Type: application/json' -H 'X-Cyberdeck-Request: 1' \
  -d '{"slot_number":210}'
```

Archive and delete accept `{"confirm_remove_stock": true}` when the drawer still has parts. Without that flag a non-empty drawer returns 409 `not_empty`. Delete records a `REMOVE` for each remaining part, then removes the drawer. History keeps the slot-number snapshot.

## Stock

```bash
curl -s -X POST http://127.0.0.1:8765/api/v1/stock/remove \
  -H 'Content-Type: application/json' -H 'X-Cyberdeck-Request: 1' \
  -d '{"part_id":"PART_ID","slot_number":110,"quantity":5}'
curl -s -X POST http://127.0.0.1:8765/api/v1/stock/add \
  -H 'Content-Type: application/json' -H 'X-Cyberdeck-Request: 1' \
  -d '{"part_id":"PART_ID","slot_number":110,"quantity":100,"transaction_type":"RESTOCK"}'
curl -s -X POST http://127.0.0.1:8765/api/v1/stock/transfer \
  -H 'Content-Type: application/json' -H 'X-Cyberdeck-Request: 1' \
  -d '{"part_id":"PART_ID","from_slot":110,"to_slot":111,"quantity":10}'
curl -s -X POST http://127.0.0.1:8765/api/v1/stock/adjust \
  -H 'Content-Type: application/json' -H 'X-Cyberdeck-Request: 1' \
  -d '{"part_id":"PART_ID","slot_number":110,"new_quantity":40}'
```

`transaction_type` for add is `ADD`, `RESTOCK`, or `INITIAL_STOCK`. A removal past zero returns 409 and leaves the stored quantity unchanged. `quantity_before` and `quantity_after` are the primary slot. `quantity_scope` is always `slot`.

## Other routes

```text
GET/POST        /api/v1/categories
PATCH/DELETE    /api/v1/categories/{id}
GET             /api/v1/transactions?transaction_type=REMOVE&slot=110&source=cli
GET             /api/v1/alerts/low-stock
GET/PATCH       /api/v1/settings
GET             /api/v1/themes
GET             /api/v1/network
GET             /api/v1/export/parts.csv
POST            /api/v1/import/preview
POST            /api/v1/import/commit
```

Palette keys are `bg`, `surface`, `text`, `muted`, `border`, `accent`, `accent_2`, `danger`, `warning`, `ok`, and `info`. `theme_preference` of `dark`, `light`, `cyberpunk`, or `high-contrast` copies that preset. `color_palette` stores a custom theme after contrast checks. Text on the background and text on the surface must be at least 4.5:1.

Import body fields: `categories_csv`, `slots_csv`, `parts_csv`, `allocations_csv`, `mode` (`create_only` or `update_metadata`), and `allocation_mode` (`add` or `skip_existing`). Preview does not write. Commit runs one database transaction. Allocation rows go through the normal stock service and do not rewrite history.

## Codes

| HTTP | code | Meaning |
| --- | --- | --- |
| 404 | not_found | Missing part or drawer |
| 409 | conflict | Duplicate SKU, drawer, or category |
| 409 | negative_stock | Removal or transfer exceeds the slot |
| 409 | not_empty | Drawer or category still referenced |
| 409 | history_exists | Part delete blocked by transactions |
| 409 | ambiguous | More than one part matched |
| 422 | validation_error | Bad quantity, color, or field |
| 403 | forbidden | Missing request header or foreign Origin |
| 413 | payload_too_large | Body above 2 MB |
