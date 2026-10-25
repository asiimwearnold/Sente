Verdict: pass

### Findings
None. All money handling uses strict integer arithmetic and satisfies conservation.

### Verification notes
- Validated money conservation in `Sente.audit()`: `bank == wallets + escrow + exit_pool + deferred_margin + revenue` across all mint, transfer, escrow release/cancellation, checkpoint rebate/margin recognition, and agent redemption operations.
- Validated rounding rules and formulas against SPEC.md for `split_premium`, `commission_cum`, and `settle_lot`.
- Confirmed type checks, idempotency, FIFO lot consumption, and error handling meet specification.
- Test suite passes cleanly with 36 tests across `test_rules.py`, `test_service.py`, and `test_chat.py`.
