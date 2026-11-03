"""Reference data inserted by migrations and by create_all test setups.

These are category names and application preferences, not inventory quantities.
"""

DEFAULT_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("Fasteners", "Screws, nuts, bolts, washers, and standoffs.", "#c9a227"),
    ("Threaded Inserts", "Heat-set and press-fit threaded inserts.", "#d08c60"),
    ("Magnets", "Permanent magnets and magnetic catches.", "#6c8cff"),
    ("Electronic Components", "Passive and active electronic parts.", "#3ddc97"),
    ("Sensors", "Sensing modules and transducers.", "#4ecdc4"),
    ("Motors", "Motors, servos, and drivers.", "#ff8a5b"),
    ("Wiring", "Wire, cable, connectors, and crimps.", "#f5c16c"),
    ("Tools", "Tools stored with the parts drawers.", "#9aa6b8"),
    ("Miscellaneous", "Other hardware.", "#b0b8c4"),
)

DEFAULT_APP_NAME = "Cyberdeck Inventory"
DEFAULT_LOW_STOCK_PERCENT = 10
DEFAULT_LANDING_PAGE = "dashboard"
DEFAULT_UNIT = "pcs"
