"""Read models assembled from parts and their slot allocations."""

from __future__ import annotations

from app.models import Category, Part, Slot, SlotInventory, StockTransaction
from app.utils.stock_math import baseline_state, low_stock_threshold, stock_status
from app.utils.time import ensure_utc


def category_dict(category: Category | None) -> dict | None:
    if category is None:
        return None
    return {
        "id": category.id,
        "name": category.name,
        "description": category.description,
        "color": category.color,
        "created_at": ensure_utc(category.created_at),
        "updated_at": ensure_utc(category.updated_at),
    }


def build_part_dict(
    part: Part,
    allocations: list[tuple[SlotInventory, Slot]],
) -> dict:
    slots = []
    total = 0
    for allocation, slot in allocations:
        total += allocation.quantity
        slots.append(
            {
                "slot_id": slot.id,
                "slot_number": slot.slot_number,
                "label": slot.label,
                "location": slot.location,
                "quantity": allocation.quantity,
            }
        )
    slots.sort(key=lambda item: item["slot_number"])
    threshold, configured = low_stock_threshold(
        part.initial_quantity,
        part.low_stock_percent,
        part.low_stock_override,
    )
    return {
        "id": part.id,
        "sku": part.sku,
        "name": part.name,
        "description": part.description,
        "category": category_dict(part.category),
        "manufacturer": part.manufacturer,
        "manufacturer_part_number": part.manufacturer_part_number,
        "specifications": part.specifications or {},
        "unit": part.unit,
        "initial_quantity": part.initial_quantity,
        "low_stock_percent": part.low_stock_percent,
        "low_stock_override": part.low_stock_override,
        "notes": part.notes,
        "current_quantity": total,
        "threshold": threshold,
        "threshold_configured": configured,
        "baseline_state": baseline_state(part.initial_quantity, part.low_stock_override),
        "status": stock_status(total, threshold, configured),
        "slots": slots,
        "created_at": ensure_utc(part.created_at),
        "updated_at": ensure_utc(part.updated_at),
        "archived_at": ensure_utc(part.archived_at) if part.archived_at else None,
    }


def transaction_dict(row: StockTransaction) -> dict:
    return {
        "id": row.id,
        "part_id": row.part_id,
        "part_name": row.part_name_snapshot,
        "part_sku": row.part_sku_snapshot,
        "from_slot_id": row.from_slot_id,
        "from_slot_number": row.from_slot_number,
        "to_slot_id": row.to_slot_id,
        "to_slot_number": row.to_slot_number,
        "transaction_type": row.transaction_type,
        "quantity": row.quantity,
        "quantity_delta": row.quantity_delta,
        "quantity_before": row.quantity_before,
        "quantity_after": row.quantity_after,
        "dest_quantity_before": row.dest_quantity_before,
        "dest_quantity_after": row.dest_quantity_after,
        "quantity_scope": "slot",
        "reason": row.reason,
        "source": row.source,
        "created_at": ensure_utc(row.created_at),
    }
