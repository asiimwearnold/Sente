"""Service ledger implementation for Sente prepaid digital cash model."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sente.rules import (
    CHECKPOINT_DAYS,
    commission_cum,
    settle_lot,
    split_premium,
)


def _ensure_strict_int(val: int, name: str) -> None:
    if isinstance(val, bool) or not isinstance(val, int):
        raise ValueError(f"{name} must be an integer, got {type(val).__name__}: {val!r}")


class InsufficientFunds(Exception):
    """Raised when a wallet or account has insufficient funds."""


class EscrowError(Exception):
    """Raised on invalid escrow operations or states."""


@dataclass
class Lot:
    id: int
    buyer: str
    amount: int
    premium: int
    exit_credit: int
    margin: int
    created_at: datetime
    exited: int = 0
    settled: bool = False


@dataclass
class Escrow:
    id: int
    holder: str
    agent: str
    amount: int
    status: str = "locked"  # "locked", "released", "cancelled"
    agent_confirmed: bool = False
    holder_confirmed: bool = False


class Sente:
    def __init__(
        self,
        db_path: str = ":memory:",
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.clock: Callable[[], datetime] = (
            clock if clock is not None else lambda: datetime.now(timezone.utc)
        )
        self._wallets: dict[str, int] = {}
        self._bank: int = 0
        self._exit_pool: int = 0
        self._deferred_margin: int = 0
        self._revenue: int = 0
        self._escrows: dict[int, Escrow] = {}
        self._lots: list[Lot] = []
        self._next_lot_id: int = 1
        self._next_escrow_id: int = 1
        self._seen_idem_keys: set[str] = set()

    def register(self, name: str) -> None:
        """Create a wallet (idempotent)."""
        if name not in self._wallets:
            self._wallets[name] = 0

    def balance(self, name: str) -> int:
        """Get wallet balance. Raises KeyError for unknown names."""
        if name not in self._wallets:
            raise KeyError(f"Unknown wallet: {name}")
        return self._wallets[name]

    def mint(self, buyer: str, amount: int) -> Lot:
        """Mint digital cash for buyer. Uses split_premium."""
        _ensure_strict_int(amount, "amount")
        if buyer not in self._wallets:
            raise KeyError(f"Unknown buyer: {buyer}")
        split = split_premium(amount)

        self._bank += amount + split.total
        self._wallets[buyer] += amount
        self._exit_pool += split.exit_credit
        self._deferred_margin += split.margin

        lot = Lot(
            id=self._next_lot_id,
            buyer=buyer,
            amount=amount,
            premium=split.total,
            exit_credit=split.exit_credit,
            margin=split.margin,
            created_at=self.clock(),
            exited=0,
            settled=False,
        )
        self._next_lot_id += 1
        self._lots.append(lot)
        return lot

    def transfer(
        self, src: str, dst: str, amount: int, idem_key: Optional[str] = None
    ) -> None:
        """Transfer between wallets. Free and instant."""
        _ensure_strict_int(amount, "amount")
        if idem_key is not None and idem_key in self._seen_idem_keys:
            return

        if src not in self._wallets:
            raise KeyError(f"Unknown src wallet: {src}")
        if dst not in self._wallets:
            raise KeyError(f"Unknown dst wallet: {dst}")
        if amount <= 0:
            raise ValueError(f"Amount must be positive, got {amount}")
        if self._wallets[src] < amount:
            raise InsufficientFunds(
                f"Src wallet {src} has {self._wallets[src]}, required {amount}"
            )

        self._wallets[src] -= amount
        self._wallets[dst] += amount

        if idem_key is not None:
            self._seen_idem_keys.add(idem_key)

    def request_exit(self, holder: str, agent: str, amount: int) -> int:
        """Locks holder's Sente in escrow. Same validation as transfer."""
        _ensure_strict_int(amount, "amount")
        if holder not in self._wallets:
            raise KeyError(f"Unknown holder wallet: {holder}")
        if agent not in self._wallets:
            raise KeyError(f"Unknown agent wallet: {agent}")
        if amount <= 0:
            raise ValueError(f"Amount must be positive, got {amount}")
        if self._wallets[holder] < amount:
            raise InsufficientFunds(
                f"Holder wallet {holder} has {self._wallets[holder]}, required {amount}"
            )

        self._wallets[holder] -= amount
        escrow_id = self._next_escrow_id
        self._next_escrow_id += 1

        self._escrows[escrow_id] = Escrow(
            id=escrow_id,
            holder=holder,
            agent=agent,
            amount=amount,
            status="locked",
        )
        return escrow_id

    def confirm_exit(self, escrow_id: int, by: str) -> str:
        """Confirm exit escrow by agent or holder. Release when both confirmed."""
        if escrow_id not in self._escrows:
            raise KeyError(f"Unknown escrow: {escrow_id}")
        if by not in ("agent", "holder"):
            raise ValueError(f"Invalid confirmation party: {by}")

        escrow = self._escrows[escrow_id]
        if escrow.status == "cancelled":
            raise EscrowError("Cannot confirm a cancelled escrow")

        if escrow.status == "released":
            return "released"

        if by == "agent":
            escrow.agent_confirmed = True
        elif by == "holder":
            escrow.holder_confirmed = True

        if escrow.agent_confirmed and escrow.holder_confirmed:
            self._release_escrow(escrow)
            return "released"

        return "locked"

    def _release_escrow(self, escrow: Escrow) -> None:
        """Execute escrow release logic."""
        escrow.status = "released"
        remaining_to_consume = escrow.amount
        total_commission = 0

        # FIFO across lots ordered by created_at then id
        sorted_lots = sorted(self._lots, key=lambda l: (l.created_at, l.id))
        for lot in sorted_lots:
            if remaining_to_consume <= 0:
                break
            available = lot.amount - lot.exited
            if available <= 0:
                continue

            consume = min(remaining_to_consume, available)
            before = lot.exited
            after = before + consume
            lot.exited = after
            remaining_to_consume -= consume

            comm = commission_cum(lot.amount, lot.exit_credit, after) - commission_cum(
                lot.amount, lot.exit_credit, before
            )
            total_commission += comm

            # If fully exited and not yet settled: move whole margin to revenue, mark settled
            if lot.exited == lot.amount and not lot.settled:
                self._deferred_margin -= lot.margin
                self._revenue += lot.margin
                lot.settled = True

        # Escrowed amount + commission goes to agent wallet from escrow and exit pool
        self._exit_pool -= total_commission
        self._wallets[escrow.agent] += escrow.amount + total_commission

    def cancel_exit(self, escrow_id: int) -> str:
        """Refund the holder. Idempotent. EscrowError if already released."""
        if escrow_id not in self._escrows:
            raise KeyError(f"Unknown escrow: {escrow_id}")

        escrow = self._escrows[escrow_id]
        if escrow.status == "released":
            raise EscrowError("Cannot cancel an already released escrow")

        if escrow.status == "cancelled":
            return "cancelled"

        escrow.status = "cancelled"
        self._wallets[escrow.holder] += escrow.amount
        return "cancelled"

    def escrow_status(self, escrow_id: int) -> str:
        """Returns locked, released, or cancelled."""
        if escrow_id not in self._escrows:
            raise KeyError(f"Unknown escrow: {escrow_id}")
        return self._escrows[escrow_id].status

    def agent_redeem(self, agent: str, amount: int) -> None:
        """Agent turns Sente into cash: wallet and bank both decrease."""
        _ensure_strict_int(amount, "amount")
        if agent not in self._wallets:
            raise KeyError(f"Unknown agent: {agent}")
        if amount <= 0:
            raise ValueError(f"Amount must be positive, got {amount}")
        if self._wallets[agent] < amount:
            raise InsufficientFunds(
                f"Agent wallet {agent} has {self._wallets[agent]}, required {amount}"
            )
        if self._bank < amount:
            raise InsufficientFunds(
                f"Bank has {self._bank}, required {amount}"
            )

        self._wallets[agent] -= amount
        self._bank -= amount

    def run_checkpoint(self) -> list[dict]:
        """Settle lots older than CHECKPOINT_DAYS."""
        now = self.clock()
        results = []

        sorted_lots = sorted(self._lots, key=lambda l: (l.created_at, l.id))
        for lot in sorted_lots:
            if lot.settled:
                continue
            if now - lot.created_at < timedelta(days=CHECKPOINT_DAYS):
                continue

            settlement = settle_lot(
                amount=lot.amount,
                exit_credit=lot.exit_credit,
                margin=lot.margin,
                exited=lot.exited,
            )

            # pay rebate into buyer's wallet from deferred margin
            self._wallets[lot.buyer] += settlement.rebate
            # move remaining margin to revenue
            self._deferred_margin -= lot.margin
            self._revenue += settlement.margin_recognized
            lot.settled = True

            results.append(
                {
                    "lot_id": lot.id,
                    "buyer": lot.buyer,
                    "rebate": settlement.rebate,
                    "margin_recognized": settlement.margin_recognized,
                }
            )

        return results

    def lots(self) -> list[Lot]:
        """Ordered by creation time then id."""
        return sorted(self._lots, key=lambda l: (l.created_at, l.id))

    def audit(self) -> dict[str, int]:
        """Return ledger balance breakdown."""
        escrow_sum = sum(
            e.amount for e in self._escrows.values() if e.status == "locked"
        )
        wallets_sum = sum(self._wallets.values())
        return {
            "bank": self._bank,
            "wallets": wallets_sum,
            "escrow": escrow_sum,
            "exit_pool": self._exit_pool,
            "deferred_margin": self._deferred_margin,
            "revenue": self._revenue,
        }
