"""Integer stock thresholds.

threshold = low_stock_override when that value is set,
otherwise ceil(initial_quantity * low_stock_percent / 100).

Ceil is computed with integers: (n + 99) // 100. Floating point is never used.
A zero baseline with no override is not a configured threshold.
"""

from __future__ import annotations


def low_stock_threshold(
    initial_quantity: int,
    low_stock_percent: int,
    low_stock_override: int | None,
) -> tuple[int | None, bool]:
    """Return ``(threshold, configured)``.

    ``configured`` is false only when the baseline is zero and no absolute
    override has been set. Callers should surface ``BASELINE_NOT_SET`` then.
    """

    if initial_quantity < 0:
        raise ValueError("initial_quantity must be nonnegative")
    if low_stock_percent < 0 or low_stock_percent > 100:
        raise ValueError("low_stock_percent must be between 0 and 100")
    if low_stock_override is not None:
        if low_stock_override < 0:
            raise ValueError("low_stock_override must be nonnegative")
        return low_stock_override, True
    if initial_quantity <= 0:
        return None, False
    return (initial_quantity * low_stock_percent + 99) // 100, True


def stock_status(quantity: int, threshold: int | None, configured: bool) -> str:
    """OUT_OF_STOCK at zero, LOW_STOCK at or below a configured threshold, else IN_STOCK."""

    if quantity < 0:
        raise ValueError("quantity must be nonnegative")
    if quantity == 0:
        return "OUT_OF_STOCK"
    if configured and threshold is not None and quantity <= threshold:
        return "LOW_STOCK"
    return "IN_STOCK"


def baseline_state(initial_quantity: int, low_stock_override: int | None) -> str:
    if initial_quantity <= 0 and low_stock_override is None:
        return "BASELINE_NOT_SET"
    return "OK"
