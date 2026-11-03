"""Rich tables for inventory views."""

from __future__ import annotations

import json
from datetime import datetime

from rich.console import Console
from rich.table import Table


def emit_json(payload) -> None:
    print(json.dumps(payload, indent=2, default=_json_default))


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Cannot encode {type(value)!r}")


def parts_table(console: Console, views: list[dict]) -> None:
    table = Table(title="Inventory", show_lines=False)
    table.add_column("Name")
    table.add_column("SKU")
    table.add_column("Qty", justify="right")
    table.add_column("Baseline", justify="right")
    table.add_column("Threshold", justify="right")
    table.add_column("Status")
    table.add_column("Drawers")
    for view in views:
        drawers = ", ".join(f"{slot['slot_number']}×{slot['quantity']}" for slot in view["slots"]) or "-"
        threshold = "-" if view["threshold"] is None else str(view["threshold"])
        if view["baseline_state"] == "BASELINE_NOT_SET":
            threshold = "not set"
        table.add_row(
            view["name"],
            view["sku"] or "",
            str(view["current_quantity"]),
            str(view["initial_quantity"]),
            threshold,
            view["status"],
            drawers,
        )
    console.print(table)


def transactions_table(console: Console, rows: list[dict]) -> None:
    table = Table(title="Transactions")
    table.add_column("When")
    table.add_column("Type")
    table.add_column("Part")
    table.add_column("From", justify="right")
    table.add_column("To", justify="right")
    table.add_column("Qty", justify="right")
    table.add_column("Source")
    for row in rows:
        created = row["created_at"]
        stamp = created.isoformat(timespec="seconds") if hasattr(created, "isoformat") else str(created)
        table.add_row(
            stamp,
            row["transaction_type"],
            row["part_sku"] or row["part_name"],
            "-" if row["from_slot_number"] is None else str(row["from_slot_number"]),
            "-" if row["to_slot_number"] is None else str(row["to_slot_number"]),
            str(row["quantity_delta"]),
            row["source"],
        )
    console.print(table)


def slot_table(console: Console, slot: dict) -> None:
    title = f"Drawer {slot['slot_number']}"
    if slot.get("label"):
        title += f" — {slot['label']}"
    table = Table(title=title)
    table.add_column("Part")
    table.add_column("SKU")
    table.add_column("Qty", justify="right")
    for item in slot["items"]:
        table.add_row(item["name"], item["sku"] or "", str(item["quantity"]))
    if not slot["items"]:
        console.print(f"{title}\nThis drawer is empty.")
        return
    console.print(table)
    console.print(f"Total units: {slot['total_units']}")
