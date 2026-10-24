"""Pure business rules for Sente prepaid digital cash model."""
from typing import NamedTuple

PREMIUM_RATE_BP = 300
PREMIUM_MIN = 200
EXIT_RATE_BP = 120
EXIT_MIN = 100
MARGIN_CAP = 5_000
REBATE_PCT = 20
MIN_MINT = 2_000
CHECKPOINT_DAYS = 365


def _ensure_strict_int(val: int, name: str) -> None:
    if isinstance(val, bool) or not isinstance(val, int):
        raise ValueError(f"{name} must be an integer, got {type(val).__name__}: {val!r}")


class PremiumSplit(NamedTuple):
    exit_credit: int
    margin: int

    @property
    def total(self) -> int:
        return self.exit_credit + self.margin


class Settlement(NamedTuple):
    agent_paid: int
    rebate: int
    margin_recognized: int
    exit_credit_reserved: int


def split_premium(amount: int) -> PremiumSplit:
    """Calculate the split of premium into exit_credit and margin."""
    _ensure_strict_int(amount, "amount")
    if amount < MIN_MINT:
        raise ValueError(f"amount {amount} is below minimum mint {MIN_MINT}")
    total_uncapped = max(PREMIUM_MIN, (amount * PREMIUM_RATE_BP + 5000) // 10000)
    exit_credit = max(EXIT_MIN, (amount * EXIT_RATE_BP + 5000) // 10000)
    margin = min(MARGIN_CAP, total_uncapped - exit_credit)
    return PremiumSplit(exit_credit=exit_credit, margin=margin)


def commission_cum(amount: int, exit_credit: int, exited: int) -> int:
    """Calculate cumulative commission for given exited amount."""
    _ensure_strict_int(amount, "amount")
    _ensure_strict_int(exit_credit, "exit_credit")
    _ensure_strict_int(exited, "exited")
    return (exit_credit * exited + amount // 2) // amount


def settle_lot(amount: int, exit_credit: int, margin: int, exited: int) -> Settlement:
    """Settle a lot based on exited amount."""
    _ensure_strict_int(amount, "amount")
    _ensure_strict_int(exit_credit, "exit_credit")
    _ensure_strict_int(margin, "margin")
    _ensure_strict_int(exited, "exited")
    if not (0 <= exited <= amount):
        raise ValueError(f"exited {exited} must be in range 0..{amount}")
    premium = exit_credit + margin
    retained = amount - exited
    agent_paid = commission_cum(amount, exit_credit, exited)
    rebate = (premium * retained * REBATE_PCT + amount * 50) // (amount * 100)
    rebate = min(rebate, margin)
    margin_recognized = margin - rebate
    exit_credit_reserved = exit_credit - agent_paid
    return Settlement(
        agent_paid=agent_paid,
        rebate=rebate,
        margin_recognized=margin_recognized,
        exit_credit_reserved=exit_credit_reserved,
    )
