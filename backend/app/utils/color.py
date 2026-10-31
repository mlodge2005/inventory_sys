"""Hex color checks and WCAG contrast. The server is the authority on saved themes."""

from __future__ import annotations

import re

from app.core.errors import InventoryError

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

PALETTE_KEYS = (
    "bg",
    "surface",
    "text",
    "muted",
    "border",
    "accent",
    "accent_2",
    "danger",
    "warning",
    "ok",
    "info",
)


def normalize_hex(value: str) -> str:
    if not isinstance(value, str) or not HEX_RE.match(value.strip()):
        raise InventoryError(
            "validation_error",
            "Colors must be #RRGGBB hexadecimal values.",
            422,
        )
    return value.strip().lower()


def _channel(value: float) -> float:
    value = value / 255.0
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    hex_color = normalize_hex(color)
    red = int(hex_color[1:3], 16)
    green = int(hex_color[3:5], 16)
    blue = int(hex_color[5:7], 16)
    return (
        0.2126 * _channel(red)
        + 0.7152 * _channel(green)
        + 0.0722 * _channel(blue)
    )


def contrast_ratio(foreground: str, background: str) -> float:
    left = relative_luminance(foreground)
    right = relative_luminance(background)
    lighter = max(left, right)
    darker = min(left, right)
    return (lighter + 0.05) / (darker + 0.05)


def validate_palette(colors: dict) -> dict[str, str]:
    if not isinstance(colors, dict):
        raise InventoryError("validation_error", "Color palette must be an object.", 422)
    unknown = set(colors) - set(PALETTE_KEYS)
    missing = [key for key in PALETTE_KEYS if key not in colors]
    if unknown or missing:
        raise InventoryError(
            "validation_error",
            "Color palette must contain exactly the documented keys.",
            422,
            {"missing": missing, "unknown": sorted(unknown)},
        )
    normalized = {key: normalize_hex(str(colors[key])) for key in PALETTE_KEYS}
    problems: list[str] = []
    checks = (
        ("text", "bg", 4.5),
        ("text", "surface", 4.5),
        ("muted", "bg", 3.0),
        ("muted", "surface", 3.0),
        ("accent", "bg", 3.0),
        ("danger", "surface", 3.0),
        ("warning", "surface", 3.0),
        ("ok", "surface", 3.0),
        ("info", "surface", 3.0),
    )
    for foreground, background, minimum in checks:
        ratio = contrast_ratio(normalized[foreground], normalized[background])
        if ratio < minimum:
            problems.append(
                f"{foreground} on {background} is {ratio:.2f}:1; need at least {minimum:.1f}:1"
            )
    if problems:
        raise InventoryError(
            "validation_error",
            "Color palette does not meet readability contrast.",
            422,
            {"problems": problems},
        )
    return normalized
