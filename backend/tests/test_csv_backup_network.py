import json

from app.maintenance import backup_database, integrity_check, restore_database
from app.services.network import (
    classify_interface,
    parse_ip_addr_json,
    parse_ip_addr_text,
    select_public_url,
)
from app.utils.qr_terminal import render_qr


def test_csv_import_is_atomic(client):
    preview = client.post(
        "/api/v1/import/preview",
        json={
            "categories_csv": "name,description,color\nDemo Bins,Temporary,not-a-color\n",
            "parts_csv": "sku,name,description,category,manufacturer,manufacturer_part_number,unit,initial_quantity,low_stock_percent,low_stock_override,notes,specifications_json\nBAD,,oops,Demo Bins,,,,,,,\n",
        },
    )
    assert preview.status_code == 200
    assert preview.json()["ok"] is False
    before = client.get("/api/v1/items").json()["total"]
    commit = client.post(
        "/api/v1/import/commit",
        json={
            "categories_csv": "name,description,color\nDemo Bins,Temporary,#336699\n",
            "parts_csv": "sku,name,description,category,manufacturer,manufacturer_part_number,unit,initial_quantity,low_stock_percent,low_stock_override,notes,specifications_json\nBAD,,oops,Demo Bins,,,,,,,\n",
        },
    )
    assert commit.status_code == 422
    assert client.get("/api/v1/items").json()["total"] == before
    assert all(item["name"] != "Demo Bins" for item in client.get("/api/v1/categories").json())


def test_csv_round_trip_uses_stock_transactions(client):
    client.post("/api/v1/slots", json={"slot_number": 110})
    created = client.post(
        "/api/v1/import/commit",
        json={
            "parts_csv": "sku,name,description,category,manufacturer,manufacturer_part_number,unit,initial_quantity,low_stock_percent,low_stock_override,notes,specifications_json\nM3-CSV,CSV screw,,Fasteners,,,pcs,40,10,,,\"{}\"\n",
            "allocations_csv": "slot_number,part_sku,part_name,quantity\n110,M3-CSV,CSV screw,40\n",
        },
    )
    assert created.status_code == 200, created.text
    exported = client.get("/api/v1/export/parts").text
    assert "M3-CSV" in exported
    part = client.get("/api/v1/items", params={"search": "M3-CSV"}).json()["items"][0]
    assert part["current_quantity"] == 40
    assert part["initial_quantity"] == 40
    history = client.get("/api/v1/transactions", params={"part_id": part["id"]}).json()
    assert history["items"][0]["source"] == "import"
    assert history["items"][0]["transaction_type"] == "INITIAL_STOCK"


def test_backup_and_restore_round_trip(client, settings, tmp_path):
    client.post("/api/v1/slots", json={"slot_number": 77, "label": "backup"})
    dest = tmp_path / "backups" / "inventory-test.db"
    metadata = backup_database(settings.resolved_database_path, dest)
    assert metadata["integrity"] == "ok"
    assert metadata["sha256"]
    assert json.loads(dest.with_suffix(".db.json").read_text())["sha256"] == metadata["sha256"]
    assert integrity_check(dest) == "ok"
    # Mutate the live database, then restore the snapshot.
    client.patch("/api/v1/slots/77", json={"label": "changed"})
    result = restore_database(dest, settings.resolved_database_path)
    assert result["integrity"] == "ok"
    assert result["safety_copy"]
    from app.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as again:
        again.headers.update({"X-Cyberdeck-Request": "1"})
        assert again.get("/api/v1/slots/77").json()["label"] == "backup"


def test_network_selection_ignores_docker_and_default_route():
    payload = [
        {"ifname": "lo", "addr_info": [{"family": "inet", "local": "127.0.0.1"}]},
        {"ifname": "docker0", "addr_info": [{"family": "inet", "local": "172.17.0.1"}]},
        {"ifname": "eth0", "addr_info": [{"family": "inet", "local": "10.42.0.20"}]},
        {"ifname": "tailscale0", "addr_info": [{"family": "inet", "local": "100.64.1.8"}]},
        {"ifname": "wlan0", "addr_info": [{"family": "inet", "local": "10.42.0.1"}]},
    ]
    found = parse_ip_addr_json(payload)
    kinds = {(item.interface, item.kind) for item in found}
    assert ("docker0", "virtual") not in kinds
    assert ("eth0", "ethernet") in kinds
    assert ("tailscale0", "tailscale") in kinds
    assert ("wlan0", "hotspot") in kinds
    text = "2: eth0: <BROADCAST>\n    inet 192.168.1.20/24 brd 192.168.1.255 scope global eth0\n"
    assert parse_ip_addr_text(text)[0].ip == "192.168.1.20"
    selected, candidates = select_public_url(port=8765, addresses=found, env_url="http://inventory.local:8765")
    assert selected == "http://inventory.local:8765"
    assert any(url.endswith(":8765") for url in candidates)
    lan, _candidates = select_public_url(port=8765, addresses=found)
    assert lan == "http://10.42.0.20:8765"
    assert classify_interface("tailscale0", "100.64.1.8") == "tailscale"


def test_qr_contains_blocks_without_network():
    rendered = render_qr("http://192.168.1.20:8765")
    assert "█" in rendered or "▀" in rendered or "▄" in rendered
    assert "\n" in rendered
    ascii_qr = render_qr("http://192.168.1.20:8765", ascii_mode=True)
    assert ascii_qr.strip()
