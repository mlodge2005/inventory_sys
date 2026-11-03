"""Interactive menu. Each action calls InventoryService and commits on success."""

from __future__ import annotations

from collections.abc import Callable

from rich.console import Console

from app.core.errors import InventoryError
from app.services.inventory import InventoryService
from inventory_cli.render import parts_table, slot_table, transactions_table

MENU = """
CYBERDECK INVENTORY
────────────────────────────────

1. View Inventory
2. Search Parts
3. Manage Stock
4. Create / Edit Part
5. Manage Drawers
6. Low Stock Report
7. Recent Transactions
8. Website QR Code
9. Settings

0. Exit
""".strip("\n")


def run_menu(
    service: InventoryService,
    *,
    console: Console | None = None,
    input_fn: Callable[[str], str] | None = None,
    qr_fn: Callable[[], None] | None = None,
) -> None:
    console = console or Console()
    reader = input_fn or (lambda prompt: input(prompt))

    def ask(prompt: str) -> str:
        try:
            value = reader(prompt if prompt.endswith(" ") else prompt + " ")
        except (EOFError, StopIteration, KeyboardInterrupt):
            return "0"
        return (value or "").strip()

    while True:
        console.print(MENU)
        choice = ask("Select")
        if choice in {"0", "q", "quit", "exit"}:
            console.print("Goodbye.")
            return
        try:
            if choice == "1":
                views, total = service.list_part_views(limit=50, offset=0)
                parts_table(console, views)
                console.print(f"{total} part type(s).")
            elif choice == "2":
                query = ask("Search")
                views, total = service.list_part_views(search=query, limit=50, offset=0)
                parts_table(console, views)
                console.print(f"{total} match(es).")
            elif choice == "3":
                _stock_menu(service, console, ask)
            elif choice == "4":
                _part_menu(service, console, ask)
            elif choice == "5":
                _drawer_menu(service, console, ask)
            elif choice == "6":
                alerts, total = service.low_stock(limit=50, offset=0)
                parts_table(console, alerts)
                console.print(f"{total} low or out of stock.")
            elif choice == "7":
                rows, total = service.list_transactions(limit=15, offset=0)
                transactions_table(console, rows)
                console.print(f"{total} transaction(s) on record.")
            elif choice == "8":
                if qr_fn is not None:
                    qr_fn()
                else:
                    from inventory_cli.qr_cmd import show_qr

                    show_qr(console, service)
            elif choice == "9":
                _settings_menu(service, console, ask)
            else:
                console.print("Choose a number from the menu.")
                continue
            service.session.commit()
        except InventoryError as exc:
            service.session.rollback()
            console.print(exc.message)
            for match in exc.details.get("matches") or []:
                console.print(f"  {match.get('sku') or '-'}  {match.get('name')}")
        except ValueError:
            service.session.rollback()
            console.print("Enter a whole number.")


def _stock_menu(service: InventoryService, console: Console, ask) -> None:
    console.print("a add   r remove   t transfer   j adjust")
    action = ask("Action").lower()
    slot_number = int(ask("Drawer"))
    if action in {"a", "add", "r", "remove"}:
        token = ask("Part (blank if the drawer has one part)")
        quantity = int(ask("Quantity"))
        if token:
            part = service.resolve_part(token)
        else:
            part = service.require_sole_part(slot_number)
        if action in {"a", "add"}:
            service.add_stock(part_id=part.id, slot_number=slot_number, quantity=quantity, transaction_type="ADD")
            console.print(f"Added {quantity} to drawer {slot_number}.")
        else:
            service.remove_stock(part_id=part.id, slot_number=slot_number, quantity=quantity)
            console.print(f"Removed {quantity} from drawer {slot_number}.")
        return
    if action in {"t", "transfer"}:
        destination = int(ask("Destination drawer"))
        token = ask("Part")
        quantity = int(ask("Quantity"))
        part = service.resolve_part(token)
        service.transfer_stock(part_id=part.id, from_slot=slot_number, to_slot=destination, quantity=quantity)
        console.print(f"Moved {quantity} from {slot_number} to {destination}.")
        return
    if action in {"j", "adjust"}:
        token = ask("Part")
        new_quantity = int(ask("New quantity"))
        part = service.resolve_part(token)
        service.adjust_stock(part_id=part.id, slot_number=slot_number, new_quantity=new_quantity)
        console.print(f"Drawer {slot_number} now records {new_quantity}.")
        return
    raise InventoryError("validation_error", "Unknown stock action.", 422)


def _part_menu(service: InventoryService, console: Console, ask) -> None:
    console.print("c create   e edit baseline   s show")
    action = ask("Action").lower()
    if action in {"c", "create"}:
        name = ask("Name")
        sku = ask("SKU (optional)") or None
        initial = int(ask("Fixed baseline quantity") or "0")
        slot_text = ask("Allocate to drawer (blank to skip)")
        quantity_text = ask("Physical quantity") if slot_text else "0"
        data = {"name": name, "sku": sku, "initial_quantity": initial, "allocations": []}
        if slot_text:
            data["allocations"].append({"slot_number": int(slot_text), "quantity": int(quantity_text)})
        view = service.create_part(data)
        console.print(
            f"Created {view['name']}. Baseline {view['initial_quantity']}. "
            f"Physical stock {view['current_quantity']}."
        )
        return
    token = ask("Part")
    part = service.resolve_part(token)
    if action in {"s", "show"}:
        parts_table(console, [service.part_view(part.id)])
        return
    if action in {"e", "edit"}:
        initial = ask("New baseline (blank keeps current)")
        percent = ask("Low-stock percent (blank keeps current)")
        fields = {}
        if initial:
            fields["initial_quantity"] = int(initial)
        if percent:
            fields["low_stock_percent"] = int(percent)
        view = service.update_part(part.id, fields)
        console.print(f"Baseline is now {view['initial_quantity']}. Physical stock is still {view['current_quantity']}.")
        return
    raise InventoryError("validation_error", "Unknown part action.", 422)


def _drawer_menu(service: InventoryService, console: Console, ask) -> None:
    console.print("c create   s show   e edit number   a archive")
    action = ask("Action").lower()
    if action in {"c", "create"}:
        number = int(ask("Drawer number"))
        label = ask("Label (optional)") or None
        view = service.create_slot(slot_number=number, label=label)
        console.print(f"Created drawer {view['slot_number']}.")
        return
    number = int(ask("Drawer"))
    if action in {"s", "show"}:
        slot_table(console, service.slot_view(number))
        return
    if action in {"e", "edit"}:
        new_number = int(ask("New drawer number"))
        view = service.update_slot(number, {"slot_number": new_number})
        console.print(f"Drawer is now {view['slot_number']}. Inventory stayed with it.")
        return
    if action in {"a", "archive"}:
        confirm = ask("Type REMOVE to record removal of any stock, or press Enter if empty")
        service.archive_slot(number, confirm_remove_stock=confirm == "REMOVE", reason="Archived from CLI")
        console.print(f"Archived drawer {number}.")
        return
    raise InventoryError("validation_error", "Unknown drawer action.", 422)


def _settings_menu(service: InventoryService, console: Console, ask) -> None:
    current = service.get_settings_view()
    console.print(f"Name: {current['application_name']}")
    console.print(f"Theme: {current['theme_preference']}")
    console.print(f"Default low-stock percent: {current['default_low_stock_percent']}")
    console.print(f"Public URL: {current['preferred_public_url'] or '(detect)'}")
    if ask("Edit settings? [y/N]").lower() != "y":
        return
    percent = ask("Default low-stock percent (blank keeps current)")
    url = ask("Public URL (blank keeps current, '-' clears)")
    fields = {}
    if percent:
        fields["default_low_stock_percent"] = int(percent)
    if url == "-":
        fields["preferred_public_url"] = None
    elif url:
        fields["preferred_public_url"] = url
    updated = service.update_settings(fields)
    console.print(f"Saved. Default low-stock percent is {updated['default_low_stock_percent']}.")
