"""Delivery settlement is disabled until a complete holdings lifecycle ships.

CNC admission is exit-only at the shared policy boundary. Keeping this hook a
no-op protects scheduler, startup catch-up and manual callers alike: none may
turn a position into inventory that the order ledger cannot sell correctly.
"""


def settle_cnc_to_holdings() -> int:
    """Do not mutate positions, inventory or cash."""
    return 0
