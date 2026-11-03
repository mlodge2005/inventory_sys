"""Direct commands and the interactive menu for `inventory`."""

from __future__ import annotations

import sys
from functools import wraps
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from app.core.config import get_settings
from app.core.errors import InventoryError, exit_code_for
from app.db.session import init_database
from app.devseed import load_demo
from app.services.csv_io import apply_plan, export_csv, plan_bundle
from inventory_cli.context import open_service
from inventory_cli.menu import run_menu
from inventory_cli.qr_cmd import show_qr
from inventory_cli.render import emit_json, parts_table, slot_table, transactions_table

console = Console()
app = typer.Typer(add_completion=False, no_args_is_help=False, help="Cyberdeck Inventory")


def _guard(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except InventoryError as exc:
            console.print(exc.message)
            if exc.guidance and exc.guidance not in exc.message:
                console.print(exc.guidance)
            for match in exc.details.get("matches") or []:
                console.print(f"  {match.get('sku') or '-'}  {match.get('name')}")
            raise typer.Exit(code=exit_code_for(exc)) from exc
        except typer.Exit:
            raise
        except Exception:
            console.print("Cannot complete that action. Check the values and try again.")
            raise typer.Exit(code=1) from None

    return wrapper


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    """Open the menu in a terminal, or show help when there is no terminal."""

    if ctx.invoked_subcommand is not None:
        return
    if sys.stdin.isatty() and sys.stdout.isatty():
        with open_service() as service:
            run_menu(service, console=console)
        raise typer.Exit()
    typer.echo(ctx.get_help())


@app.command("help")
def help_cmd(ctx: typer.Context) -> None:
    """Show command help."""

    typer.echo(ctx.parent.get_help() if ctx.parent else ctx.get_help())


@app.command("list")
@_guard
def list_cmd(
    search: Annotated[str | None, typer.Option("--search")] = None,
    status: Annotated[str | None, typer.Option("--status")] = None,
    category: Annotated[str | None, typer.Option("--category")] = None,
    slot: Annotated[int | None, typer.Option("--slot")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List parts."""

    with open_service() as service:
        views, total = service.list_part_views(
            search=search,
            status=status,
            category=category,
            slot_number=slot,
            limit=limit,
            offset=0,
        )
    if as_json:
        emit_json({"items": views, "total": total})
        return
    parts_table(console, views)
    console.print(f"{total} part type(s).")


@app.command("search")
@_guard
def search_cmd(
    query: Annotated[str, typer.Argument()],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Search parts by name, SKU, or description."""

    list_cmd(search=query, status=None, category=None, slot=None, limit=50, as_json=as_json)


@app.command("slot")
@_guard
def slot_cmd(
    args: Annotated[list[str] | None, typer.Argument()] = None,
    label: Annotated[str | None, typer.Option("--label")] = None,
    location: Annotated[str | None, typer.Option("--location")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    number: Annotated[int | None, typer.Option("--number")] = None,
    confirm_remove_stock: Annotated[bool, typer.Option("--confirm-remove-stock")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show or change a drawer: `inventory slot 110` or `inventory slot create 110`."""

    tokens = args or []
    with open_service() as service:
        if not tokens:
            rows, total = service.list_slots(limit=100, offset=0)
            if as_json:
                emit_json({"items": rows, "total": total})
            else:
                for row in rows:
                    console.print(
                        f"{row['slot_number']:>6}  {row['label'] or '-'}  "
                        f"{row['part_count']} parts  {row['total_units']} units"
                    )
            return
        action = tokens[0]
        if action.isdigit() and len(tokens) == 1:
            view = service.slot_view(int(action))
            if as_json:
                emit_json(view)
            else:
                slot_table(console, view)
            return
        if action == "create" and len(tokens) >= 2 and tokens[1].isdigit():
            view = service.create_slot(
                slot_number=int(tokens[1]),
                label=label,
                location=location,
                description=description,
            )
            console.print(f"Created drawer {view['slot_number']}.")
            return
        if action == "edit" and len(tokens) >= 2 and tokens[1].isdigit():
            fields = {}
            if number is not None:
                fields["slot_number"] = number
            if label is not None:
                fields["label"] = label
            if location is not None:
                fields["location"] = location
            if description is not None:
                fields["description"] = description
            view = service.update_slot(int(tokens[1]), fields)
            console.print(f"Updated drawer {view['slot_number']}.")
            return
        if action == "archive" and len(tokens) >= 2 and tokens[1].isdigit():
            service.archive_slot(
                int(tokens[1]),
                confirm_remove_stock=confirm_remove_stock,
                reason="Archived from CLI",
            )
            console.print(f"Archived drawer {tokens[1]}.")
            return
        if action == "delete" and len(tokens) >= 2 and tokens[1].isdigit():
            service.delete_slot(
                int(tokens[1]),
                confirm_remove_stock=confirm_remove_stock,
                reason="Deleted from CLI",
            )
            console.print("Drawer deleted successfully.")
            return
    raise InventoryError(
        "validation_error",
        "Enter a drawer number, or use create, edit, archive, or delete.",
        422,
        field="slot_number",
        guidance="Select an existing drawer or create a new one.",
    )


@app.command("add")
@_guard
def add_cmd(
    slot: Annotated[int | None, typer.Argument()] = None,
    quantity: Annotated[int | None, typer.Argument()] = None,
    slot_opt: Annotated[int | None, typer.Option("--slot")] = None,
    part: Annotated[str | None, typer.Option("--part")] = None,
    quantity_opt: Annotated[int | None, typer.Option("--quantity", "-q")] = None,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
    kind: Annotated[str, typer.Option("--type")] = "ADD",
) -> None:
    """Add stock. Without --part, the drawer must contain one part type."""

    _change("add", slot, quantity, slot_opt, part, quantity_opt, reason, kind)


@app.command("remove")
@_guard
def remove_cmd(
    slot: Annotated[int | None, typer.Argument()] = None,
    quantity: Annotated[int | None, typer.Argument()] = None,
    slot_opt: Annotated[int | None, typer.Option("--slot")] = None,
    part: Annotated[str | None, typer.Option("--part")] = None,
    quantity_opt: Annotated[int | None, typer.Option("--quantity", "-q")] = None,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
) -> None:
    """Remove stock. Without --part, the drawer must contain one part type."""

    _change("remove", slot, quantity, slot_opt, part, quantity_opt, reason, "REMOVE")


def _change(action, slot, quantity, slot_opt, part, quantity_opt, reason, kind) -> None:
    slot_number = slot_opt if slot_opt is not None else slot
    qty = quantity_opt if quantity_opt is not None else quantity
    if slot_number is None or qty is None:
        raise InventoryError(
            "validation_error",
            "Provide a drawer and a quantity. Example: inventory add 110 25",
            422,
        )
    with open_service() as service:
        if part:
            chosen = service.resolve_part(part)
        else:
            chosen = service.require_sole_part(slot_number)
        if action == "add":
            service.add_stock(
                part_id=chosen.id,
                slot_number=slot_number,
                quantity=qty,
                transaction_type=kind,
                reason=reason,
            )
            verb = "Added"
        else:
            service.remove_stock(part_id=chosen.id, slot_number=slot_number, quantity=qty, reason=reason)
            verb = "Removed"
        view = service.part_view(chosen.id)
    console.print(f"{verb} {qty}. {view['name']} now totals {view['current_quantity']}.")


@app.command("transfer")
@_guard
def transfer_cmd(
    from_slot: Annotated[int, typer.Option("--from")],
    to_slot: Annotated[int, typer.Option("--to")],
    part: Annotated[str, typer.Option("--part")],
    quantity: Annotated[int, typer.Option("--quantity", "-q")],
    reason: Annotated[str | None, typer.Option("--reason")] = None,
) -> None:
    """Move pieces of one part from one drawer to another."""

    with open_service() as service:
        chosen = service.resolve_part(part)
        service.transfer_stock(
            part_id=chosen.id,
            from_slot=from_slot,
            to_slot=to_slot,
            quantity=quantity,
            reason=reason,
        )
        view = service.part_view(chosen.id)
    console.print(f"Moved {quantity} from drawer {from_slot} to {to_slot}. Total is {view['current_quantity']}.")


@app.command("low")
@_guard
def low_cmd(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Show low-stock and out-of-stock parts."""

    with open_service() as service:
        views, total = service.low_stock(limit=200, offset=0)
    if as_json:
        emit_json({"items": views, "total": total})
        return
    parts_table(console, views)
    console.print(f"{total} part type(s) need attention.")


@app.command("history")
@_guard
def history_cmd(
    limit: Annotated[int, typer.Option("--limit")] = 20,
    part: Annotated[str | None, typer.Option("--part")] = None,
    slot: Annotated[int | None, typer.Option("--slot")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show recent stock transactions."""

    with open_service() as service:
        part_id = service.resolve_part(part).id if part else None
        rows, total = service.list_transactions(part_id=part_id, slot_number=slot, limit=limit, offset=0)
    if as_json:
        emit_json({"items": rows, "total": total})
        return
    transactions_table(console, rows)
    console.print(f"{total} transaction(s).")


@app.command("qr")
@_guard
def qr_cmd(
    url: Annotated[str | None, typer.Option("--url")] = None,
    index: Annotated[int | None, typer.Option("--index")] = None,
    ascii_mode: Annotated[bool, typer.Option("--ascii")] = False,
) -> None:
    """Print a QR code and the inventory website URL."""

    with open_service() as service:
        show_qr(console, service, explicit=url, index=index, ascii_mode=ascii_mode)


@app.command("status")
@_guard
def status_cmd() -> None:
    """Show version, database path, and stock counts."""

    from app import __version__ as app_version
    from app.maintenance import schema_revision

    settings = get_settings()
    with open_service() as service:
        stats = service.stats()
        settings_view = service.get_settings_view()
    revision = schema_revision(settings.resolved_database_path)
    console.print(f"Cyberdeck Inventory {app_version}")
    console.print(f"Database: {settings.resolved_database_path}")
    console.print(f"Schema: {revision or 'unversioned'}")
    console.print(f"Application name: {settings_view['application_name']}")
    console.print(f"Active parts: {stats['active_part_types']}")
    console.print(f"Occupied drawers: {stats['occupied_slots']}")
    console.print(f"Units: {stats['total_units']}")
    console.print(f"Low stock: {stats['low_stock_part_types']}")
    console.print(f"Out of stock: {stats['out_of_stock_part_types']}")
    console.print(f"Suggested URL port: {settings.port}")


@app.command("part")
@_guard
def part_cmd(
    args: Annotated[list[str] | None, typer.Argument()] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    sku: Annotated[str | None, typer.Option("--sku")] = None,
    initial: Annotated[int | None, typer.Option("--initial")] = None,
    percent: Annotated[int | None, typer.Option("--percent")] = None,
    category: Annotated[str | None, typer.Option("--category")] = None,
    allocate: Annotated[list[str] | None, typer.Option("--allocate")] = None,
    override: Annotated[int | None, typer.Option("--override")] = None,
    clear_override: Annotated[bool, typer.Option("--clear-override")] = False,
) -> None:
    """Create or edit a part. Baseline changes do not move physical stock."""

    tokens = args or []
    if not tokens:
        raise InventoryError("validation_error", "Usage: inventory part create|show|baseline ...", 422)
    action = tokens[0]
    with open_service() as service:
        if action == "create":
            if not name:
                raise InventoryError("validation_error", "Pass --name.", 422)
            allocations = [_parse_allocation(item) for item in allocate or []]
            category_id = None
            if category:
                category_id = service._resolve_category_filter(category).id
            view = service.create_part(
                {
                    "name": name,
                    "sku": sku,
                    "initial_quantity": initial or 0,
                    "low_stock_percent": percent,
                    "category_id": category_id,
                    "allocations": allocations,
                }
            )
            console.print(
                f"Created {view['name']}. Baseline {view['initial_quantity']}. "
                f"Physical stock {view['current_quantity']}."
            )
            return
        if len(tokens) < 2:
            raise InventoryError("validation_error", "Name the part.", 422)
        part = service.resolve_part(tokens[1])
        if action == "show":
            parts_table(console, [service.part_view(part.id)])
            return
        if action == "baseline":
            fields = {}
            if initial is not None:
                fields["initial_quantity"] = initial
            if percent is not None:
                fields["low_stock_percent"] = percent
            if clear_override:
                fields["low_stock_override"] = None
            elif override is not None:
                fields["low_stock_override"] = override
            view = service.update_part(part.id, fields)
            console.print(
                f"Baseline {view['initial_quantity']}. Threshold "
                f"{view['threshold'] if view['threshold_configured'] else 'not set'}. "
                f"Physical stock {view['current_quantity']}."
            )
            return
    raise InventoryError("validation_error", "Unknown part action.", 422)


@app.command("export")
@_guard
def export_cmd(kind: Annotated[str, typer.Argument()]) -> None:
    """Write parts, slots, allocations, categories, or transactions CSV to stdout."""

    with open_service() as service:
        sys.stdout.write(export_csv(service, kind))


@app.command("import")
@_guard
def import_cmd(
    kind: Annotated[str, typer.Argument()],
    file: Annotated[Path, typer.Option("--file", exists=True, dir_okay=False)],
    commit: Annotated[bool, typer.Option("--commit")] = False,
) -> None:
    """Validate a CSV import. Nothing is written unless --commit is set."""

    key = f"{kind}_csv"
    if key not in {"categories_csv", "slots_csv", "parts_csv", "allocations_csv"}:
        raise InventoryError("validation_error", "Import kind must be categories, slots, parts, or allocations.", 422)
    payload = {key: file.read_text(encoding="utf-8")}
    with open_service() as service:
        plan = plan_bundle(service, **payload)
        if not plan.ok or not commit:
            for error in plan.errors:
                console.print(f"row {error['row']}: {error['message']}")
            console.print(str(plan.summary))
            if not plan.ok:
                raise InventoryError("validation_error", "Import was not applied.", 422)
            if not commit:
                console.print("Preview only. Re-run with --commit to apply.")
                return
        service.source = "import"
        apply_plan(service, plan)
    console.print("Import applied.")


@app.command("init")
@_guard
def init_cmd() -> None:
    """Create or migrate the local database. Does not insert demo quantities."""

    settings = get_settings()
    init_database(settings, migrate=True)
    console.print(f"Database ready at {settings.resolved_database_path}")


@app.command("devseed")
@_guard
def devseed_cmd() -> None:
    """Load clearly marked DEMO parts. Refuses to run in production."""

    with open_service() as service:
        created = load_demo(service)
    if created:
        console.print("Loaded demo records: " + ", ".join(created))
    else:
        console.print("Demo records were already present.")


def _parse_allocation(value: str) -> dict:
    slot_text, _, qty_text = value.partition(":")
    if not slot_text.isdigit() or not qty_text.isdigit():
        raise InventoryError("validation_error", "Use --allocate DRAWER:QUANTITY, for example 110:25.", 422)
    return {"slot_number": int(slot_text), "quantity": int(qty_text)}


if __name__ == "__main__":
    app()
