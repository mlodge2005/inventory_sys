"""Built-in palettes. Custom themes must pass the same contrast checks."""

from __future__ import annotations

from app.utils.color import PALETTE_KEYS

PRESETS: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0e1116",
        "surface": "#171c24",
        "text": "#e7ecf3",
        "muted": "#9aabbf",
        "border": "#2c3646",
        "accent": "#3ddc97",
        "accent_2": "#7aa2ff",
        "danger": "#ff5d6c",
        "warning": "#f5c16c",
        "ok": "#3ddc97",
        "info": "#7aa2ff",
    },
    "light": {
        "bg": "#f4f6f8",
        "surface": "#ffffff",
        "text": "#1a1f26",
        "muted": "#4d5d72",
        "border": "#d5dde6",
        "accent": "#0b7a4b",
        "accent_2": "#1d4e89",
        "danger": "#b42318",
        "warning": "#8a5a00",
        "ok": "#0b7a4b",
        "info": "#1d4e89",
    },
    "cyberpunk": {
        "bg": "#0c0d14",
        "surface": "#141625",
        "text": "#e8f0ff",
        "muted": "#a9b3d4",
        "border": "#2a2e48",
        "accent": "#e23ca8",
        "accent_2": "#2ec5d6",
        "danger": "#ff5d6c",
        "warning": "#f0c15a",
        "ok": "#5ddeaf",
        "info": "#2ec5d6",
    },
    "high-contrast": {
        "bg": "#000000",
        "surface": "#0a0a0a",
        "text": "#ffffff",
        "muted": "#e6e6e6",
        "border": "#ffffff",
        "accent": "#ffe600",
        "accent_2": "#00e5ff",
        "danger": "#ff5a5a",
        "warning": "#ffd000",
        "ok": "#00ff88",
        "info": "#66d1ff",
    },
}


def preset_palette(name: str) -> dict[str, str] | None:
    palette = PRESETS.get(name)
    if palette is None:
        return None
    return {key: palette[key] for key in PALETTE_KEYS}
