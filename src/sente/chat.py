"""Deterministic parser for Sente chat intents."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


_AMOUNT = r"(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?k?)"
_USER = r"[a-z][a-z0-9_]*"
_ACTIONS = re.compile(r"\b(?:send|pay|buy|top\s+up|cash\s+out)\b", re.IGNORECASE)


def _amount(value: str) -> int | None:
    normalized = value.replace(",", "")
    multiplier = Decimal(1000) if normalized.lower().endswith("k") else Decimal(1)
    if multiplier != 1:
        normalized = normalized[:-1]
    try:
        result = Decimal(normalized) * multiplier
    except InvalidOperation:
        return None
    if result <= 0 or result != result.to_integral_value():
        return None
    return int(result)


def _unknown(reason: str | None = None) -> dict:
    result = {"action": "unknown", "needs_confirmation": False}
    if reason:
        result["reason"] = reason
    return result


def parse_intent(text: str) -> dict:
    """Parse a supported intent without executing any operation."""
    normalized = text.strip().lower()
    action_matches = list(_ACTIONS.finditer(normalized))
    if len(action_matches) > 1:
        return _unknown("multiple_actions")
    if not action_matches:
        if re.search(r"\bbalance\b", normalized):
            return {"action": "balance", "needs_confirmation": False}
        return _unknown()

    patterns = (
        (
            "transfer",
            re.compile(rf"\bsend\s+({_AMOUNT})\s+to\s+({_USER})\b", re.IGNORECASE),
            ("amount", "to"),
        ),
        (
            "transfer",
            re.compile(rf"\bpay\s+({_USER})\s+({_AMOUNT})\b", re.IGNORECASE),
            ("to", "amount"),
        ),
        (
            "mint",
            re.compile(rf"\b(?:buy|top\s+up)\s+({_AMOUNT})\b", re.IGNORECASE),
            ("amount",),
        ),
        (
            "exit",
            re.compile(rf"\bcash\s+out\s+({_AMOUNT})(?:\s+at\s+({_USER}))?\b", re.IGNORECASE),
            ("amount", "agent"),
        ),
    )
    for action, pattern, fields in patterns:
        match = pattern.search(normalized)
        if not match:
            continue
        amount = _amount(match.group(1 if action != "transfer" or fields[0] == "amount" else 2))
        if amount is None:
            return _unknown()
        result = {"action": action}
        if action == "transfer" and fields[0] == "to":
            result["to"] = match.group(1).lower()
            result["amount"] = amount
        else:
            result["amount"] = amount
            if action == "transfer":
                result["to"] = match.group(2).lower()
        if action == "exit":
            result["agent"] = match.group(2).lower() if match.group(2) else None
        result["needs_confirmation"] = True
        return result
    return _unknown()
