# Execution Debugging Guide

This guide explains how to troubleshoot transaction execution issues in taox.

## Overview

taox wraps btcli commands with a hardened execution layer that provides:
- Debug logging with password redaction
- Dry-run mode for all commands
- Robust status parsing
- Transaction hash extraction
- Human-friendly error messages

## Quick Troubleshooting

### Transaction Not Going Through

1. **Enable debug mode** to see exactly what's happening:
   ```bash
   taox --debug chat
   # or
   export TAOX_DEBUG=true
   taox chat
   ```

2. **Use dry-run mode** to verify the command without executing:
   ```bash
   taox --dry-run chat
   # Then type your command, e.g., "stake 10 TAO to Taostats"
   ```

3. **Check the debug logs** at `~/.taox/logs/`:
   ```bash
   ls -la ~/.taox/logs/
   cat ~/.taox/logs/20260204_143022_stake_add.log
   ```

### Common Issues and Solutions

| Symptom | Likely Cause | Solution |
|---------|--------------|----------|
| "Too many password attempts" | Wrong password | Verify your coldkey password |
| "Command timed out" | Network issues or slow node | Increase timeout or check network |
| "btcli not found" | btcli not installed | Run `pip install bittensor-cli` |
| "Insufficient balance" | Not enough TAO | Check balance with `taox wallet balance` |
| "Invalid address" | Wrong SS58 format | Verify destination address |
| "Command not allowed" | Command not in whitelist | Check supported commands |

---

## Debug Logging System

### Enabling Debug Mode

```bash
# Via command line flag
taox --debug chat

# Via environment variable
export TAOX_DEBUG=true
taox chat

# Via config file (~/.taox/config.yml)
debug: true
```

### Log File Location

Debug logs are stored at `~/.taox/logs/` with secure permissions (owner-only access).

Log file naming: `YYYYMMDD_HHMMSS_<group>_<subcommand>.log`

Example: `20260204_143022_stake_add.log`

### Log File Contents

Each log file contains:
```
=== TAOX Debug Log ===
Timestamp: 2026-02-04T14:30:22.123456
Command: btcli stake add --network [VALUE] --amount [VALUE] --include-hotkeys [VALUE]
==================================================

--- EXECUTING (INTERACTIVE) ---
btcli stake add --network [VALUE] --amount [VALUE] --include-hotkeys [VALUE]

--- OUTPUT ---
Connecting to finney network...
Fetching stake information...

--- ACTION ---
[PASSWORD ENTERED]

--- OUTPUT ---
Staking 10.0 TAO to hotkey 5Abc...
Transaction submitted...
Block hash: 0xdef456...
Success! ✅

==================================================
=== RESULT ===
Status: success
Return Code: 0
Execution Time: 12.34s
TX Hash: 0xdef456789...
==================================================
```

### Security: Password Redaction

The debug logger **never logs passwords**. All sensitive data is automatically redacted:

| Pattern | Replacement |
|---------|-------------|
| `password=xxx` | `password=[REDACTED]` |
| `mnemonic: xxx` | `mnemonic: [REDACTED]` |
| `seed=xxx` | `seed=[REDACTED]` |
| `api_key=xxx` | `api_key=[REDACTED]` |
| `token=xxx` | `token=[REDACTED]` |
| 64-char hex strings | `[REDACTED_KEY]` |

The actual password entry is logged as `[PASSWORD ENTERED]` without the password value.

---

## Dry-Run Mode

Dry-run mode shows exactly what command would be executed without actually running it.

### Enabling Dry-Run

```bash
# Via command line flag
taox --dry-run chat

# In chat, just type your request:
> stake 10 TAO to Taostats on subnet 1
[DRY RUN] Would execute:
btcli stake add --network finney --amount 10.0 --include-hotkeys 5FFApa... --netuid 1 --safe
```

### Use Cases

1. **Verify command structure** before executing real transactions
2. **Test intent parsing** to ensure taox understands your request
3. **Demo/training** to show what taox does without real effects
4. **CI/CD testing** to validate command building logic

---

## Status Parsing

The executor determines transaction status from btcli output using pattern matching.

### Success Indicators

| Pattern | Example |
|---------|---------|
| ✅ | `Transfer complete ✅` |
| Success/success | `Operation successful` |
| Finalized | `Transaction Finalized` |
| Extrinsic submitted | `Extrinsic submitted` |
| Block hash | `Block hash: 0xabc123` |

### Failure Indicators

| Pattern | Example |
|---------|---------|
| ❌ | `Transaction failed ❌` |
| Error/error | `Error: Something went wrong` |
| Failed/failed | `Failed to submit` |
| Insufficient | `Insufficient balance` |
| Invalid | `Invalid address` |
| Denied/rejected | `Permission denied` |

### Status Values

| Status | Meaning |
|--------|---------|
| `success` | Command completed successfully |
| `failed` | Command failed with error |
| `timeout` | Command timed out |
| `cancelled` | User cancelled operation |
| `unknown` | Could not determine status |
| `dry_run` | Dry-run mode (no execution) |
| `demo_mode` | Demo mode (simulated) |

---

## Transaction Hash Extraction

The executor automatically extracts transaction hashes from output.

### Recognized Formats

- `0x` + 64 hex characters: `0xabcdef1234...`
- Plain 64 hex characters: `abcdef1234...`

### Accessing the Hash

```python
from taox.commands.executor import BtcliExecutor

executor = BtcliExecutor()
result = executor.execute("wallet", "transfer", args={"amount": 10, "dest": "5Abc"})

if result.success:
    print(f"Transaction hash: {result.tx_hash}")
```

---

## Password Handling

The executor uses `pexpect` for interactive password handling.

### Password Prompt Patterns

The following prompts trigger password entry:

- `Enter your coldkey password`
- `Enter the password to unlock your coldkey`
- `Unlock your coldkey`
- `Decrypting coldkey`
- `Enter your hotkey password`
- `Unlock your hotkey`
- `Enter password`
- `Password:`
- `Passphrase:`

### Password Entry Flow

1. User initiates transaction (e.g., "stake 10 TAO")
2. taox shows confirmation prompt
3. User confirms
4. btcli is spawned via pexpect
5. When password prompt detected, taox uses `getpass.getpass()` to securely collect password
6. Password is sent to btcli (never logged)
7. Output is captured and parsed

### Multiple Password Attempts

If the password is incorrect, taox allows up to 2 retry attempts before aborting with "Too many password attempts" error.

---

## Command Whitelist

For security, only whitelisted commands are allowed:

| Group | Subcommands |
|-------|-------------|
| `wallet` | list, balance, create, transfer, new-coldkey, new-hotkey |
| `stake` | add, remove, list, move, wizard, child |
| `subnets` | list, metagraph, hyperparameters, register, pow-register, burn-cost |
| `config` | set, get, clear |
| `sudo` | get-take, set-take |
| `root` | list, weights |

Attempting to execute non-whitelisted commands returns an error.

---

## Programmatic Usage

### Basic Execution

```python
from taox.commands.executor import BtcliExecutor, ExecutionMode

executor = BtcliExecutor(network="finney", timeout=120, debug=True)

# Dry-run
result = executor.execute("stake", "add",
    args={"amount": 10, "netuid": 1, "include-hotkeys": "5Abc"},
    dry_run=True
)
print(result.stdout)

# Real execution
result = executor.execute("stake", "add",
    args={"amount": 10, "netuid": 1, "include-hotkeys": "5Abc"},
    mode=ExecutionMode.INTERACTIVE
)

if result.success:
    print(f"Staked! TX: {result.tx_hash}")
else:
    print(f"Failed: {result.error_message}")
```

### Using Command Builders

```python
from taox.commands.executor import BtcliExecutor, build_stake_add_command

executor = BtcliExecutor()

cmd = build_stake_add_command(
    amount=10.0,
    hotkey="5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v",
    netuid=1,
    wallet_name="default",
    safe_staking=True
)

result = executor.execute(**cmd)
```

### Custom Password Callback

```python
def get_password_from_vault():
    # Your secure password retrieval logic
    return "password"

result = executor.execute("wallet", "transfer",
    args={"amount": 10, "dest": "5Abc"},
    password_callback=get_password_from_vault
)
```

---

## Troubleshooting Checklist

### Before Transactions

- [ ] Check balance: `taox wallet balance`
- [ ] Verify destination address format (SS58)
- [ ] Test with dry-run first: `taox --dry-run chat`
- [ ] Ensure btcli is installed: `btcli --version`

### During Issues

- [ ] Enable debug mode: `taox --debug chat`
- [ ] Check debug logs: `ls ~/.taox/logs/`
- [ ] Verify network connectivity
- [ ] Confirm wallet password is correct

### After Failures

- [ ] Read the error message carefully
- [ ] Check the debug log for full output
- [ ] Look for transaction hash (may have succeeded)
- [ ] Check on-chain state via explorer

---

## Debug Log Examples

### Successful Transfer

```
=== TAOX Debug Log ===
Timestamp: 2026-02-04T14:30:22.123456
Command: btcli wallet transfer --network [VALUE] --amount [VALUE] --dest [VALUE]
==================================================

--- EXECUTING (INTERACTIVE) ---
btcli wallet transfer --network finney --amount 10.0 --dest 5Xyz...

--- OUTPUT ---
Transferring 10.0 TAO to 5Xyz...
Enter your coldkey password:

--- ACTION ---
[PASSWORD ENTERED]

--- OUTPUT ---
Transaction submitted
Waiting for finalization...
Block hash: 0x1234abcd...
Transfer complete ✅

==================================================
=== RESULT ===
Status: success
Return Code: 0
Execution Time: 8.23s
TX Hash: 0x1234abcd...
==================================================
```

### Failed Transfer (Wrong Password)

```
=== TAOX Debug Log ===
Timestamp: 2026-02-04T14:35:10.789012
Command: btcli wallet transfer --network [VALUE] --amount [VALUE] --dest [VALUE]
==================================================

--- EXECUTING (INTERACTIVE) ---
btcli wallet transfer --network finney --amount 10.0 --dest 5Xyz...

--- OUTPUT ---
Transferring 10.0 TAO to 5Xyz...
Enter your coldkey password:

--- ACTION ---
[PASSWORD ENTERED]

--- OUTPUT ---
Decryption failed: incorrect password
Enter your coldkey password:

--- ACTION ---
[PASSWORD ENTERED]

--- OUTPUT ---
Decryption failed: incorrect password
Enter your coldkey password:

--- ERROR ---
Too many password attempts - aborting

==================================================
=== RESULT ===
Status: failed
Return Code: -1
Execution Time: 25.67s
Error: Incorrect password (too many attempts)
==================================================
```

### Timeout

```
=== TAOX Debug Log ===
Timestamp: 2026-02-04T14:40:00.000000
Command: btcli stake add --network [VALUE] --amount [VALUE] --netuid [VALUE]
==================================================

--- EXECUTING (INTERACTIVE) ---
btcli stake add --network finney --amount 10.0 --netuid 1

--- OUTPUT ---
Connecting to finney network...
Fetching stake information...

--- TIMEOUT ---
Timed out after 120s

==================================================
=== RESULT ===
Status: timeout
Return Code: -1
Execution Time: 120.05s
Error: Command timed out after 120 seconds
==================================================
```

---

## Support

If you continue to experience issues:

1. Check the [GitHub Issues](https://github.com/anthropics/claude-code/issues)
2. Include your debug log (redacted) when reporting
3. Note your btcli version (`btcli --version`)
4. Note your taox version (`taox --version`)
