"""Show a local QR code for the inventory website."""

from __future__ import annotations

import sys

from rich.console import Console

from app.core.config import get_settings
from app.services.inventory import InventoryService
from app.services.network import detect_addresses, select_public_url
from app.utils.qr_terminal import render_qr


def show_qr(
    console: Console,
    service: InventoryService | None = None,
    *,
    explicit: str | None = None,
    index: int | None = None,
    ascii_mode: bool = False,
    input_fn=None,
) -> str:
    settings = get_settings()
    saved = None
    if service is not None:
        saved = service.get_settings_view().get("preferred_public_url")
    addresses = detect_addresses()
    interactive = input_fn is not None or (sys.stdin.isatty() and sys.stdout.isatty() and explicit is None and index is None)
    if input_fn is None and interactive:
        input_fn = lambda prompt: input(prompt + " ")
    if not interactive:
        input_fn = None
    selected, candidates = select_public_url(
        port=settings.port,
        addresses=addresses,
        explicit=explicit,
        env_url=settings.public_url or None,
        settings_url=saved,
        index=index,
        interactive=bool(input_fn),
        input_fn=input_fn,
    )
    picture = render_qr(selected, ascii_mode=ascii_mode or not _stdout_can_unicode())
    console.print(picture)
    console.print("")
    console.print("Inventory Website")
    console.print(selected)
    extras = [url for url in candidates if url != selected]
    if extras:
        console.print("Other detected URLs:")
        for url in extras:
            console.print(f"  {url}")
    return selected


def _stdout_can_unicode() -> bool:
    encoding = getattr(sys.stdout, "encoding", None) or ""
    return "utf" in encoding.lower()
