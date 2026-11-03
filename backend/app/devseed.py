"""Development-only sample drawers and parts.

Every record is named DEMO and the notes say the quantities are fake.
The installer never calls this module. It refuses to run when
INVENTORY_ENVIRONMENT=production.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.errors import InventoryError
from app.services.inventory import InventoryService

DEMO_NOTE = "DEMO data for development only. These quantities are not real stock."


def load_demo(service: InventoryService) -> list[str]:
    if get_settings().environment == "production":
        raise InventoryError(
            "forbidden",
            "Refusing to load demo inventory while INVENTORY_ENVIRONMENT=production.",
            403,
        )
    created: list[str] = []
    categories = {item["name"]: item["id"] for item in service.list_categories()}
    for number, label in ((110, "DEMO fasteners"), (111, "DEMO magnets"), (112, "DEMO empty")):
        try:
            service.create_slot(slot_number=number, label=label, description=DEMO_NOTE)
            created.append(f"drawer {number}")
        except InventoryError as exc:
            if exc.code != "conflict":
                raise
    _ensure_part(
        service,
        created,
        sku="DEMO-M3-SCREW",
        name="DEMO M3 x 10mm screw",
        category_id=categories.get("Fasteners"),
        initial_quantity=100,
        allocations=[{"slot_number": 110, "quantity": 100}],
    )
    _ensure_part(
        service,
        created,
        sku="DEMO-M3-NUT",
        name="DEMO M3 nut",
        category_id=categories.get("Fasteners"),
        initial_quantity=80,
        allocations=[{"slot_number": 110, "quantity": 80}],
    )
    _ensure_part(
        service,
        created,
        sku="DEMO-MAG-6",
        name="DEMO 6mm magnet",
        category_id=categories.get("Magnets"),
        initial_quantity=20,
        allocations=[{"slot_number": 111, "quantity": 2}],
    )
    _ensure_part(
        service,
        created,
        sku="DEMO-SENSOR",
        name="DEMO unallocated sensor",
        category_id=categories.get("Sensors"),
        initial_quantity=10,
        allocations=[],
    )
    return created


def _ensure_part(service: InventoryService, created: list[str], **payload) -> None:
    try:
        service.resolve_part(payload["sku"])
    except InventoryError as exc:
        if exc.code != "not_found":
            raise
        payload["notes"] = DEMO_NOTE
        payload["description"] = DEMO_NOTE
        service.create_part(payload)
        created.append(payload["sku"])
