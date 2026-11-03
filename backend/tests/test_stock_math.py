import pytest

from app.core.themes import PRESETS
from app.utils.color import contrast_ratio, validate_palette
from app.utils.stock_math import baseline_state, low_stock_threshold, stock_status


@pytest.mark.parametrize(
    ("initial", "percent", "override", "threshold", "configured"),
    [
        (100, 10, None, 10, True),
        (101, 10, None, 11, True),
        (15, 10, None, 2, True),
        (1, 10, None, 1, True),
        (100, 0, None, 0, True),
        (0, 10, None, None, False),
        (0, 10, 0, 0, True),
        (100, 10, 25, 25, True),
    ],
)
def test_threshold(initial, percent, override, threshold, configured):
    assert low_stock_threshold(initial, percent, override) == (threshold, configured)


def test_status_bands():
    assert stock_status(0, 10, True) == "OUT_OF_STOCK"
    assert stock_status(10, 10, True) == "LOW_STOCK"
    assert stock_status(11, 10, True) == "IN_STOCK"
    assert stock_status(5, None, False) == "IN_STOCK"
    assert stock_status(0, None, False) == "OUT_OF_STOCK"


def test_baseline_state():
    assert baseline_state(0, None) == "BASELINE_NOT_SET"
    assert baseline_state(0, 3) == "OK"
    assert baseline_state(10, None) == "OK"


def test_presets_are_readable():
    for name, palette in PRESETS.items():
        validate_palette(palette)
        assert contrast_ratio(palette["text"], palette["bg"]) >= 4.5, name
