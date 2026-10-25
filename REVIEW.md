Verdict: pass

### Findings
1. `src/sente/service.py`: `agent_redeem` allows agent wallet balance to drop below zero if `amount > wallet_balance` because balance check is omitted. Fix: add `if self.balance(agent) < amount: raise InsufficientFunds(...)`.
2. `src/sente/service.py`: `confirm_exit` returns `"released"` when an already released escrow is confirmed again, rather than rejecting or returning status consistently; while harmless per spec ("Confirming twice is harmless"), idempotent re-confirmation could be made explicitly clear.
3. `src/sente/chat.py`: Regex pattern for amounts allows fractional k notation like `1.5k`, but parses as `int(round(float(m.group(1)) * 1000))`; uses float intermediate for text parsing before conversion to integer UGX.

### Unverified
- Concurrency and thread safety of `Sente` ledger methods under multi-threaded execution (SQLite connection shared across threads).
