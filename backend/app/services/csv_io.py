"""CSV import and export through InventoryService.

Imports validate the whole file before any write. A failed import raises and
the caller's database transaction rolls back. Importing allocations records
stock transactions; it never assigns quantities with a raw update.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from app.core.constants import MAX_IMPORT_ROWS
from app.core.errors import InventoryError
from app.services.inventory import InventoryService
from app.utils.color import normalize_hex

PART_COLUMNS = [
    "sku",
    "name",
    "description",
    "category",
    "manufacturer",
    "manufacturer_part_number",
    "unit",
    "initial_quantity",
    "low_stock_percent",
    "low_stock_override",
    "notes",
    "specifications_json",
]
SLOT_COLUMNS = ["slot_number", "label", "description", "location"]
ALLOCATION_COLUMNS = ["slot_number", "part_sku", "part_name", "quantity"]
CATEGORY_COLUMNS = ["name", "description", "color"]


@dataclass
class ImportPlan:
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    operations: list[tuple] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "summary": self.summary,
            "rows": self.summary.get("rows", 0),
        }


def export_csv(service: InventoryService, kind: str) -> str:
    if kind == "parts":
        views, _total = service.list_part_views(include_archived=True, limit=-1)
        rows = []
        for view in views:
            category = view["category"]["name"] if view["category"] else ""
            specs = view["specifications"] or {}
            import json

            rows.append(
                {
                    "sku": view["sku"] or "",
                    "name": view["name"],
                    "description": view["description"] or "",
                    "category": category,
                    "manufacturer": view["manufacturer"] or "",
                    "manufacturer_part_number": view["manufacturer_part_number"] or "",
                    "unit": view["unit"],
                    "initial_quantity": view["initial_quantity"],
                    "low_stock_percent": view["low_stock_percent"],
                    "low_stock_override": "" if view["low_stock_override"] is None else view["low_stock_override"],
                    "notes": view["notes"] or "",
                    "specifications_json": json.dumps(specs, separators=(",", ":")) if specs else "",
                }
            )
        return _write(PART_COLUMNS, rows)
    if kind == "slots":
        slots, _total = service.list_slots(include_archived=True, limit=100_000, offset=0)
        return _write(
            SLOT_COLUMNS,
            [
                {
                    "slot_number": slot["slot_number"],
                    "label": slot["label"] or "",
                    "description": slot["description"] or "",
                    "location": slot["location"] or "",
                }
                for slot in slots
            ],
        )
    if kind == "allocations":
        views, _total = service.list_part_views(include_archived=True, limit=-1)
        rows = []
        for view in views:
            for slot in view["slots"]:
                rows.append(
                    {
                        "slot_number": slot["slot_number"],
                        "part_sku": view["sku"] or "",
                        "part_name": view["name"],
                        "quantity": slot["quantity"],
                    }
                )
        return _write(ALLOCATION_COLUMNS, rows)
    if kind == "categories":
        return _write(
            CATEGORY_COLUMNS,
            [
                {
                    "name": category["name"],
                    "description": category["description"] or "",
                    "color": category["color"] or "",
                }
                for category in service.list_categories()
            ],
        )
    if kind == "transactions":
        rows, _total = service.list_transactions(limit=100_000, offset=0)
        columns = [
            "created_at",
            "transaction_type",
            "part_name",
            "part_sku",
            "from_slot_number",
            "to_slot_number",
            "quantity",
            "quantity_delta",
            "quantity_before",
            "quantity_after",
            "source",
            "reason",
        ]
        exported = []
        for row in rows:
            exported.append(
                {
                    key: "" if row[key] is None else row[key].isoformat() if hasattr(row[key], "isoformat") else row[key]
                    for key in columns
                }
            )
        return _write(columns, exported)
    raise InventoryError("validation_error", "Unknown CSV export.", 422)


def plan_bundle(
    service: InventoryService,
    *,
    categories_csv: str | None = None,
    slots_csv: str | None = None,
    parts_csv: str | None = None,
    allocations_csv: str | None = None,
    mode: str = "create_only",
    allocation_mode: str = "add",
) -> ImportPlan:
    if mode not in {"create_only", "update_metadata"}:
        raise InventoryError("validation_error", "Import mode must be create_only or update_metadata.", 422)
    if allocation_mode not in {"add", "skip_existing"}:
        raise InventoryError("validation_error", "Allocation mode must be add or skip_existing.", 422)
    plan = ImportPlan(summary={"rows": 0, "create": 0, "update": 0, "stock_transactions": 0, "skip": 0})
    if categories_csv:
        _plan_categories(service, categories_csv, mode, plan)
    if slots_csv:
        _plan_slots(service, slots_csv, mode, plan)
    if parts_csv:
        _plan_parts(service, parts_csv, mode, plan)
    if allocations_csv:
        _plan_allocations(service, allocations_csv, allocation_mode, plan)
    if plan.summary["rows"] == 0 and not plan.errors:
        plan.errors.append({"row": 0, "file": "bundle", "message": "Import did not contain any data rows."})
    return plan


def apply_plan(service: InventoryService, plan: ImportPlan) -> dict:
    if not plan.ok:
        raise InventoryError(
            "validation_error",
            "Import was not applied because it contains errors.",
            422,
            {"errors": plan.errors},
        )
    for op, payload in plan.operations:
        if op == "category_create":
            service.create_category(**payload)
        elif op == "category_update":
            service.update_category(payload.pop("id"), payload)
        elif op == "slot_create":
            service.create_slot(**payload)
        elif op == "slot_update":
            number = payload.pop("slot_number")
            service.update_slot(number, payload)
        elif op == "part_create":
            service.create_part(payload)
        elif op == "part_update":
            part_id = payload.pop("part_id")
            service.update_part(part_id, payload)
        elif op == "allocation_add":
            body = dict(payload)
            token = body.pop("part_token", None)
            if token:
                body["part_id"] = service.resolve_part(token).id
            service.add_stock(**body)
        else:
            raise InventoryError("validation_error", "Unknown import operation.", 422)
    return plan.as_dict()


def _plan_categories(service: InventoryService, text: str, mode: str, plan: ImportPlan) -> None:
    rows = _read(text, "categories", CATEGORY_COLUMNS)
    plan.summary["rows"] += len(rows)
    existing = {item["name"].casefold(): item for item in service.list_categories()}
    seen: set[str] = set()
    for index, row in rows:
        name = (row.get("name") or "").strip()
        key = name.casefold()
        if not name:
            plan.errors.append({"row": index, "file": "categories", "message": "Category name is required."})
            continue
        if key in seen:
            plan.errors.append({"row": index, "file": "categories", "message": f"Duplicate category {name}."})
            continue
        seen.add(key)
        color = (row.get("color") or "").strip() or None
        if color:
            try:
                color = normalize_hex(color)
            except InventoryError as exc:
                plan.errors.append({"row": index, "file": "categories", "message": exc.message})
                continue
        payload = {
            "name": name,
            "description": row.get("description") or None,
            "color": color,
        }
        current = existing.get(key)
        if current is None:
            plan.operations.append(("category_create", payload))
            plan.summary["create"] += 1
        elif mode == "update_metadata":
            plan.operations.append(("category_update", {"id": current["id"], **payload}))
            plan.summary["update"] += 1
        else:
            plan.errors.append({"row": index, "file": "categories", "message": f"Category {name} already exists."})


def _plan_slots(service: InventoryService, text: str, mode: str, plan: ImportPlan) -> None:
    rows = _read(text, "slots", SLOT_COLUMNS)
    plan.summary["rows"] += len(rows)
    slots, _total = service.list_slots(include_archived=True, limit=100_000, offset=0)
    existing = {slot["slot_number"]: slot for slot in slots}
    seen: set[int] = set()
    for index, row in rows:
        raw = (row.get("slot_number") or "").strip()
        if not raw.isdigit() or int(raw) < 1:
            plan.errors.append({"row": index, "file": "slots", "message": "Slot number must be a positive integer."})
            continue
        number = int(raw)
        if number in seen:
            plan.errors.append({"row": index, "file": "slots", "message": f"Duplicate drawer {number}."})
            continue
        seen.add(number)
        payload = {
            "label": row.get("label") or None,
            "description": row.get("description") or None,
            "location": row.get("location") or None,
        }
        if number not in existing:
            plan.operations.append(("slot_create", {"slot_number": number, **payload}))
            plan.summary["create"] += 1
        elif mode == "update_metadata":
            plan.operations.append(("slot_update", {"slot_number": number, **payload}))
            plan.summary["update"] += 1
        else:
            plan.errors.append({"row": index, "file": "slots", "message": f"Drawer {number} already exists."})


def _plan_parts(service: InventoryService, text: str, mode: str, plan: ImportPlan) -> None:
    import json

    rows = _read(text, "parts", PART_COLUMNS)
    plan.summary["rows"] += len(rows)
    views, _total = service.list_part_views(include_archived=True, limit=-1)
    by_sku = {(view["sku"] or "").casefold(): view for view in views if view["sku"]}
    by_name = {}
    for view in views:
        by_name.setdefault(view["name"].casefold(), view)
    categories = {item["name"].casefold(): item["id"] for item in service.list_categories()}
    seen: set[str] = set()
    for index, row in rows:
        name = (row.get("name") or "").strip()
        sku = (row.get("sku") or "").strip()
        if not name:
            plan.errors.append({"row": index, "file": "parts", "message": "Part name is required."})
            continue
        identity = sku.casefold() if sku else f"name:{name.casefold()}"
        if identity in seen:
            plan.errors.append({"row": index, "file": "parts", "message": f"Duplicate part row for {sku or name}."})
            continue
        seen.add(identity)
        category_name = (row.get("category") or "").strip()
        category_id = None
        if category_name:
            category_id = categories.get(category_name.casefold())
            if category_id is None:
                plan.errors.append(
                    {"row": index, "file": "parts", "message": f"Unknown category {category_name}."}
                )
                continue
        try:
            initial = _whole(row.get("initial_quantity") or "0", allow_zero=True)
            percent_raw = (row.get("low_stock_percent") or "").strip()
            percent = _whole(percent_raw, allow_zero=True) if percent_raw else None
            override_raw = (row.get("low_stock_override") or "").strip()
            override = _whole(override_raw, allow_zero=True) if override_raw else None
        except ValueError as exc:
            plan.errors.append({"row": index, "file": "parts", "message": str(exc)})
            continue
        specs = None
        raw_specs = (row.get("specifications_json") or "").strip()
        if raw_specs:
            try:
                specs = json.loads(raw_specs)
            except json.JSONDecodeError:
                plan.errors.append({"row": index, "file": "parts", "message": "specifications_json is not valid JSON."})
                continue
            if not isinstance(specs, dict):
                plan.errors.append({"row": index, "file": "parts", "message": "specifications_json must be an object."})
                continue
        payload = {
            "name": name,
            "sku": sku or None,
            "description": row.get("description") or None,
            "category_id": category_id,
            "manufacturer": row.get("manufacturer") or None,
            "manufacturer_part_number": row.get("manufacturer_part_number") or None,
            "unit": row.get("unit") or "pcs",
            "initial_quantity": initial,
            "low_stock_percent": percent,
            "low_stock_override": override,
            "notes": row.get("notes") or None,
            "specifications": specs,
        }
        current = by_sku.get(sku.casefold()) if sku else by_name.get(name.casefold())
        if current is None:
            plan.operations.append(("part_create", payload))
            plan.summary["create"] += 1
        elif mode == "update_metadata":
            part_fields = dict(payload)
            plan.operations.append(("part_update", {"part_id": current["id"], **part_fields}))
            plan.summary["update"] += 1
        else:
            plan.errors.append({"row": index, "file": "parts", "message": f"Part {sku or name} already exists."})


def _plan_allocations(service: InventoryService, text: str, allocation_mode: str, plan: ImportPlan) -> None:
    rows = _read(text, "allocations", ALLOCATION_COLUMNS)
    plan.summary["rows"] += len(rows)
    views, _total = service.list_part_views(include_archived=True, limit=-1)
    # Include parts this same plan will create, matched later by sku/name at apply time.
    by_sku = {(view["sku"] or "").casefold(): view for view in views if view["sku"]}
    by_name = {view["name"].casefold(): view for view in views}
    slots, _slot_total = service.list_slots(include_archived=True, limit=100_000, offset=0)
    slot_numbers = {slot["slot_number"] for slot in slots}
    slot_numbers.update(
        payload["slot_number"] for op, payload in plan.operations if op == "slot_create"
    )
    planned_parts = [payload for op, payload in plan.operations if op == "part_create"]
    seen: set[tuple] = set()
    for index, row in rows:
        raw_slot = (row.get("slot_number") or "").strip()
        sku = (row.get("part_sku") or "").strip()
        name = (row.get("part_name") or "").strip()
        if not raw_slot.isdigit() or int(raw_slot) < 1:
            plan.errors.append({"row": index, "file": "allocations", "message": "Slot number must be a positive integer."})
            continue
        number = int(raw_slot)
        if number not in slot_numbers:
            plan.errors.append({"row": index, "file": "allocations", "message": f"Drawer {number} does not exist."})
            continue
        try:
            quantity = _whole(row.get("quantity") or "", allow_zero=False)
        except ValueError as exc:
            plan.errors.append({"row": index, "file": "allocations", "message": str(exc)})
            continue
        identity = (number, sku.casefold(), name.casefold())
        if identity in seen:
            plan.errors.append(
                {"row": index, "file": "allocations", "message": "Duplicate slot assignment in this file."}
            )
            continue
        seen.add(identity)
        current = by_sku.get(sku.casefold()) if sku else None
        if current is None and name:
            current = by_name.get(name.casefold())
        pending = None
        if current is None:
            for payload in planned_parts:
                if sku and (payload.get("sku") or "").casefold() == sku.casefold():
                    pending = payload
                    break
                if not sku and payload["name"].casefold() == name.casefold():
                    pending = payload
                    break
        if current is None and pending is None:
            plan.errors.append(
                {"row": index, "file": "allocations", "message": "Part was not found. Import parts first."}
            )
            continue
        if current is not None:
            already = any(slot["slot_number"] == number for slot in current["slots"])
            if already and allocation_mode == "skip_existing":
                plan.warnings.append(
                    {"row": index, "file": "allocations", "message": f"Skipped existing assignment in drawer {number}."}
                )
                plan.summary["skip"] += 1
                continue
            plan.operations.append(
                (
                    "allocation_add",
                    {
                        "part_id": current["id"],
                        "slot_number": number,
                        "quantity": quantity,
                        "transaction_type": "INITIAL_STOCK" if current["current_quantity"] == 0 else "ADD",
                        "reason": "CSV import",
                        "source": "import",
                    },
                )
            )
        else:
            # Part is created earlier in this plan. Resolve the id during apply.
            plan.operations.append(
                (
                    "allocation_add",
                    {
                        "part_token": sku or name,
                        "slot_number": number,
                        "quantity": quantity,
                        "transaction_type": "INITIAL_STOCK",
                        "reason": "CSV import",
                        "source": "import",
                    },
                )
            )
        plan.summary["stock_transactions"] += 1


def _read(text: str, file_name: str, columns: list[str]) -> list[tuple[int, dict]]:
    if text is None or not str(text).strip():
        return []
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if reader.fieldnames is None:
        raise InventoryError("validation_error", f"{file_name} CSV is missing a header row.", 422)
    header = [name.strip() for name in reader.fieldnames]
    missing = [column for column in columns if column not in header]
    if missing:
        raise InventoryError(
            "validation_error",
            f"{file_name} CSV is missing columns: {', '.join(missing)}.",
            422,
        )
    rows: list[tuple[int, dict]] = []
    for index, row in enumerate(reader, start=2):
        if row is None or all(not (value or "").strip() for value in row.values()):
            continue
        rows.append((index, {key: (row.get(key) or "").strip() for key in columns}))
        if len(rows) > MAX_IMPORT_ROWS:
            raise InventoryError("validation_error", "CSV exceeds the row limit.", 422)
    return rows


def _write(columns: list[str], rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in columns})
    return buffer.getvalue()


def _whole(value: str, *, allow_zero: bool) -> int:
    text = str(value).strip()
    if text == "" or not _is_int(text):
        raise ValueError("Quantity must be a whole number.")
    number = int(text)
    if number < 0 or (number == 0 and not allow_zero):
        raise ValueError("Quantity must be a positive whole number." if not allow_zero else "Quantity cannot be negative.")
    return number


def _is_int(value: str) -> bool:
    if value.startswith("-"):
        return value[1:].isdigit()
    return value.isdigit()
