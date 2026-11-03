def test_health_and_reference_data(client):
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["version"]
    categories = client.get("/api/v1/categories").json()
    assert {item["name"] for item in categories} >= {
        "Fasteners",
        "Threaded Inserts",
        "Magnets",
        "Electronic Components",
        "Sensors",
        "Motors",
        "Wiring",
        "Tools",
        "Miscellaneous",
    }
    assert client.get("/openapi.json").status_code == 200
    assert "BrowserRequestHeader" in client.get("/openapi.json").json()["components"]["securitySchemes"]
    assert client.get("/docs").status_code == 200
    assert "cdn." not in client.get("/docs").text


def test_acceptance_flow_over_http(client):
    assert client.post("/api/v1/slots", json={"slot_number": 110, "label": "Screws"}).status_code == 201
    assert client.post("/api/v1/slots", json={"slot_number": 111}).status_code == 201
    fasteners = next(item for item in client.get("/api/v1/categories").json() if item["name"] == "Fasteners")
    screws = client.post(
        "/api/v1/items",
        json={
            "name": "M3 x 10mm screw",
            "sku": "M3-SCREW",
            "category_id": fasteners["id"],
            "initial_quantity": 100,
            "allocations": [{"slot_number": 110, "quantity": 100}],
        },
    )
    assert screws.status_code == 201, screws.text
    nuts = client.post(
        "/api/v1/items",
        json={
            "name": "M3 nut",
            "sku": "M3-NUT",
            "category_id": fasteners["id"],
            "initial_quantity": 80,
            "allocations": [{"slot_number": 110, "quantity": 80}],
        },
    )
    assert nuts.status_code == 201, nuts.text
    screw_id = screws.json()["id"]
    nut_id = nuts.json()["id"]

    removed = client.post(
        "/api/v1/stock/remove",
        json={"part_id": screw_id, "slot_number": 110, "quantity": 5, "reason": "used"},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["quantity_before"] == 100
    assert removed.json()["quantity_after"] == 95
    assert removed.json()["quantity_scope"] == "slot"
    assert client.get(f"/api/v1/items/{nut_id}").json()["current_quantity"] == 80

    transferred = client.post(
        "/api/v1/stock/transfer",
        json={"part_id": screw_id, "from_slot": 110, "to_slot": 111, "quantity": 10},
    )
    assert transferred.status_code == 200, transferred.text
    assert transferred.json()["dest_quantity_after"] == 10

    renamed = client.patch("/api/v1/slots/110", json={"slot_number": 210})
    assert renamed.status_code == 200, renamed.text
    drawer = client.get("/api/v1/slots/210").json()
    assert {item["sku"] for item in drawer["items"]} == {"M3-SCREW", "M3-NUT"}

    restocked = client.post(
        "/api/v1/stock/add",
        json={"part_id": screw_id, "slot_number": 210, "quantity": 100, "transaction_type": "RESTOCK"},
    )
    assert restocked.status_code == 200
    current = client.get(f"/api/v1/items/{screw_id}").json()
    assert current["initial_quantity"] == 100
    assert current["current_quantity"] == 195

    edited = client.patch(f"/api/v1/items/{screw_id}", json={"initial_quantity": 50})
    assert edited.status_code == 200
    edited_body = edited.json()
    assert edited_body["initial_quantity"] == 50
    assert edited_body["current_quantity"] == 195
    assert edited_body["threshold"] == 5

    blocked = client.post(
        "/api/v1/stock/remove",
        json={"part_id": nut_id, "slot_number": 210, "quantity": 500},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "negative_stock"
    assert client.get(f"/api/v1/items/{nut_id}").json()["current_quantity"] == 80

    history = client.get("/api/v1/transactions", params={"part_id": screw_id}).json()
    assert history["total"] >= 4
    assert {row["transaction_type"] for row in history["items"]} >= {"INITIAL_STOCK", "REMOVE", "TRANSFER", "RESTOCK"}


def test_filters_pagination_and_low_stock(client):
    client.post("/api/v1/slots", json={"slot_number": 5})
    for index in range(12):
        client.post(
            "/api/v1/items",
            json={"name": f"Part {index:02d}", "sku": f"P{index:02d}", "initial_quantity": 100},
        )
    low = client.post(
        "/api/v1/items",
        json={
            "name": "Low magnet",
            "sku": "MAG-LOW",
            "initial_quantity": 100,
            "allocations": [{"slot_number": 5, "quantity": 5}],
        },
    ).json()
    assert low["status"] == "LOW_STOCK"
    assert low["threshold"] == 10
    page = client.get("/api/v1/items", params={"limit": 5, "offset": 0, "sort": "name"}).json()
    assert page["total"] >= 13
    assert len(page["items"]) == 5
    found = client.get("/api/v1/items", params={"search": "MAG-LOW"}).json()
    assert found["total"] == 1
    by_status = client.get("/api/v1/items", params={"status": "LOW_STOCK"}).json()
    assert any(item["sku"] == "MAG-LOW" for item in by_status["items"])
    by_slot = client.get("/api/v1/items", params={"slot": 5}).json()
    assert by_slot["total"] == 1
    alerts = client.get("/api/v1/alerts/low-stock").json()
    assert alerts["items"][0]["status"] in {"OUT_OF_STOCK", "LOW_STOCK"}
    assert any(item["sku"] == "MAG-LOW" for item in alerts["items"])
    stats = client.get("/api/v1/stats").json()
    assert stats["low_stock_part_types"] >= 1
    assert stats["occupied_slots"] == 1
    assert stats["total_units"] == 5


def test_invalid_input_and_csrf(client, bare_client):
    missing = bare_client.post("/api/v1/slots", json={"slot_number": 9})
    assert missing.status_code == 403
    bad = client.post("/api/v1/items", json={"name": ""})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "validation_error"
    assert client.get("/api/v1/slots/9999").status_code == 404
    assert client.post("/api/v1/slots", json={"slot_number": 0}).status_code == 422
    foreign = client.post(
        "/api/v1/slots",
        json={"slot_number": 8},
        headers={"Origin": "http://evil.example", "X-Cyberdeck-Request": "1"},
    )
    assert foreign.status_code == 403


def test_settings_theme_round_trip(client):
    updated = client.patch(
        "/api/v1/settings",
        json={"theme_preference": "cyberpunk", "application_name": "Bench Inventory"},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["theme_preference"] == "cyberpunk"
    assert body["application_name"] == "Bench Inventory"
    assert body["color_palette"]["accent"] == "#e23ca8"
    rejected = client.patch(
        "/api/v1/settings",
        json={
            "theme_preference": "custom",
            "color_palette": {
                "bg": "#ffffff",
                "surface": "#ffffff",
                "text": "#ffffff",
                "muted": "#ffffff",
                "border": "#000000",
                "accent": "#ffffff",
                "accent_2": "#000000",
                "danger": "#ffffff",
                "warning": "#ffffff",
                "ok": "#ffffff",
                "info": "#ffffff",
            },
        },
    )
    assert rejected.status_code == 422
    assert client.get("/api/v1/themes").json()["presets"]["dark"]["bg"] == "#0e1116"


def test_restart_persists_rows(settings, client):
    assert client.post("/api/v1/slots", json={"slot_number": 42, "label": "kept"}).status_code == 201
    from app.main import create_app

    reopened = create_app(settings)
    from fastapi.testclient import TestClient

    with TestClient(reopened) as again:
        again.headers.update({"X-Cyberdeck-Request": "1"})
        listing = again.get("/api/v1/slots/42")
        assert listing.status_code == 200
        assert listing.json()["label"] == "kept"


def test_payload_limit(bare_client):
    response = bare_client.post(
        "/api/v1/slots",
        content=b"{}",
        headers={
            "X-Cyberdeck-Request": "1",
            "Content-Type": "application/json",
            "Content-Length": "3000000",
        },
    )
    assert response.status_code == 413
