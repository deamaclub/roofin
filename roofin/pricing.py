"""Price the offer so the money left after payment fees is at least the profit you want.

Fee presets are typical published US rates for a one-off payment to a person/small business. They change;
check your processor and pass --fee-pct / --fee-fixed if yours differ.
"""
from __future__ import annotations

import math

PROCESSORS = {
    # name: (percent, fixed cents)
    "paypal": (3.49, 49),
    "stripe": (2.9, 30),
    "venmo": (1.9, 10),
    "cashapp": (2.75, 0),
    "zelle": (0.0, 0),  # bank-to-bank, no fee
}


def fee_cents(amount_cents: int, pct: float, fixed: int) -> int:
    return math.ceil(amount_cents * pct / 100) + fixed if amount_cents else 0


def price_for_profit(profit_cents: int, pct: float, fixed: int, round_to: int = 100) -> int:
    """Smallest price (rounded up to whole dollars by default) whose payout after fees >= profit."""
    raw = math.ceil((profit_cents + fixed) / (1 - pct / 100))
    price = math.ceil(raw / round_to) * round_to
    while price - fee_cents(price, pct, fixed) < profit_cents:
        price += round_to
    return price
