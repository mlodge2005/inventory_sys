import io

import pytest
from rich.console import Console
from typer.testing import CliRunner

from app.core.config import get_settings
from app.db.session import init_database
from inventory_cli.context import open_service
from inventory_cli.main import app
from inventory_cli.menu import run_menu

runner = CliRunner()


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "inventory.db"
    monkeypatch.setenv("INVENTORY_DATABASE_PATH", str(path))
    monkeypatch.setenv("INVENTORY_ENVIRONMENT", "test")
    monkeypatch.setenv("INVENTORY_PUBLIC_URL", "http://10.1.2.3:8765")
    monkeypatch.setenv("INVENTORY_PORT", "8765")
    get_settings.cache_clear()
    from app.core.config import Settings

    init_database(
        Settings(environment="test", database_path=path, port=8765, public_url="http://10.1.2.3:8765"),
        migrate=False,
    )
    return path


def test_help_and_status(database):
    help_result = runner.invoke(app, ["help"])
    assert help_result.exit_code == 0
    assert "inventory" in help_result.output.lower() or "Usage" in help_result.output
    direct = runner.invoke(app, [])
    assert direct.exit_code == 0
    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0
    assert "Active parts" in status.output
    assert str(database) in status.output


def test_add_remove_ambiguity_and_transfer(database):
    assert runner.invoke(app, ["slot", "create", "110"]).exit_code == 0
    assert runner.invoke(app, ["slot", "create", "111"]).exit_code == 0
    created = runner.invoke(
        app,
        [
            "part",
            "create",
            "--name",
            "M3 screw",
            "--sku",
            "M3-SCREW",
            "--initial",
            "100",
            "--allocate",
            "110:40",
        ],
    )
    assert created.exit_code == 0, created.output
    nuts = runner.invoke(
        app,
        ["part", "create", "--name", "M3 nut", "--sku", "M3-NUT", "--initial", "20", "--allocate", "110:20"],
    )
    assert nuts.exit_code == 0, nuts.output
    ambiguous = runner.invoke(app, ["remove", "110", "5"])
    assert ambiguous.exit_code == 4
    assert "M3-SCREW" in ambiguous.output
    removed = runner.invoke(app, ["remove", "--slot", "110", "--part", "M3-SCREW", "--quantity", "5"])
    assert removed.exit_code == 0, removed.output
    assert "35" in removed.output
    nuts_left = runner.invoke(app, ["search", "M3-NUT"])
    assert "20" in nuts_left.output
    moved = runner.invoke(
        app,
        ["transfer", "--from", "110", "--to", "111", "--part", "M3-SCREW", "--quantity", "10"],
    )
    assert moved.exit_code == 0, moved.output
    drawer = runner.invoke(app, ["slot", "111"])
    assert drawer.exit_code == 0
    assert "M3 screw" in drawer.output
    renamed = runner.invoke(app, ["slot", "edit", "110", "--number", "210"])
    assert renamed.exit_code == 0, renamed.output
    still = runner.invoke(app, ["slot", "210"])
    assert "M3 nut" in still.output
    missing = runner.invoke(app, ["slot", "999"])
    assert missing.exit_code == 3
    invalid = runner.invoke(app, ["slot", "abc"])
    assert invalid.exit_code == 2
    baseline = runner.invoke(app, ["part", "baseline", "M3-SCREW", "--initial", "80"])
    assert baseline.exit_code == 0
    assert "Baseline 80" in baseline.output
    assert "Physical stock" in baseline.output


def test_low_stock_and_history(database):
    runner.invoke(app, ["slot", "create", "4"])
    runner.invoke(
        app,
        ["part", "create", "--name", "Low bolt", "--sku", "LOW", "--initial", "100", "--allocate", "4:5"],
    )
    low = runner.invoke(app, ["low"])
    assert low.exit_code == 0
    assert "LOW" in low.output
    assert "LOW_STOCK" in low.output
    history = runner.invoke(app, ["history", "--part", "LOW"])
    assert history.exit_code == 0
    assert "INITIAL_STOCK" in history.output


def test_qr_prints_url_and_blocks(database):
    result = runner.invoke(app, ["qr", "--ascii"])
    assert result.exit_code == 0, result.output
    assert "http://10.1.2.3:8765" in result.output
    assert "Inventory Website" in result.output


def test_search_and_menu(database):
    runner.invoke(app, ["slot", "create", "7"])
    runner.invoke(app, ["part", "create", "--name", "Search magnet", "--sku", "MAG", "--initial", "3", "--allocate", "7:3"])
    found = runner.invoke(app, ["search", "magnet"])
    assert found.exit_code == 0
    assert "Search magnet" in found.output
    buffer = io.StringIO()
    menu_console = Console(file=buffer, force_terminal=True, width=120)
    answers = iter(["1", "6", "0"])
    with open_service() as service:
        run_menu(service, console=menu_console, input_fn=lambda _prompt: next(answers))
    text = buffer.getvalue()
    assert "CYBERDECK INVENTORY" in text
    assert "Search magnet" in text
    assert "Goodbye." in text


def test_devseed_refuses_production(database, monkeypatch):
    monkeypatch.setenv("INVENTORY_ENVIRONMENT", "production")
    get_settings.cache_clear()
    refused = runner.invoke(app, ["devseed"])
    assert refused.exit_code != 0
    assert "production" in refused.output.lower()
