from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import SlotInventory
from app.services.inventory import InventoryService


def _service(session_factory):
    session = session_factory()
    return session, InventoryService(session, source="api")


def test_drawers_parts_transfer_rename_and_baseline(session_factory):
    session, service = _service(session_factory)
    service.create_slot(slot_number=110)
    service.create_slot(slot_number=111)
    screws = service.create_part(
        {
            "name": "M3 x 10mm screw",
            "sku": "M3-SCREW",
            "initial_quantity": 100,
            "allocations": [{"slot_number": 110, "quantity": 100}],
        }
    )
    nuts = service.create_part(
        {
            "name": "M3 nut",
            "sku": "M3-NUT",
            "initial_quantity": 50,
            "allocations": [{"slot_number": 110, "quantity": 50}],
        }
    )
    session.commit()

    service.remove_stock(part_id=screws["id"], slot_number=110, quantity=5)
    session.commit()
    screws = service.part_view(screws["id"])
    nuts = service.part_view(nuts["id"])
    assert screws["current_quantity"] == 95
    assert nuts["current_quantity"] == 50
    assert screws["initial_quantity"] == 100

    service.transfer_stock(part_id=screws["id"], from_slot=110, to_slot=111, quantity=10)
    session.commit()
    service.update_slot(110, {"slot_number": 210})
    session.commit()
    drawer = service.slot_view(210)
    names = {item["sku"] for item in drawer["items"]}
    assert names == {"M3-SCREW", "M3-NUT"}
    moved = service.slot_view(111)
    assert moved["items"][0]["sku"] == "M3-SCREW"
    assert moved["items"][0]["quantity"] == 10

    service.add_stock(part_id=screws["id"], slot_number=210, quantity=100, transaction_type="RESTOCK")
    session.commit()
    screws = service.part_view(screws["id"])
    assert screws["initial_quantity"] == 100
    assert screws["current_quantity"] == 195

    service.update_part(screws["id"], {"initial_quantity": 80, "low_stock_percent": 10})
    session.commit()
    screws = service.part_view(screws["id"])
    assert screws["initial_quantity"] == 80
    assert screws["current_quantity"] == 195
    assert screws["threshold"] == 8
    audit = service.list_audit(entity_type="part", entity_id=screws["id"])
    assert any(event["action"] == "baseline.update" for event in audit)
    history, total = service.list_transactions(part_id=screws["id"], limit=20, offset=0)
    types = [row["transaction_type"] for row in history]
    assert "INITIAL_STOCK" in types
    assert "REMOVE" in types
    assert "TRANSFER" in types
    assert "RESTOCK" in types
    assert total >= 4
    session.close()


def test_negative_stock_and_duplicate_allocation(session_factory):
    session, service = _service(session_factory)
    service.create_slot(slot_number=110)
    part = service.create_part(
        {
            "name": "Washer",
            "sku": "WASH",
            "initial_quantity": 4,
            "allocations": [{"slot_number": 110, "quantity": 4}],
        }
    )
    session.commit()
    try:
        service.remove_stock(part_id=part["id"], slot_number=110, quantity=5)
        raise AssertionError("expected negative stock")
    except Exception as exc:
        session.rollback()
        assert exc.code == "negative_stock"
    assert service.part_view(part["id"])["current_quantity"] == 4
    slot = session.scalar(select(SlotInventory).where(SlotInventory.part_id == part["id"]))
    session.add(
        SlotInventory(
            id="duplicate",
            slot_id=slot.slot_id,
            part_id=slot.part_id,
            quantity=1,
            created_at=slot.created_at,
            updated_at=slot.updated_at,
        )
    )
    with pytest_raises_integrity(session):
        session.flush()
    session.close()


def test_zero_baseline_and_override(session_factory):
    session, service = _service(session_factory)
    unset = service.create_part({"name": "Unknown lot", "initial_quantity": 0})
    assert unset["threshold_configured"] is False
    assert unset["baseline_state"] == "BASELINE_NOT_SET"
    assert unset["status"] == "OUT_OF_STOCK"
    overridden = service.create_part(
        {"name": "Override", "initial_quantity": 0, "low_stock_override": 2}
    )
    assert overridden["threshold"] == 2
    assert overridden["threshold_configured"] is True
    session.close()


def test_one_part_in_many_drawers(session_factory):
    session, service = _service(session_factory)
    service.create_slot(slot_number=1)
    service.create_slot(slot_number=2)
    part = service.create_part(
        {
            "name": "Heat-set insert",
            "initial_quantity": 30,
            "allocations": [
                {"slot_number": 1, "quantity": 10},
                {"slot_number": 2, "quantity": 20},
            ],
        }
    )
    session.commit()
    assert part["current_quantity"] == 30
    assert {slot["slot_number"] for slot in part["slots"]} == {1, 2}
    session.close()


def test_delete_drawer_requires_confirmation_and_keeps_history(session_factory):
    session, service = _service(session_factory)
    service.create_slot(slot_number=110)
    part = service.create_part(
        {
            "name": "Standoff",
            "sku": "STAND",
            "initial_quantity": 6,
            "allocations": [{"slot_number": 110, "quantity": 6}],
        }
    )
    session.commit()
    try:
        service.delete_slot(110, confirm_remove_stock=False, reason=None)
        raise AssertionError("expected not_empty")
    except Exception as exc:
        session.rollback()
        assert exc.code == "not_empty"
    assert service.part_view(part["id"])["current_quantity"] == 6
    service.delete_slot(110, confirm_remove_stock=True, reason="cleared")
    session.commit()
    history, _total = service.list_transactions(part_id=part["id"], limit=10, offset=0)
    assert any(row["transaction_type"] == "REMOVE" and row["from_slot_number"] == 110 for row in history)
    try:
        service.slot_view(110)
        raise AssertionError("drawer should be gone")
    except Exception as exc:
        assert exc.code == "not_found"
    session.close()


def test_ambiguous_and_sole_part(session_factory):
    session, service = _service(session_factory)
    service.create_slot(slot_number=12)
    service.create_part(
        {
            "name": "Red wire",
            "sku": "WIRE-RED",
            "initial_quantity": 3,
            "allocations": [{"slot_number": 12, "quantity": 1}],
        }
    )
    only = service.require_sole_part(12)
    assert only.sku == "WIRE-RED"
    service.create_part(
        {
            "name": "Blue wire",
            "sku": "WIRE-BLUE",
            "initial_quantity": 3,
            "allocations": [{"slot_number": 12, "quantity": 1}],
        }
    )
    try:
        service.require_sole_part(12)
        raise AssertionError("expected ambiguous")
    except Exception as exc:
        assert exc.code == "ambiguous"
        assert len(exc.details["matches"]) == 2
    assert service.resolve_part("wire-red").sku == "WIRE-RED"
    session.close()


def pytest_raises_integrity(session):
    class _Context:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            session.rollback()
            if exc_type is None:
                raise AssertionError("expected IntegrityError")
            return issubclass(exc_type, IntegrityError)

    return _Context()
