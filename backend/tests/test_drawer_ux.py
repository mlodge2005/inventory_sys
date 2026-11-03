"""Drawer editing, deletion rules, and user-facing API errors."""


def _part(client, *, slot: int, quantity: int, name: str = "screws", sku: str = "SCR"):
    created = client.post(
        "/api/v1/items",
        json={
            "name": name,
            "sku": sku,
            "initial_quantity": 100,
            "allocations": [{"slot_number": slot, "quantity": quantity}],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_renumber_keeps_inventory_and_transactions(client):
    created = client.post("/api/v1/slots", json={"slot_number": 110, "label": "Bin"})
    assert created.status_code == 201, created.text
    slot_id = created.json()["id"]
    part = _part(client, slot=110, quantity=40)
    renamed = client.patch(
        "/api/v1/slots/110",
        json={"slot_number": 210, "label": "M3 Fasteners", "description": "Left cabinet", "location": "Bench"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["id"] == slot_id
    drawer = client.get("/api/v1/slots/210")
    assert drawer.status_code == 200
    body = drawer.json()
    assert body["id"] == slot_id
    assert body["label"] == "M3 Fasteners"
    assert body["description"] == "Left cabinet"
    assert body["location"] == "Bench"
    assert body["items"][0]["quantity"] == 40
    removed = client.post(
        "/api/v1/stock/remove",
        json={"part_id": part["id"], "slot_number": 210, "quantity": 5, "reason": "used"},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["quantity_before"] == 40
    assert removed.json()["quantity_after"] == 35
    assert removed.json()["from_slot_number"] == 210
    again = client.get(f"/api/v1/items/{part['id']}").json()
    assert again["initial_quantity"] == 100
    assert again["current_quantity"] == 35


def test_create_and_delete_empty_drawer(client):
    created = client.post("/api/v1/slots", json={"slot_number": 7, "label": "Empty"})
    assert created.status_code == 201
    deleted = client.delete("/api/v1/slots/7")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    missing = client.get("/api/v1/slots/7")
    assert missing.status_code == 404
    assert missing.json()["error"]["message"] == "Drawer 7 does not exist. Select an existing drawer or create a new one."
    assert missing.json()["error"]["field"] == "slot_number"
    assert missing.json()["error"]["guidance"]


def test_occupied_drawer_cannot_be_deleted(client):
    client.post("/api/v1/slots", json={"slot_number": 110})
    part = _part(client, slot=110, quantity=8, name="screws", sku="SCR-8")
    rejected = client.delete("/api/v1/slots/110")
    assert rejected.status_code == 409
    payload = rejected.json()["error"]
    assert payload["code"] == "not_empty"
    assert payload["message"] == "Drawer 110 still contains parts. Transfer or remove them before deleting it."
    assert payload["field"] == "slot_number"
    assert client.get(f"/api/v1/items/{part['id']}").json()["current_quantity"] == 8
    assert client.get("/api/v1/slots/110").status_code == 200


def test_duplicate_and_unknown_drawer_messages(client):
    assert client.post("/api/v1/slots", json={"slot_number": 110}).status_code == 201
    duplicate = client.post("/api/v1/slots", json={"slot_number": 110})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["message"] == "Drawer 110 already exists. Choose another number."
    assert duplicate.json()["error"]["field"] == "slot_number"
    part = _part(client, slot=110, quantity=8, name="screws", sku="SCR-MSG")
    missing = client.post(
        "/api/v1/stock/remove",
        json={"part_id": part["id"], "slot_number": 999, "quantity": 1},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["message"] == "Drawer 999 does not exist. Select an existing drawer or create a new one."
    short = client.post(
        "/api/v1/stock/remove",
        json={"part_id": part["id"], "slot_number": 110, "quantity": 15},
    )
    assert short.status_code == 409
    assert short.json()["error"]["message"] == "Cannot remove 15 screws from drawer 110. Only 8 are available."
    assert short.json()["error"]["field"] == "quantity"
    gone = client.post(
        "/api/v1/stock/remove",
        json={"part_id": "missing-part", "slot_number": 110, "quantity": 1},
    )
    assert gone.status_code == 404
    assert gone.json()["error"]["message"] == "This part could not be found. It may have been deleted or archived."


def test_validation_error_names_the_field(client):
    response = client.post(
        "/api/v1/stock/remove",
        json={"part_id": "part", "slot_number": 110, "quantity": "many"},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"] == "Enter a whole number greater than zero."
    assert error["field"] == "quantity"
    assert "sqlalchemy" not in error["message"].lower()
    assert "Traceback" not in response.text


def test_part_can_be_assigned_to_several_drawers_without_changing_baseline(client):
    client.post("/api/v1/slots", json={"slot_number": 110, "label": "M3 Fasteners"})
    client.post("/api/v1/slots", json={"slot_number": 111, "label": "Spare"})
    created = client.post(
        "/api/v1/items",
        json={
            "name": "M3 screw",
            "sku": "M3-MULTI",
            "initial_quantity": 100,
            "allocations": [
                {"slot_number": 110, "quantity": 25},
                {"slot_number": 111, "quantity": 15},
            ],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["initial_quantity"] == 100
    assert body["current_quantity"] == 40
    assert {slot["slot_number"] for slot in body["slots"]} == {110, 111}
    history = client.get(f"/api/v1/items/{body['id']}/transactions").json()
    assert {item["transaction_type"] for item in history["items"]} == {"INITIAL_STOCK"}
    assert sum(item["quantity"] for item in history["items"]) == 40
