"""Shared enumerations. Stock math lives in app.utils.stock_math."""

TRANSACTION_TYPES = frozenset(
    {"INITIAL_STOCK", "ADD", "REMOVE", "TRANSFER", "ADJUST", "RESTOCK"}
)
INCREASE_TYPES = frozenset({"INITIAL_STOCK", "ADD", "RESTOCK"})
SOURCES = frozenset({"web", "cli", "api", "migration", "import"})
STATUSES = frozenset({"OUT_OF_STOCK", "LOW_STOCK", "IN_STOCK"})
LANDING_PAGES = frozenset(
    {"dashboard", "inventory", "drawers", "alerts", "transactions"}
)
THEMES = frozenset({"dark", "light", "cyberpunk", "high-contrast", "custom"})

# Piece counts are integers. These caps stop accidental huge writes on a Pi.
MAX_QUANTITY = 1_000_000
MAX_SLOT_NUMBER = 999_999
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_LIMIT = 50
MAX_IMPORT_ROWS = 5_000
MAX_SPEC_BYTES = 16_384
