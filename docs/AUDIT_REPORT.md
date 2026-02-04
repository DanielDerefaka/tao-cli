# taox Audit Report

**Date:** 2026-02-04
**Auditor:** Claude
**Scope:** Full codebase review comparing implementation to README promises

---

## Executive Summary

taox is a well-structured CLI application with solid foundations. However, there are **critical bugs** in the transaction execution layer that prevent real transactions from completing successfully. The primary issue is in the pexpect implementation for password handling.

**Critical Finding:** Transactions are not going through because of a bug in `executor.py:run_interactive()`.

---

## Feature Audit

### Working Features (✅)

| Feature | File(s) | Status | Notes |
|---------|---------|--------|-------|
| CLI Structure | `cli.py` | ✅ Working | Typer-based, well organized |
| Wallet Detection | `onboarding.py` | ✅ Working | Detects ~/.bittensor/wallets |
| Wallet Listing | `wallet.py:list_wallets()` | ✅ Working | Lists wallets with hotkeys |
| Balance Display | `wallet.py:show_balance()` | ✅ Working | SDK-based balance fetch |
| Portfolio View | `stake.py:show_portfolio()` | ✅ Working | Shows positions with USD values |
| Validators List | `stake.py:show_validators()` | ✅ Working | Taostats API integration |
| Subnets List | `subnet.py:list_subnets()` | ✅ Working | Taostats API integration |
| Metagraph Display | `subnet.py:show_metagraph()` | ✅ Working | SDK or btcli fallback |
| Price Fetching | `taostats.py:get_price()` | ✅ Working | Live TAO price |
| Intent Parsing (Mock) | `intents.py:MockIntentParser` | ✅ Working | Regex patterns work |
| Chat Context | `context.py` | ✅ Working | Message history maintained |
| Configuration | `settings.py` | ✅ Working | YAML + env vars |
| Secure Credentials | `credentials.py` | ✅ Working | Keyring integration |
| Demo Mode | Throughout | ✅ Working | Mock data when no keys |
| Onboarding Flow | `onboarding.py` | ✅ Working | Wallet selection wizard |
| TUI Dashboard | `dashboard.py` | ✅ Working | Textual-based real-time |
| Data Caching | `cache.py` | ✅ Working | TTL + persistent caches |

### Partially Working Features (⚠️)

| Feature | File(s) | Status | Issue |
|---------|---------|--------|-------|
| Transfer TAO | `wallet.py:transfer_tao()` | ⚠️ Partial | pexpect bug blocks execution |
| Stake TAO | `stake.py:stake_tao()` | ⚠️ Partial | pexpect bug blocks execution |
| Unstake TAO | `stake.py:unstake_tao()` | ⚠️ Partial | pexpect bug blocks execution |
| Chat LLM | `llm.py` | ⚠️ Partial | Works but falls back to mock often |
| Password Handling | `executor.py:run_interactive()` | ⚠️ **CRITICAL** | See detailed analysis below |
| Confirmation Flow | `confirm.py` | ⚠️ Partial | Works but inconsistent UX |

### Missing/Broken Features (❌)

| Feature | File(s) | Status | Issue |
|---------|---------|--------|-------|
| Transaction History Recording | `history.py` | ❌ Not Integrated | Class exists but never called |
| Child Hotkey Operations | `child.py` | ❌ Broken | Uses `run()` not `run_interactive()` |
| Registration Operations | `register.py` | ❌ Broken | Uses `run()` not `run_interactive()` |
| Offline Mode | `cache.py` | ❌ Not Integrated | `OfflineManager` never used |
| Cache Integration | `taostats.py` | ❌ Not Integrated | Caches imported but unused |

---

## Critical Bug Analysis: "Transactions Not Going Through"

### Root Cause

**File:** `src/taox/commands/executor.py` **Lines:** 288-289

```python
# BUG: This is wrong!
child = pexpect.spawn(" ".join(cmd), timeout=self.timeout, encoding="utf-8")
```

### Problem

The `pexpect.spawn()` function receives a shell-escaped string via `" ".join(cmd)`. This can cause issues with:

1. **Argument parsing** - Arguments with spaces or special characters get mangled
2. **Shell interpretation** - String is parsed by shell, not passed directly
3. **Timeout handling** - The patterns list includes `pexpect.TIMEOUT` twice

### Correct Implementation

```python
# Option 1: Use command list properly
child = pexpect.spawn(cmd[0], cmd[1:], timeout=self.timeout, encoding="utf-8")

# Option 2: Use pexpect.spawnu for unicode
child = pexpect.spawnu(cmd[0], cmd[1:], timeout=self.timeout)
```

### Secondary Issues

1. **Password prompt patterns may not match** (line 17-24):
   ```python
   PASSWORD_PROMPTS = [
       "Enter password",
       "Password:",
       # Missing: "Enter your coldkey password:", "Decrypting", etc.
   ]
   ```

2. **Index calculation error** (line 316):
   ```python
   elif index == len(PASSWORD_PROMPTS):  # EOF
   ```
   The patterns list has `PASSWORD_PROMPTS + [pexpect.EOF, pexpect.TIMEOUT]`, so EOF is at `len(PASSWORD_PROMPTS)` and TIMEOUT at `len(PASSWORD_PROMPTS) + 1`.

3. **Output not captured properly** - `child.before` may be None or incomplete.

---

## Security Analysis

### Secure (✅)

| Item | Implementation | Notes |
|------|----------------|-------|
| Shell injection prevention | `shell=False` in subprocess | Proper |
| Command whitelist | `ALLOWED_COMMANDS` dict | Good, but incomplete |
| Password redaction | `getpass.getpass()` | Password never logged |
| Credential storage | System keyring | Secure |
| Sensitive data filter | `SensitiveDataFilter` | Logs filtered |

### Risky Areas (⚠️)

| Item | Location | Risk | Recommendation |
|------|----------|------|----------------|
| pexpect shell string | `executor.py:289` | Medium | Command could be manipulated |
| btcli passthrough | `cli.py:795-818` | Low | Direct shell access |
| Config file perms | `settings.py` | Low | No chmod after write |
| Wallet path expansion | `sdk.py:129` | Low | Path traversal possible |

### Not Yet Implemented (❌)

| Item | Expected | Actual |
|------|----------|--------|
| Transaction signing verification | Should verify | Not implemented |
| Address validation | Should validate SS58 | Only regex in intents.py |
| Amount bounds checking | Should limit | Only UI limits |

---

## Architecture Issues

### 1. Inconsistent Command Execution

Some commands use `run_interactive()`, others use `run()`:

| Command | Uses | Should Use |
|---------|------|------------|
| `wallet.py:transfer_tao` | `run_interactive` | ✅ Correct |
| `stake.py:stake_tao` | `run_interactive` | ✅ Correct |
| `stake.py:unstake_tao` | `run_interactive` | ✅ Correct |
| `child.py:set_child_hotkey` | `run` | ❌ Should be `run_interactive` |
| `child.py:revoke_child_hotkey` | `run` | ❌ Should be `run_interactive` |
| `child.py:set_child_take` | `run` | ❌ Should be `run_interactive` |
| `register.py:register_burned` | `run` | ❌ Should be `run_interactive` |
| `register.py:register_pow` | `run` | ❌ Should be `run_interactive` |

### 2. Transaction History Not Integrated

`history.py` defines a complete `TransactionHistory` class but it's never called:

```python
# This exists but is never used:
transaction_history = TransactionHistory()

# Should be called in wallet.py, stake.py after transactions:
transaction_history.record(
    tx_type=TransactionType.TRANSFER,
    status=TransactionStatus.SUCCESS,
    amount=amount,
    ...
)
```

### 3. Cache Not Integrated

`cache.py` defines caches but they're not used in `taostats.py`:

```python
# Defined in cache.py:
validator_cache = Cache(maxsize=200, ttl=300)

# Not used in taostats.py - could wrap API calls
```

### 4. show_transaction_preview Still Used

`confirm.py:show_transaction_preview()` was supposed to be removed but is still imported/used in:
- `child.py` (lines 12, 176, 249, 329, 413)
- `register.py` (lines 12, 228, 310)

---

## README vs Implementation Gap

| README Promise | Implementation Status |
|----------------|----------------------|
| "Natural Language Interface" | ✅ Works (mock parser) |
| "Secure Password Handling" | ⚠️ Implementation buggy |
| "Context Awareness" | ✅ Works |
| "Real-time Data" | ✅ Works |
| "Portfolio Dashboard" | ✅ Works |
| "Interactive Wizards" | ✅ Works |
| "Transaction History" | ❌ Not integrated |
| "No Shell Injection" | ✅ Mostly (pexpect risk) |
| "Command Whitelist" | ✅ Works |
| "Secure Credential Storage" | ✅ Works |
| "Transaction Confirmations" | ✅ Works |

---

## Quick Wins (High Impact, Low Effort)

1. **Fix pexpect spawn** - 1 line change, fixes all transactions
2. **Add missing password prompts** - Add btcli-specific patterns
3. **Integrate transaction history** - 5-10 lines per command
4. **Update child.py/register.py to use run_interactive** - Simple find/replace

---

## Prioritized Fix List

### P0 - Critical (Blocking Core Functionality)

| # | Issue | File | Effort |
|---|-------|------|--------|
| 1 | Fix pexpect.spawn() argument passing | `executor.py:289` | 5 min |
| 2 | Add more PASSWORD_PROMPTS patterns | `executor.py:17-24` | 10 min |
| 3 | Fix index calculation for EOF/TIMEOUT | `executor.py:316` | 5 min |

### P1 - High (Important for UX)

| # | Issue | File | Effort |
|---|-------|------|--------|
| 4 | Update child.py to use run_interactive | `child.py` | 15 min |
| 5 | Update register.py to use run_interactive | `register.py` | 15 min |
| 6 | Integrate transaction history recording | Multiple | 30 min |
| 7 | Remove show_transaction_preview from child/register | Multiple | 10 min |

### P2 - Medium (Polish/Optimization)

| # | Issue | File | Effort |
|---|-------|------|--------|
| 8 | Integrate caching into taostats.py | `taostats.py` | 30 min |
| 9 | Implement offline mode fallback | `cache.py`, `taostats.py` | 1 hr |
| 10 | Add SS58 address validation | `intents.py` | 20 min |
| 11 | Improve error messages from btcli | `executor.py` | 30 min |

### P3 - Low (Nice to Have)

| # | Issue | File | Effort |
|---|-------|------|--------|
| 12 | Add LLM streaming responses | `llm.py`, `cli.py` | 1 hr |
| 13 | Add more intent patterns | `intents.py` | 30 min |
| 14 | Config file permission hardening | `settings.py` | 15 min |

---

## Appendix: Files Reviewed

```
src/taox/
├── __init__.py
├── cli.py ........................ Main entry point
├── chat/
│   ├── context.py ................ Conversation state
│   ├── intents.py ................ Intent classification
│   └── llm.py .................... LLM client
├── commands/
│   ├── executor.py ............... btcli wrapper (CRITICAL BUGS)
│   ├── wallet.py ................. Balance/transfer
│   ├── stake.py .................. Staking operations
│   ├── subnet.py ................. Subnet info
│   ├── child.py .................. Child hotkeys (needs update)
│   └── register.py ............... Registration (needs update)
├── data/
│   ├── sdk.py .................... Bittensor SDK wrapper
│   ├── taostats.py ............... Taostats API client
│   ├── cache.py .................. Caching utilities
│   └── history.py ................ Transaction history (not integrated)
├── security/
│   ├── confirm.py ................ Confirmations
│   └── credentials.py ............ Keyring storage
├── ui/
│   ├── console.py ................ Rich console
│   ├── theme.py .................. Colors/symbols
│   ├── prompts.py ................ User prompts
│   ├── dashboard.py .............. TUI dashboard
│   └── onboarding.py ............. Setup wizard
└── config/
    └── settings.py ............... Configuration
```

---

## Conclusion

taox has a solid architecture and most features work in demo mode. The **primary blocker** is the pexpect implementation bug in `executor.py` which prevents real transactions from completing. Fixing this one bug (P0 #1) will unblock the core value proposition of the application.

Secondary priorities should focus on consistency (making all commands use the same execution path) and integration (connecting the transaction history system).
