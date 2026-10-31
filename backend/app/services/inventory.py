"""Single mutation path for parts, drawers, and stock.

The HTTP API and the CLI both call this service. Stock changes always insert
an append-only transaction in the same database transaction as the quantity
update. Callers commit or roll back the session.
"""

from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.constants import (
    INCREASE_TYPES,
    LANDING_PAGES,
    MAX_QUANTITY,
    MAX_SLOT_NUMBER,
    MAX_SPEC_BYTES,
    SOURCES,
    THEMES,
)
from app.core.defaults import DEFAULT_UNIT
from app.core.errors import InventoryError
from app.core.themes import preset_palette
from app.models import (
    AppSetting,
    AuditEvent,
    Category,
    Part,
    Slot,
    SlotInventory,
    StockTransaction,
)
from app.services.views import build_part_dict, category_dict, transaction_dict
from app.utils.color import normalize_hex, validate_palette
from app.utils.ids import new_id
from app.utils.time import ensure_utc, utcnow

BASELINE_FIELDS = frozenset({"initial_quantity", "low_stock_percent", "low_stock_override"})
PART_FIELDS = BASELINE_FIELDS | frozenset(
    {
        "name",
        "sku",
        "description",
        "category_id",
        "manufacturer",
        "manufacturer_part_number",
        "specifications",
        "unit",
        "notes",
    }
)
_SORTS = {
    "name": lambda view: view["name"].casefold(),
    "sku": lambda view: (view["sku"] or "").casefold(),
    "quantity": lambda view: view["current_quantity"],
    "updated_at": lambda view: view["updated_at"],
    "status": lambda view: {"OUT_OF_STOCK": 0, "LOW_STOCK": 1, "IN_STOCK": 2}[view["status"]],
}


class InventoryService:
    def __init__(self, session: Session, *, source: str = "api") -> None:
        if source not in SOURCES:
            raise InventoryError("validation_error", "Unknown change source.", 422)
        self.session = session
        self.source = source

    # ----- categories -----------------------------------------------------

    def list_categories(self) -> list[dict]:
        rows = self.session.scalars(select(Category).order_by(Category.name)).all()
        return [category_dict(row) for row in rows]

    def create_category(
        self,
        *,
        name: str,
        description: str | None = None,
        color: str | None = None,
    ) -> dict:
        cleaned = self._clean_name(name, field="Category name", limit=120)
        self._ensure_category_name(cleaned)
        now = utcnow()
        row = Category(
            id=new_id(),
            name=cleaned,
            description=_blank_to_none(description),
            color=normalize_hex(color) if color else None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self._flush()
        return category_dict(row)

    def update_category(self, category_id: str, fields: dict) -> dict:
        row = self._require_category(category_id)
        if "name" in fields and fields["name"] is not None:
            cleaned = self._clean_name(fields["name"], field="Category name", limit=120)
            self._ensure_category_name(cleaned, exclude_id=row.id)
            row.name = cleaned
        if "description" in fields:
            row.description = _blank_to_none(fields["description"])
        if "color" in fields:
            color = fields["color"]
            row.color = normalize_hex(color) if color else None
        row.updated_at = utcnow()
        self._flush()
        return category_dict(row)

    def delete_category(
        self,
        category_id: str,
        *,
        reassign_to: str | None = None,
        allow_clear: bool = False,
    ) -> None:
        row = self._require_category(category_id)
        users = list(self.session.scalars(select(Part).where(Part.category_id == row.id)).all())
        if users:
            if reassign_to:
                target = self._require_category(reassign_to)
                if target.id == row.id:
                    raise InventoryError(
                        "validation_error",
                        "Choose a different category to reassign parts to.",
                        422,
                    )
                target_id = target.id
            elif allow_clear:
                target_id = None
            else:
                raise InventoryError(
                    "not_empty",
                    "Category is assigned to parts. Reassign them or pass allow_clear.",
                    409,
                    {"part_count": len(users)},
                )
            now = utcnow()
            for part in users:
                part.category_id = target_id
                part.updated_at = now
        self.session.delete(row)
        self._flush()

    # ----- parts ----------------------------------------------------------

    def create_part(self, data: dict) -> dict:
        name = self._clean_name(data.get("name") or "", field="Part name", limit=200)
        sku = self._clean_sku(data.get("sku"))
        self._ensure_sku(sku)
        category_id = self._optional_category(data.get("category_id"))
        percent = data.get("low_stock_percent")
        if percent is None:
            percent = self._settings_row().default_low_stock_percent
        self._check_percent(percent)
        initial = self._check_quantity(data.get("initial_quantity") or 0, allow_zero=True)
        override = data.get("low_stock_override")
        if override is not None:
            override = self._check_quantity(override, allow_zero=True)
        specifications = self._specifications(data.get("specifications"))
        now = utcnow()
        part = Part(
            id=new_id(),
            sku=sku,
            name=name,
            description=_blank_to_none(data.get("description")),
            category_id=category_id,
            manufacturer=_limit(data.get("manufacturer"), 200),
            manufacturer_part_number=_limit(data.get("manufacturer_part_number"), 200),
            specifications=specifications,
            unit=_blank_to_none(data.get("unit")) or DEFAULT_UNIT,
            initial_quantity=initial,
            low_stock_percent=percent,
            low_stock_override=override,
            notes=_limit(data.get("notes"), 4000),
            created_at=now,
            updated_at=now,
            archived_at=None,
        )
        if len(part.unit) > 32:
            raise InventoryError("validation_error", "Unit is too long.", 422)
        self.session.add(part)
        self._flush()
        self._audit(
            "part",
            part.id,
            "part.create",
            {
                "name": {"old": None, "new": part.name},
                "sku": {"old": None, "new": part.sku},
                "initial_quantity": {"old": None, "new": part.initial_quantity},
                "low_stock_percent": {"old": None, "new": part.low_stock_percent},
                "low_stock_override": {"old": None, "new": part.low_stock_override},
            },
        )
        allocations = data.get("allocations") or []
        seen: set[int] = set()
        for allocation in allocations:
            slot_number = int(allocation["slot_number"])
            if slot_number in seen:
                raise InventoryError(
                    "validation_error",
                    f"Drawer {slot_number} is listed twice in the allocation.",
                    422,
                )
            seen.add(slot_number)
            self.add_stock(
                part_id=part.id,
                slot_number=slot_number,
                quantity=int(allocation["quantity"]),
                transaction_type="INITIAL_STOCK",
                reason=allocation.get("reason") or "Initial physical allocation",
            )
        return self.part_view(part.id)

    def update_part(self, part_id: str, fields: dict) -> dict:
        part = self._require_part(part_id)
        changes: dict[str, dict] = {}
        if "name" in fields:
            name = self._clean_name(fields["name"] or "", field="Part name", limit=200)
            self._remember(changes, "name", part.name, name)
            part.name = name
        if "sku" in fields:
            sku = self._clean_sku(fields["sku"])
            self._ensure_sku(sku, exclude_id=part.id)
            self._remember(changes, "sku", part.sku, sku)
            part.sku = sku
        if "description" in fields:
            value = _blank_to_none(fields["description"])
            self._remember(changes, "description", part.description, value)
            part.description = value
        if "category_id" in fields:
            value = self._optional_category(fields["category_id"])
            self._remember(changes, "category_id", part.category_id, value)
            part.category_id = value
        if "manufacturer" in fields:
            value = _limit(fields["manufacturer"], 200)
            self._remember(changes, "manufacturer", part.manufacturer, value)
            part.manufacturer = value
        if "manufacturer_part_number" in fields:
            value = _limit(fields["manufacturer_part_number"], 200)
            self._remember(changes, "manufacturer_part_number", part.manufacturer_part_number, value)
            part.manufacturer_part_number = value
        if "specifications" in fields:
            value = self._specifications(fields["specifications"])
            self._remember(changes, "specifications", part.specifications or {}, value or {})
            part.specifications = value
        if "unit" in fields:
            value = _blank_to_none(fields["unit"]) or DEFAULT_UNIT
            if len(value) > 32:
                raise InventoryError("validation_error", "Unit is too long.", 422)
            self._remember(changes, "unit", part.unit, value)
            part.unit = value
        if "initial_quantity" in fields and fields["initial_quantity"] is not None:
            value = self._check_quantity(fields["initial_quantity"], allow_zero=True)
            self._remember(changes, "initial_quantity", part.initial_quantity, value)
            part.initial_quantity = value
        if "low_stock_percent" in fields and fields["low_stock_percent"] is not None:
            self._check_percent(fields["low_stock_percent"])
            self._remember(changes, "low_stock_percent", part.low_stock_percent, fields["low_stock_percent"])
            part.low_stock_percent = fields["low_stock_percent"]
        if "low_stock_override" in fields:
            raw = fields["low_stock_override"]
            value = None if raw is None else self._check_quantity(raw, allow_zero=True)
            self._remember(changes, "low_stock_override", part.low_stock_override, value)
            part.low_stock_override = value
        if "notes" in fields:
            value = _limit(fields["notes"], 4000)
            self._remember(changes, "notes", part.notes, value)
            part.notes = value
        if changes:
            part.updated_at = utcnow()
            baseline = {key: changes[key] for key in BASELINE_FIELDS if key in changes}
            other = {key: changes[key] for key in changes if key not in BASELINE_FIELDS}
            if baseline:
                self._audit("part", part.id, "baseline.update", baseline)
            if other:
                self._audit("part", part.id, "part.update", other)
        self._flush()
        return self.part_view(part.id)

    def archive_part(self, part_id: str, *, confirm_remove_stock: bool, reason: str | None) -> dict:
        part = self._require_part(part_id)
        if part.archived_at is not None:
            raise InventoryError("archived", "Part is already archived.", 409)
        self._clear_part_stock(part, confirm=confirm_remove_stock, reason=reason or "Archived part")
        part.archived_at = utcnow()
        part.updated_at = part.archived_at
        self._audit("part", part.id, "part.archive", {"archived_at": {"old": None, "new": part.archived_at.isoformat()}})
        self._flush()
        return self.part_view(part.id)

    def unarchive_part(self, part_id: str) -> dict:
        part = self._require_part(part_id)
        if part.archived_at is None:
            raise InventoryError("validation_error", "Part is not archived.", 422)
        old = part.archived_at
        part.archived_at = None
        part.updated_at = utcnow()
        self._audit(
            "part",
            part.id,
            "part.unarchive",
            {"archived_at": {"old": old.isoformat(), "new": None}},
        )
        self._flush()
        return self.part_view(part.id)

    def delete_part(self, part_id: str) -> None:
        part = self._require_part(part_id)
        qty = self._part_quantity(part.id)
        if qty > 0:
            raise InventoryError(
                "not_empty",
                "Remove this part's stock, or archive it, before deleting it.",
                409,
                {"current_quantity": qty},
            )
        txn_count = self.session.scalar(
            select(func.count()).select_from(StockTransaction).where(StockTransaction.part_id == part.id)
        )
        if txn_count:
            raise InventoryError(
                "history_exists",
                "This part has transaction history. Archive it instead of deleting it.",
                409,
            )
        self.session.delete(part)
        self._flush()

    # ----- slots ----------------------------------------------------------

    def create_slot(
        self,
        *,
        slot_number: int,
        label: str | None = None,
        description: str | None = None,
        location: str | None = None,
    ) -> dict:
        number = self._check_slot_number(slot_number)
        if self._find_slot(number) is not None:
            raise InventoryError("conflict", f"Drawer {number} already exists.", 409)
        now = utcnow()
        slot = Slot(
            id=new_id(),
            slot_number=number,
            label=_limit(label, 120),
            description=_blank_to_none(description),
            location=_limit(location, 120),
            created_at=now,
            updated_at=now,
            archived_at=None,
        )
        self.session.add(slot)
        self._audit(
            "slot",
            slot.id,
            "slot.create",
            {"slot_number": {"old": None, "new": number}},
        )
        self._flush()
        return self.slot_view(number)

    def update_slot(self, slot_number: int, fields: dict) -> dict:
        slot = self._require_slot(slot_number)
        if "slot_number" in fields and fields["slot_number"] is not None:
            new_number = self._check_slot_number(fields["slot_number"])
            if new_number != slot.slot_number:
                other = self._find_slot(new_number)
                if other is not None:
                    raise InventoryError("conflict", f"Drawer {new_number} already exists.", 409)
                old_number = slot.slot_number
                slot.slot_number = new_number
                self._audit(
                    "slot",
                    slot.id,
                    "slot.renumber",
                    {"slot_number": {"old": old_number, "new": new_number}},
                )
        if "label" in fields:
            slot.label = _limit(fields["label"], 120)
        if "description" in fields:
            slot.description = _blank_to_none(fields["description"])
        if "location" in fields:
            slot.location = _limit(fields["location"], 120)
        slot.updated_at = utcnow()
        self._flush()
        return self.slot_view(slot.slot_number)

    def archive_slot(self, slot_number: int, *, confirm_remove_stock: bool, reason: str | None) -> dict:
        slot = self._require_slot(slot_number)
        if slot.archived_at is not None:
            raise InventoryError("archived", f"Drawer {slot.slot_number} is already archived.", 409)
        self._clear_slot_stock(slot, confirm=confirm_remove_stock, reason=reason or "Archived drawer")
        slot.archived_at = utcnow()
        slot.updated_at = slot.archived_at
        self._audit(
            "slot",
            slot.id,
            "slot.archive",
            {"archived_at": {"old": None, "new": slot.archived_at.isoformat()}},
        )
        self._flush()
        return self.slot_view(slot.slot_number)

    def unarchive_slot(self, slot_number: int) -> dict:
        slot = self._require_slot(slot_number)
        if slot.archived_at is None:
            raise InventoryError("validation_error", "Drawer is not archived.", 422)
        slot.archived_at = None
        slot.updated_at = utcnow()
        self._flush()
        return self.slot_view(slot.slot_number)

    def delete_slot(self, slot_number: int, *, confirm_remove_stock: bool, reason: str | None) -> None:
        slot = self._require_slot(slot_number)
        self._clear_slot_stock(
            slot,
            confirm=confirm_remove_stock,
            reason=reason or "Removed during drawer deletion",
        )
        # History keeps slot-number snapshots. The foreign keys are SET NULL.
        self.session.delete(slot)
        self._flush()

    # ----- stock ----------------------------------------------------------

    def add_stock(
        self,
        *,
        part_id: str,
        slot_number: int,
        quantity: int,
        transaction_type: str = "ADD",
        reason: str | None = None,
        source: str | None = None,
    ) -> StockTransaction:
        if transaction_type not in INCREASE_TYPES:
            raise InventoryError(
                "validation_error",
                "Stock increases must be ADD, RESTOCK, or INITIAL_STOCK.",
                422,
            )
        qty = self._check_quantity(quantity, allow_zero=False)
        part = self._require_active_part(part_id)
        slot = self._require_active_slot(slot_number)
        row = self._allocation(slot.id, part.id, create=True)
        assert row is not None
        before = row.quantity
        after = before + qty
        if after > MAX_QUANTITY:
            raise InventoryError("validation_error", "Resulting quantity is too large.", 422)
        row.quantity = after
        row.updated_at = utcnow()
        txn = self._transaction(
            part=part,
            transaction_type=transaction_type,
            quantity=qty,
            quantity_delta=qty,
            quantity_before=before,
            quantity_after=after,
            to_slot=slot,
            reason=reason,
            source=source,
        )
        self._flush()
        return txn

    def remove_stock(
        self,
        *,
        part_id: str,
        slot_number: int,
        quantity: int,
        reason: str | None = None,
        source: str | None = None,
    ) -> StockTransaction:
        qty = self._check_quantity(quantity, allow_zero=False)
        part = self._require_active_part(part_id)
        slot = self._require_active_slot(slot_number)
        row = self._allocation(slot.id, part.id, create=False)
        have = row.quantity if row is not None else 0
        if row is None or have < qty:
            raise InventoryError(
                "negative_stock",
                f"Drawer {slot.slot_number} only has {have} {part.unit} of {part.name}.",
                409,
                {"available": have, "requested": qty, "part_id": part.id, "slot_number": slot.slot_number},
            )
        before = have
        after = have - qty
        if after == 0:
            self.session.delete(row)
        else:
            row.quantity = after
            row.updated_at = utcnow()
        txn = self._transaction(
            part=part,
            transaction_type="REMOVE",
            quantity=qty,
            quantity_delta=-qty,
            quantity_before=before,
            quantity_after=after,
            from_slot=slot,
            reason=reason,
            source=source,
        )
        self._flush()
        return txn

    def transfer_stock(
        self,
        *,
        part_id: str,
        from_slot: int,
        to_slot: int,
        quantity: int,
        reason: str | None = None,
        source: str | None = None,
    ) -> StockTransaction:
        if from_slot == to_slot:
            raise InventoryError(
                "validation_error",
                "Source and destination drawers must be different.",
                422,
            )
        qty = self._check_quantity(quantity, allow_zero=False)
        part = self._require_active_part(part_id)
        source_slot = self._require_active_slot(from_slot)
        dest_slot = self._require_active_slot(to_slot)
        # Lock order by slot id so concurrent transfers cannot deadlock.
        first, second = sorted((source_slot, dest_slot), key=lambda item: item.id)
        self._allocation(first.id, part.id, create=False)
        self._allocation(second.id, part.id, create=False)
        src_row = self._allocation(source_slot.id, part.id, create=False)
        have = src_row.quantity if src_row is not None else 0
        if src_row is None or have < qty:
            raise InventoryError(
                "negative_stock",
                f"Drawer {source_slot.slot_number} only has {have} {part.unit} of {part.name}.",
                409,
                {"available": have, "requested": qty},
            )
        dest_row = self._allocation(dest_slot.id, part.id, create=True)
        assert dest_row is not None
        src_before = have
        src_after = have - qty
        dest_before = dest_row.quantity
        dest_after = dest_before + qty
        if dest_after > MAX_QUANTITY:
            raise InventoryError("validation_error", "Resulting quantity is too large.", 422)
        if src_after == 0:
            self.session.delete(src_row)
        else:
            src_row.quantity = src_after
            src_row.updated_at = utcnow()
        dest_row.quantity = dest_after
        dest_row.updated_at = utcnow()
        txn = self._transaction(
            part=part,
            transaction_type="TRANSFER",
            quantity=qty,
            quantity_delta=-qty,
            quantity_before=src_before,
            quantity_after=src_after,
            from_slot=source_slot,
            to_slot=dest_slot,
            dest_quantity_before=dest_before,
            dest_quantity_after=dest_after,
            reason=reason,
            source=source,
        )
        self._flush()
        return txn

    def adjust_stock(
        self,
        *,
        part_id: str,
        slot_number: int,
        new_quantity: int,
        reason: str | None = None,
        source: str | None = None,
    ) -> StockTransaction:
        target = self._check_quantity(new_quantity, allow_zero=True)
        part = self._require_active_part(part_id)
        slot = self._require_active_slot(slot_number)
        row = self._allocation(slot.id, part.id, create=False)
        before = row.quantity if row is not None else 0
        if target == before:
            raise InventoryError(
                "validation_error",
                "That drawer already holds this quantity.",
                422,
            )
        if target == 0 and row is not None:
            self.session.delete(row)
        elif row is None:
            row = self._allocation(slot.id, part.id, create=True)
            assert row is not None
            row.quantity = target
            row.updated_at = utcnow()
        else:
            row.quantity = target
            row.updated_at = utcnow()
        delta = target - before
        txn = self._transaction(
            part=part,
            transaction_type="ADJUST",
            quantity=abs(delta),
            quantity_delta=delta,
            quantity_before=before,
            quantity_after=target,
            to_slot=slot,
            reason=reason,
            source=source,
        )
        self._flush()
        return txn

    def require_sole_part(self, slot_number: int) -> Part:
        slot = self._require_active_slot(slot_number)
        rows = self.session.execute(
            select(SlotInventory, Part)
            .join(Part, Part.id == SlotInventory.part_id)
            .where(SlotInventory.slot_id == slot.id, SlotInventory.quantity > 0)
            .order_by(Part.name)
        ).all()
        if not rows:
            raise InventoryError(
                "not_found",
                f"Drawer {slot.slot_number} is empty. Pass --part to choose a part.",
                404,
                {"slot_number": slot.slot_number, "matches": []},
            )
        if len(rows) > 1:
            raise InventoryError(
                "ambiguous",
                f"Drawer {slot.slot_number} holds more than one part. Pass --part.",
                409,
                {"matches": [_match(part) for _allocation, part in rows]},
            )
        return rows[0][1]

    def resolve_part(self, token: str) -> Part:
        text = (token or "").strip()
        if not text:
            raise InventoryError("validation_error", "A part identifier is required.", 422)
        by_id = self.session.get(Part, text)
        if by_id is not None:
            return by_id
        folded = text.casefold()
        exact_sku = self.session.scalars(select(Part).where(func.lower(Part.sku) == folded)).all()
        if len(exact_sku) == 1:
            return exact_sku[0]
        exact_name = self.session.scalars(select(Part).where(func.lower(Part.name) == folded)).all()
        if len(exact_name) == 1:
            return exact_name[0]
        if len(exact_name) > 1:
            raise InventoryError(
                "ambiguous",
                f"More than one part is named {text!r}.",
                409,
                {"matches": [_match(part) for part in exact_name]},
            )
        like = f"%{_escape_like(folded)}%"
        fuzzy = self.session.scalars(
            select(Part).where(
                or_(
                    func.lower(Part.sku).like(like, escape="\\"),
                    func.lower(Part.name).like(like, escape="\\"),
                )
            ).limit(20)
        ).all()
        if len(fuzzy) == 1:
            return fuzzy[0]
        if len(fuzzy) > 1:
            raise InventoryError(
                "ambiguous",
                f"Multiple parts match {text!r}. Use an exact SKU or name.",
                409,
                {"matches": [_match(part) for part in fuzzy]},
            )
        raise InventoryError("not_found", f"No part matches {text!r}.", 404)

    # ----- queries --------------------------------------------------------

    def part_view(self, part_id: str) -> dict:
        part = self._require_part(part_id)
        # Ensure category is loaded.
        if part.category_id and part.category is None:
            self.session.refresh(part, attribute_names=["category"])
        return build_part_dict(part, self._allocations_for([part.id]).get(part.id, []))

    def list_part_views(
        self,
        *,
        search: str | None = None,
        category: str | None = None,
        status: str | None = None,
        slot_number: int | None = None,
        include_archived: bool = False,
        sort: str = "name",
        order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        if sort not in _SORTS:
            raise InventoryError("validation_error", "Unsupported sort field.", 422)
        if order not in {"asc", "desc"}:
            raise InventoryError("validation_error", "Order must be asc or desc.", 422)
        if status is not None and status not in {"OUT_OF_STOCK", "LOW_STOCK", "IN_STOCK"}:
            raise InventoryError("validation_error", "Unknown stock status.", 422)
        stmt = select(Part).options(selectinload(Part.category))
        if not include_archived:
            stmt = stmt.where(Part.archived_at.is_(None))
        if search:
            stmt = stmt.where(self._search_clause(search))
        if category:
            stmt = stmt.where(Part.category_id == self._resolve_category_filter(category).id)
        if slot_number is not None:
            number = self._check_slot_number(slot_number)
            stmt = stmt.where(
                Part.id.in_(
                    select(SlotInventory.part_id)
                    .join(Slot, Slot.id == SlotInventory.slot_id)
                    .where(Slot.slot_number == number)
                )
            )
        parts = list(self.session.scalars(stmt).all())
        grouped = self._allocations_for([part.id for part in parts])
        views = [build_part_dict(part, grouped.get(part.id, [])) for part in parts]
        if status:
            views = [view for view in views if view["status"] == status]
        views.sort(key=_SORTS[sort], reverse=order == "desc")
        total = len(views)
        if limit < 0:
            return views, total
        return views[offset : offset + limit], total

    def slot_view(self, slot_number: int) -> dict:
        slot = self._require_slot(slot_number)
        rows = self.session.execute(
            select(SlotInventory, Part)
            .join(Part, Part.id == SlotInventory.part_id)
            .where(SlotInventory.slot_id == slot.id)
            .order_by(Part.name)
        ).all()
        items = [
            {
                "part_id": part.id,
                "name": part.name,
                "sku": part.sku,
                "unit": part.unit,
                "quantity": allocation.quantity,
                "category_id": part.category_id,
            }
            for allocation, part in rows
        ]
        return {
            "id": slot.id,
            "slot_number": slot.slot_number,
            "label": slot.label,
            "description": slot.description,
            "location": slot.location,
            "created_at": ensure_utc(slot.created_at),
            "updated_at": ensure_utc(slot.updated_at),
            "archived_at": ensure_utc(slot.archived_at) if slot.archived_at else None,
            "items": items,
            "total_units": sum(item["quantity"] for item in items),
        }

    def list_slots(
        self,
        *,
        search: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        stmt = select(Slot)
        if not include_archived:
            stmt = stmt.where(Slot.archived_at.is_(None))
        if search:
            text = search.strip()
            if text.isdigit():
                stmt = stmt.where(Slot.slot_number == int(text))
            else:
                like = f"%{_escape_like(text.casefold())}%"
                stmt = stmt.where(
                    or_(
                        func.lower(Slot.label).like(like, escape="\\"),
                        func.lower(Slot.location).like(like, escape="\\"),
                        func.lower(Slot.description).like(like, escape="\\"),
                    )
                )
        stmt = stmt.order_by(Slot.slot_number)
        slots = list(self.session.scalars(stmt).all())
        total = len(slots)
        page = slots[offset : offset + limit]
        if not page:
            return [], total
        ids = [slot.id for slot in page]
        counts = dict(
            self.session.execute(
                select(SlotInventory.slot_id, func.coalesce(func.sum(SlotInventory.quantity), 0))
                .where(SlotInventory.slot_id.in_(ids))
                .group_by(SlotInventory.slot_id)
            ).all()
        )
        part_counts = dict(
            self.session.execute(
                select(SlotInventory.slot_id, func.count())
                .where(SlotInventory.slot_id.in_(ids))
                .group_by(SlotInventory.slot_id)
            ).all()
        )
        views = [
            {
                "id": slot.id,
                "slot_number": slot.slot_number,
                "label": slot.label,
                "description": slot.description,
                "location": slot.location,
                "created_at": ensure_utc(slot.created_at),
                "updated_at": ensure_utc(slot.updated_at),
                "archived_at": ensure_utc(slot.archived_at) if slot.archived_at else None,
                "total_units": int(counts.get(slot.id, 0) or 0),
                "part_count": int(part_counts.get(slot.id, 0) or 0),
            }
            for slot in page
        ]
        return views, total

    def list_transactions(
        self,
        *,
        part_id: str | None = None,
        slot_number: int | None = None,
        transaction_type: str | None = None,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        stmt = select(StockTransaction)
        count_stmt = select(func.count()).select_from(StockTransaction)
        filters = []
        if part_id:
            filters.append(StockTransaction.part_id == part_id)
        if transaction_type:
            filters.append(StockTransaction.transaction_type == transaction_type)
        if source:
            if source not in SOURCES:
                raise InventoryError("validation_error", "Unknown transaction source.", 422)
            filters.append(StockTransaction.source == source)
        if slot_number is not None:
            number = self._check_slot_number(slot_number)
            slot = self._find_slot(number)
            clauses = [
                StockTransaction.from_slot_number == number,
                StockTransaction.to_slot_number == number,
            ]
            if slot is not None:
                clauses.extend(
                    [
                        StockTransaction.from_slot_id == slot.id,
                        StockTransaction.to_slot_id == slot.id,
                    ]
                )
            filters.append(or_(*clauses))
        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)
        total = int(self.session.scalar(count_stmt) or 0)
        rows = self.session.scalars(
            stmt.order_by(StockTransaction.created_at.desc(), StockTransaction.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [transaction_dict(row) for row in rows], total

    def list_audit(self, *, entity_type: str, entity_id: str) -> list[dict]:
        rows = self.session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_type == entity_type, AuditEvent.entity_id == entity_id)
            .order_by(AuditEvent.created_at.desc())
        ).all()
        return [
            {
                "id": row.id,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "action": row.action,
                "changes": row.changes,
                "source": row.source,
                "created_at": ensure_utc(row.created_at),
            }
            for row in rows
        ]

    def low_stock(self, *, limit: int = 500, offset: int = 0) -> tuple[list[dict], int]:
        views, _total = self.list_part_views(include_archived=False, limit=-1, offset=0)
        alerts = [view for view in views if view["status"] in {"OUT_OF_STOCK", "LOW_STOCK"}]
        alerts.sort(
            key=lambda view: (
                0 if view["status"] == "OUT_OF_STOCK" else 1,
                view["current_quantity"],
                view["name"].casefold(),
            )
        )
        return alerts[offset : offset + limit], len(alerts)

    def stats(self) -> dict:
        views, _total = self.list_part_views(include_archived=True, limit=-1, offset=0)
        active = [view for view in views if view["archived_at"] is None]
        occupied = self.session.scalar(
            select(func.count(func.distinct(SlotInventory.slot_id))).where(SlotInventory.quantity > 0)
        )
        units = self.session.scalar(select(func.coalesce(func.sum(SlotInventory.quantity), 0)))
        drawers = self.session.scalar(
            select(func.count()).select_from(Slot).where(Slot.archived_at.is_(None))
        )
        return {
            "active_part_types": len(active),
            "occupied_slots": int(occupied or 0),
            "total_units": int(units or 0),
            "low_stock_part_types": sum(1 for view in active if view["status"] == "LOW_STOCK"),
            "out_of_stock_part_types": sum(1 for view in active if view["status"] == "OUT_OF_STOCK"),
            "archived_part_types": sum(1 for view in views if view["archived_at"] is not None),
            "drawer_count": int(drawers or 0),
        }

    # ----- settings -------------------------------------------------------

    def get_settings_view(self) -> dict:
        row = self._settings_row()
        return self._settings_dict(row)

    def update_settings(self, fields: dict) -> dict:
        row = self._settings_row()
        if "application_name" in fields and fields["application_name"] is not None:
            name = self._clean_name(fields["application_name"], field="Application name", limit=80)
            row.application_name = name
        if "default_low_stock_percent" in fields and fields["default_low_stock_percent"] is not None:
            self._check_percent(fields["default_low_stock_percent"])
            row.default_low_stock_percent = fields["default_low_stock_percent"]
        if "preferred_landing_page" in fields and fields["preferred_landing_page"] is not None:
            page = fields["preferred_landing_page"]
            if page not in LANDING_PAGES:
                raise InventoryError("validation_error", "Unknown landing page.", 422)
            row.preferred_landing_page = page
        if "display_preferences" in fields and fields["display_preferences"] is not None:
            row.display_preferences = _display_preferences(fields["display_preferences"])
        if "preferred_public_url" in fields:
            row.preferred_public_url = _public_url(fields["preferred_public_url"])
        theme = fields.get("theme_preference", row.theme_preference)
        if "color_palette" in fields and fields["color_palette"] is not None:
            theme = "custom"
            row.color_palette = validate_palette(fields["color_palette"])
            row.theme_preference = "custom"
        elif "theme_preference" in fields and fields["theme_preference"] is not None:
            if theme not in THEMES:
                raise InventoryError("validation_error", "Unknown theme.", 422)
            if theme == "custom":
                if "color_palette" not in fields or fields.get("color_palette") is None:
                    raise InventoryError(
                        "validation_error",
                        "A custom theme requires a color palette.",
                        422,
                    )
            else:
                palette = preset_palette(theme)
                assert palette is not None
                row.theme_preference = theme
                row.color_palette = validate_palette(palette)
        row.updated_at = utcnow()
        self._flush()
        return self._settings_dict(row)

    # ----- internals ------------------------------------------------------

    def _settings_row(self) -> AppSetting:
        row = self.session.get(AppSetting, 1)
        if row is None:
            raise InventoryError("not_found", "Application settings are not initialized.", 500)
        return row

    def _settings_dict(self, row: AppSetting) -> dict:
        return {
            "application_name": row.application_name,
            "theme_preference": row.theme_preference,
            "color_palette": row.color_palette,
            "default_low_stock_percent": row.default_low_stock_percent,
            "preferred_landing_page": row.preferred_landing_page,
            "display_preferences": row.display_preferences,
            "preferred_public_url": row.preferred_public_url,
            "updated_at": ensure_utc(row.updated_at),
        }

    def _transaction(
        self,
        *,
        part: Part,
        transaction_type: str,
        quantity: int,
        quantity_delta: int,
        quantity_before: int,
        quantity_after: int,
        from_slot: Slot | None = None,
        to_slot: Slot | None = None,
        dest_quantity_before: int | None = None,
        dest_quantity_after: int | None = None,
        reason: str | None = None,
        source: str | None = None,
    ) -> StockTransaction:
        chosen = source or self.source
        if chosen not in SOURCES:
            raise InventoryError("validation_error", "Unknown change source.", 422)
        row = StockTransaction(
            id=new_id(),
            part_id=part.id,
            part_name_snapshot=part.name,
            part_sku_snapshot=part.sku,
            from_slot_id=from_slot.id if from_slot else None,
            to_slot_id=to_slot.id if to_slot else None,
            from_slot_number=from_slot.slot_number if from_slot else None,
            to_slot_number=to_slot.slot_number if to_slot else None,
            transaction_type=transaction_type,
            quantity=quantity,
            quantity_delta=quantity_delta,
            quantity_before=quantity_before,
            quantity_after=quantity_after,
            dest_quantity_before=dest_quantity_before,
            dest_quantity_after=dest_quantity_after,
            reason=_limit(reason, 500),
            source=chosen,
            created_at=utcnow(),
        )
        self.session.add(row)
        return row

    def _audit(self, entity_type: str, entity_id: str, action: str, changes: dict) -> None:
        self.session.add(
            AuditEvent(
                id=new_id(),
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                changes=_json_safe(changes),
                source=self.source,
                created_at=utcnow(),
            )
        )

    def _allocation(self, slot_id: str, part_id: str, *, create: bool) -> SlotInventory | None:
        row = self.session.scalar(
            select(SlotInventory).where(
                SlotInventory.slot_id == slot_id,
                SlotInventory.part_id == part_id,
            )
        )
        if row is None and create:
            now = utcnow()
            row = SlotInventory(
                id=new_id(),
                slot_id=slot_id,
                part_id=part_id,
                quantity=0,
                created_at=now,
                updated_at=now,
            )
            self.session.add(row)
            self._flush()
        return row

    def _allocations_for(self, part_ids: list[str]) -> dict[str, list[tuple[SlotInventory, Slot]]]:
        grouped: dict[str, list[tuple[SlotInventory, Slot]]] = defaultdict(list)
        if not part_ids:
            return grouped
        rows = self.session.execute(
            select(SlotInventory, Slot)
            .join(Slot, Slot.id == SlotInventory.slot_id)
            .where(SlotInventory.part_id.in_(part_ids))
        ).all()
        for allocation, slot in rows:
            grouped[allocation.part_id].append((allocation, slot))
        return grouped

    def _clear_part_stock(self, part: Part, *, confirm: bool, reason: str) -> None:
        rows = self.session.scalars(select(SlotInventory).where(SlotInventory.part_id == part.id)).all()
        if any(row.quantity > 0 for row in rows) and not confirm:
            raise InventoryError(
                "not_empty",
                "This part still has stock. Confirm removal to record it before archiving.",
                409,
                {"current_quantity": sum(row.quantity for row in rows)},
            )
        for row in list(rows):
            if row.quantity <= 0:
                self.session.delete(row)
                continue
            slot = self.session.get(Slot, row.slot_id)
            if slot is None:
                continue
            self.remove_stock(part_id=part.id, slot_number=slot.slot_number, quantity=row.quantity, reason=reason)

    def _clear_slot_stock(self, slot: Slot, *, confirm: bool, reason: str) -> None:
        rows = self.session.execute(
            select(SlotInventory, Part).join(Part, Part.id == SlotInventory.part_id).where(SlotInventory.slot_id == slot.id)
        ).all()
        units = sum(allocation.quantity for allocation, _part in rows)
        if units > 0 and not confirm:
            raise InventoryError(
                "not_empty",
                f"Drawer {slot.slot_number} still holds {units} units. Transfer them or confirm removal.",
                409,
                {
                    "total_units": units,
                    "items": [
                        {"part_id": part.id, "name": part.name, "sku": part.sku, "quantity": allocation.quantity}
                        for allocation, part in rows
                    ],
                },
            )
        for allocation, part in list(rows):
            if allocation.quantity > 0:
                self.remove_stock(
                    part_id=part.id,
                    slot_number=slot.slot_number,
                    quantity=allocation.quantity,
                    reason=reason,
                )
            else:
                self.session.delete(allocation)

    def _part_quantity(self, part_id: str) -> int:
        value = self.session.scalar(
            select(func.coalesce(func.sum(SlotInventory.quantity), 0)).where(SlotInventory.part_id == part_id)
        )
        return int(value or 0)

    def _find_slot(self, slot_number: int) -> Slot | None:
        return self.session.scalar(select(Slot).where(Slot.slot_number == slot_number))

    def _require_slot(self, slot_number: int) -> Slot:
        number = self._check_slot_number(slot_number)
        slot = self._find_slot(number)
        if slot is None:
            raise InventoryError("not_found", f"Drawer {number} was not found.", 404)
        return slot

    def _require_active_slot(self, slot_number: int) -> Slot:
        slot = self._require_slot(slot_number)
        if slot.archived_at is not None:
            raise InventoryError("archived", f"Drawer {slot.slot_number} is archived.", 409)
        return slot

    def _require_part(self, part_id: str) -> Part:
        part = self.session.get(Part, part_id)
        if part is None:
            raise InventoryError("not_found", "Part was not found.", 404)
        return part

    def _require_active_part(self, part_id: str) -> Part:
        part = self._require_part(part_id)
        if part.archived_at is not None:
            raise InventoryError("archived", "Part is archived.", 409)
        return part

    def _require_category(self, category_id: str) -> Category:
        row = self.session.get(Category, category_id)
        if row is None:
            raise InventoryError("not_found", "Category was not found.", 404)
        return row

    def _optional_category(self, category_id: str | None) -> str | None:
        if category_id in (None, ""):
            return None
        return self._require_category(str(category_id)).id

    def _resolve_category_filter(self, token: str) -> Category:
        row = self.session.get(Category, token)
        if row is not None:
            return row
        folded = token.strip().casefold()
        matches = self.session.scalars(select(Category).where(func.lower(Category.name) == folded)).all()
        if len(matches) == 1:
            return matches[0]
        raise InventoryError("not_found", f"Category {token!r} was not found.", 404)

    def _ensure_sku(self, sku: str | None, *, exclude_id: str | None = None) -> None:
        if not sku:
            return
        stmt = select(Part).where(func.lower(Part.sku) == sku.casefold())
        if exclude_id:
            stmt = stmt.where(Part.id != exclude_id)
        if self.session.scalar(stmt) is not None:
            raise InventoryError("conflict", f"SKU {sku} is already in use.", 409)

    def _ensure_category_name(self, name: str, *, exclude_id: str | None = None) -> None:
        stmt = select(Category).where(func.lower(Category.name) == name.casefold())
        if exclude_id:
            stmt = stmt.where(Category.id != exclude_id)
        if self.session.scalar(stmt) is not None:
            raise InventoryError("conflict", f"Category {name} already exists.", 409)

    def _search_clause(self, search: str):
        text = search.strip()
        if len(text) > 200:
            raise InventoryError("validation_error", "Search text is too long.", 422)
        like = f"%{_escape_like(text.casefold())}%"
        return or_(
            func.lower(Part.name).like(like, escape="\\"),
            func.lower(Part.sku).like(like, escape="\\"),
            func.lower(Part.manufacturer).like(like, escape="\\"),
            func.lower(Part.manufacturer_part_number).like(like, escape="\\"),
            func.lower(Part.description).like(like, escape="\\"),
            func.lower(Part.notes).like(like, escape="\\"),
        )

    def _specifications(self, value) -> dict | None:
        if value in (None, "", {}):
            return None
        if not isinstance(value, dict):
            raise InventoryError("validation_error", "Specifications must be a JSON object.", 422)
        encoded = json.dumps(value)
        if len(encoded.encode("utf-8")) > MAX_SPEC_BYTES:
            raise InventoryError("validation_error", "Specifications are too large.", 422)
        return value

    def _check_slot_number(self, value: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise InventoryError("validation_error", "Drawer number must be a positive integer.", 422) from exc
        if number < 1 or number > MAX_SLOT_NUMBER:
            raise InventoryError(
                "validation_error",
                f"Drawer number must be between 1 and {MAX_SLOT_NUMBER}.",
                422,
            )
        return number

    def _check_quantity(self, value: int, *, allow_zero: bool) -> int:
        if isinstance(value, bool) or isinstance(value, float):
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            else:
                raise InventoryError(
                    "validation_error",
                    "Fractional quantities are not supported.",
                    422,
                )
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise InventoryError("validation_error", "Quantity must be a whole number.", 422) from exc
        if number < 0 or (number == 0 and not allow_zero) or number > MAX_QUANTITY:
            raise InventoryError(
                "validation_error",
                "Quantity must be a nonnegative whole number within the supported range.",
                422,
            )
        return number

    def _check_percent(self, value: int) -> None:
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise InventoryError("validation_error", "Low-stock percent must be an integer.", 422) from exc
        if number < 0 or number > 100:
            raise InventoryError("validation_error", "Low-stock percent must be from 0 to 100.", 422)

    def _clean_name(self, value: str, *, field: str, limit: int) -> str:
        cleaned = " ".join(str(value).split())
        if not cleaned:
            raise InventoryError("validation_error", f"{field} is required.", 422)
        if len(cleaned) > limit:
            raise InventoryError("validation_error", f"{field} is too long.", 422)
        return cleaned

    def _clean_sku(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        if not cleaned:
            return None
        if len(cleaned) > 80:
            raise InventoryError("validation_error", "SKU is too long.", 422)
        return cleaned

    def _flush(self) -> None:
        try:
            self.session.flush()
        except IntegrityError as exc:
            raise InventoryError(
                "conflict",
                "That change conflicts with existing inventory data.",
                409,
            ) from exc

    @staticmethod
    def _remember(changes: dict, field: str, old, new) -> None:
        if old != new:
            changes[field] = {"old": old, "new": new}


def _blank_to_none(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _limit(value, size: int):
    text = _blank_to_none(value)
    if text is None:
        return None
    if len(text) > size:
        raise InventoryError("validation_error", "A text field is too long.", 422)
    return text


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _match(part: Part) -> dict:
    return {"id": part.id, "sku": part.sku, "name": part.name}


def _json_safe(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _display_preferences(value: dict) -> dict:
    if not isinstance(value, dict):
        raise InventoryError("validation_error", "Display preferences must be an object.", 422)
    page_size = int(value.get("page_size", 25))
    density = value.get("density", "comfortable")
    show_sku = bool(value.get("show_sku", True))
    if page_size < 10 or page_size > 100:
        raise InventoryError("validation_error", "Page size must be from 10 to 100.", 422)
    if density not in {"comfortable", "compact"}:
        raise InventoryError("validation_error", "Density must be comfortable or compact.", 422)
    return {"page_size": page_size, "density": density, "show_sku": show_sku}


def _public_url(value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    if len(text) > 300 or not (text.startswith("http://") or text.startswith("https://")):
        raise InventoryError(
            "validation_error",
            "Public URL must start with http:// or https://.",
            422,
        )
    if any(char.isspace() for char in text):
        raise InventoryError("validation_error", "Public URL cannot contain spaces.", 422)
    return text
