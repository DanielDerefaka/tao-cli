# taox Fix Plan

**Based on:** AUDIT_REPORT.md
**Date:** 2026-02-04

---

## Overview

This plan addresses all issues identified in the audit, organized into milestones. Each milestone is independently testable and deployable.

---

## Milestone 1: Fix Transaction Execution (P0 - Critical)

**Goal:** Make transactions actually work
**Estimated Effort:** 30 minutes
**Dependencies:** None

### Step 1.1: Fix pexpect.spawn() argument passing

**File:** `src/taox/commands/executor.py`
**Line:** 289

**Current (Broken):**
```python
child = pexpect.spawn(" ".join(cmd), timeout=self.timeout, encoding="utf-8")
```

**Fixed:**
```python
child = pexpect.spawn(cmd[0], cmd[1:], timeout=self.timeout, encoding="utf-8")
```

**Why:** `pexpect.spawn()` with a string passes it to the shell, causing argument parsing issues. Using list form passes arguments directly to the executable.

### Step 1.2: Expand PASSWORD_PROMPTS patterns

**File:** `src/taox/commands/executor.py`
**Lines:** 17-24

**Current:**
```python
PASSWORD_PROMPTS = [
    "Enter password",
    "Password:",
    "password:",
    "Unlock your coldkey",
    "Enter your password",
    "Passphrase",
]
```

**Updated:**
```python
PASSWORD_PROMPTS = [
    "Enter password",
    "Password:",
    "password:",
    "Unlock your coldkey",
    "Enter your password",
    "Passphrase",
    "Enter your coldkey password",
    "Decrypting",
    "decrypt",
    "Enter the password",
    "coldkey password",
]
```

### Step 1.3: Fix EOF/TIMEOUT index calculation

**File:** `src/taox/commands/executor.py`
**Lines:** 297-320

**Current (may have off-by-one):**
```python
patterns = PASSWORD_PROMPTS + [pexpect.EOF, pexpect.TIMEOUT]
index = child.expect(patterns, timeout=self.timeout)

if index < len(PASSWORD_PROMPTS):
    # Password prompt
elif index == len(PASSWORD_PROMPTS):  # EOF
    break
else:  # TIMEOUT
```

**Fixed (clearer logic):**
```python
patterns = PASSWORD_PROMPTS + [pexpect.EOF, pexpect.TIMEOUT]
eof_index = len(PASSWORD_PROMPTS)
timeout_index = len(PASSWORD_PROMPTS) + 1

index = child.expect(patterns, timeout=self.timeout)

if index < eof_index:
    # Password prompt detected
elif index == eof_index:
    # EOF - process completed
    break
elif index == timeout_index:
    # Timeout
    output_lines.append(f"Command timed out after {self.timeout}s")
    break
```

### Step 1.4: Improve output capture

**File:** `src/taox/commands/executor.py`
**Inside `run_interactive()` method**

Add better output capture:
```python
# After spawning
child.logfile_read = sys.stdout  # Optional: show btcli output in real-time

# Better output handling
if child.before:
    output_lines.append(child.before)
if child.after and isinstance(child.after, str):
    output_lines.append(child.after)
```

### Test Milestone 1

```bash
# Test in demo mode first
taox --demo chat
> send 0.01 tao to 5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v

# Test with real wallet (small amount!)
taox chat
> send 0.001 tao to 5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v
```

**Success Criteria:**
- [ ] Password prompt appears and is hidden
- [ ] Transaction completes (or fails with btcli error, not pexpect error)
- [ ] Output shows success/failure message

---

## Milestone 2: Consistent Command Execution (P1)

**Goal:** All btcli operations use interactive password handling
**Estimated Effort:** 45 minutes
**Dependencies:** Milestone 1

### Step 2.1: Update child.py

**File:** `src/taox/commands/child.py`

**Changes needed in these functions:**

1. `get_child_hotkeys()` - line 183: Change `executor.run(**cmd_info)` to `executor.run_interactive(**cmd_info)`
2. `set_child_hotkey()` - line 273: Change `executor.run(**cmd_info)` to `executor.run_interactive(**cmd_info)`
3. `revoke_child_hotkey()` - line 351: Change `executor.run(**cmd_info)` to `executor.run_interactive(**cmd_info)`
4. `set_child_take()` - line 435: Change `executor.run(**cmd_info)` to `executor.run_interactive(**cmd_info)`

Also remove `show_transaction_preview` calls and import.

### Step 2.2: Update register.py

**File:** `src/taox/commands/register.py`

**Changes needed:**

1. `register_burned()` - line 254: Change `executor.run(**cmd_info)` to `executor.run_interactive(**cmd_info)`
2. `register_pow()` - line 332: Change `executor.run(**cmd_info, timeout=3600)` to `executor.run_interactive(**cmd_info)` (handle long timeout separately)

Also remove `show_transaction_preview` calls and import.

### Step 2.3: Clean up show_transaction_preview

Remove the verbose command preview (per user request "no need to show the btcli command"):

**Files to update:**
- `child.py`: Remove import and all `show_transaction_preview()` calls
- `register.py`: Remove import and all `show_transaction_preview()` calls

The function can remain in `confirm.py` for future use but should not be called.

### Test Milestone 2

```bash
# Test child hotkey operations
taox child --wizard

# Test registration
taox register --wizard
```

**Success Criteria:**
- [ ] Child hotkey operations prompt for password
- [ ] Registration operations prompt for password
- [ ] No verbose btcli command preview shown

---

## Milestone 3: Transaction History Integration (P1)

**Goal:** Record all transactions for audit trail
**Estimated Effort:** 1 hour
**Dependencies:** Milestones 1 & 2

### Step 3.1: Add history recording to wallet.py

**File:** `src/taox/commands/wallet.py`

Add import at top:
```python
from taox.data.history import transaction_history, TransactionType, TransactionStatus
```

In `transfer_tao()`, after execution:
```python
# Record the transaction
tx = transaction_history.record(
    tx_type=TransactionType.TRANSFER,
    status=TransactionStatus.SUCCESS if result.success else TransactionStatus.FAILED,
    amount=amount,
    from_address=from_address,
    to_address=destination,
    wallet_name=wallet_name,
    command=executor.get_command_string(**cmd_info),
    error=result.stderr if not result.success else None,
)
```

### Step 3.2: Add history recording to stake.py

**File:** `src/taox/commands/stake.py`

Add import at top:
```python
from taox.data.history import transaction_history, TransactionType, TransactionStatus
```

In `stake_tao()`:
```python
transaction_history.record(
    tx_type=TransactionType.STAKE,
    status=TransactionStatus.SUCCESS if result.success else TransactionStatus.FAILED,
    amount=amount,
    to_address=hotkey,
    netuid=netuid,
    wallet_name=wallet_name,
    validator_name=resolved_name,
    command=executor.get_command_string(**cmd_info),
    error=result.stderr if not result.success else None,
)
```

In `unstake_tao()`:
```python
transaction_history.record(
    tx_type=TransactionType.UNSTAKE,
    status=TransactionStatus.SUCCESS if result.success else TransactionStatus.FAILED,
    amount=amount,
    from_address=hotkey,
    netuid=netuid,
    wallet_name=wallet_name,
    command=executor.get_command_string(**cmd_info),
    error=result.stderr if not result.success else None,
)
```

### Step 3.3: Add history recording to child.py and register.py

Similar pattern for:
- `child.py`: `set_child_hotkey`, `revoke_child_hotkey`, `set_child_take`
- `register.py`: `register_burned`, `register_pow`

### Test Milestone 3

```bash
# Make some transactions
taox chat
> send 0.001 tao to 5xxx...

# View history
taox history
taox history --type transfer
taox history --export transactions.csv
```

**Success Criteria:**
- [ ] Transactions appear in `taox history`
- [ ] Export to CSV/JSON works
- [ ] History persists across sessions (~/.taox/history/transactions.json)

---

## Milestone 4: Cache Integration (P2)

**Goal:** Reduce API calls and enable offline fallback
**Estimated Effort:** 1 hour
**Dependencies:** None

### Step 4.1: Integrate caching into taostats.py

**File:** `src/taox/data/taostats.py`

Update `get_validators()`:
```python
async def get_validators(
    self, netuid: Optional[int] = None, limit: int = 10
) -> list[Validator]:
    cache_key = f"validators:{netuid}:{limit}"

    # Check memory cache first
    cached = validator_cache.get(cache_key)
    if cached is not None:
        return cached

    # Check persistent cache for offline mode
    if offline_manager.is_offline:
        stale = persistent_validator_cache.get_stale(cache_key)
        if stale:
            return stale

    # ... existing API fetch code ...

    # Cache the result
    validator_cache.set(cache_key, validators)
    persistent_validator_cache.set(cache_key, [asdict(v) for v in validators])

    return validators
```

Apply similar pattern to:
- `get_subnets()`
- `get_price()`
- `get_stake_balance()`

### Step 4.2: Implement offline detection

**File:** `src/taox/data/taostats.py`

In `_get_client()`:
```python
async def _get_client(self) -> httpx.AsyncClient:
    # Check connectivity periodically
    if offline_manager.should_check_network():
        await offline_manager.check_connectivity()

    # ... rest of existing code ...
```

### Test Milestone 4

```bash
# Make requests to warm cache
taox validators
taox subnets
taox price

# Check cache files exist
ls ~/.taox/cache/

# Simulate offline (disconnect network)
# Should still work with cached data
taox validators
```

**Success Criteria:**
- [ ] Repeated API calls use cache
- [ ] Cache files persist in ~/.taox/cache/
- [ ] Offline mode shows stale data with warning

---

## Milestone 5: Polish & Testing (P3)

**Goal:** Improve reliability and user experience
**Estimated Effort:** 2 hours
**Dependencies:** Milestones 1-4

### Step 5.1: Add SS58 address validation

**File:** `src/taox/chat/intents.py`

Add validation function:
```python
def is_valid_ss58(address: str) -> bool:
    """Validate SS58 address format."""
    if not address or len(address) != 48:
        return False
    if not address.startswith('5'):
        return False
    # Check for valid base58 characters
    valid_chars = set('123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz')
    return all(c in valid_chars for c in address)
```

### Step 5.2: Improve error messages

**File:** `src/taox/commands/executor.py`

Add error parsing in `run_interactive()`:
```python
# Parse common btcli errors
def _parse_btcli_error(output: str) -> str:
    if "insufficient" in output.lower():
        return "Insufficient balance for this transaction"
    if "invalid" in output.lower() and "address" in output.lower():
        return "Invalid destination address"
    if "not registered" in output.lower():
        return "Hotkey not registered on this subnet"
    if "password" in output.lower() and "incorrect" in output.lower():
        return "Incorrect wallet password"
    return output
```

### Step 5.3: Add integration tests

**File:** `tests/test_executor.py`

```python
import pytest
from taox.commands.executor import BtcliExecutor

def test_command_validation():
    executor = BtcliExecutor()
    assert executor._validate_command("wallet", "balance") == True
    assert executor._validate_command("wallet", "malicious") == False

def test_command_building():
    executor = BtcliExecutor()
    cmd = executor._build_command("wallet", "balance", args={"wallet-name": "test"})
    assert "btcli" in cmd
    assert "wallet" in cmd
    assert "balance" in cmd
```

### Test Milestone 5

```bash
# Run tests
pytest tests/ -v

# Test invalid inputs
taox chat
> send 10 tao to invalid_address
# Should show validation error

> send 10000 tao to 5xxx...
# Should warn about large amount
```

**Success Criteria:**
- [ ] All tests pass
- [ ] Invalid addresses rejected with helpful message
- [ ] Error messages are user-friendly

---

## Implementation Order Summary

| Order | Milestone | Effort | Impact | Risk |
|-------|-----------|--------|--------|------|
| 1 | Fix Transaction Execution | 30 min | **Critical** | Low |
| 2 | Consistent Command Execution | 45 min | High | Low |
| 3 | Transaction History | 1 hr | Medium | Low |
| 4 | Cache Integration | 1 hr | Medium | Low |
| 5 | Polish & Testing | 2 hr | Low | Low |

**Total Estimated Effort:** ~5 hours

---

## Verification Checklist

After completing all milestones:

- [ ] `taox chat` - Can send TAO to address
- [ ] `taox chat` - Can stake TAO to validator
- [ ] `taox chat` - Can unstake TAO
- [ ] `taox stake --wizard` - Interactive staking works
- [ ] `taox child --wizard` - Child hotkey management works
- [ ] `taox register --wizard` - Registration works
- [ ] `taox history` - Shows all past transactions
- [ ] `taox history --export tx.csv` - Export works
- [ ] App works in offline mode with cached data
- [ ] All tests pass

---

## Rollback Plan

If issues arise after deployment:

1. **Immediate rollback:** Revert `run_interactive()` to use `run()` as fallback
2. **Keep transaction history:** History feature can be disabled by not importing
3. **Cache issues:** Delete `~/.taox/cache/` to clear

Each milestone is independent and can be reverted individually without affecting others.
