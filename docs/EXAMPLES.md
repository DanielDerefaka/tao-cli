# Safe Examples for taox

This guide shows how to use taox safely, including demo mode and dry-run examples.

## Demo Mode

Demo mode lets you explore taox without making real API calls or transactions. All data shown is sample data.

### Enabling Demo Mode

```bash
# Via command line flag
taox --demo chat

# Via environment variable
export TAOX_DEMO_MODE=true
taox chat

# Via config file (~/.taox/config.yml)
demo_mode: true
```

### Demo Mode Examples

```bash
# Check balance (shows sample balance)
taox --demo chat
> what is my balance?
Your balance is 100.0000 τ [DEMO DATA]

# View validators (shows sample validators)
> show validators on subnet 1
Top validators on subnet 1:
1. Taostats - 1,500,000 τ staked
2. OpenTensor Foundation - 1,200,000 τ
...
[DEMO DATA - Sample validators]

# Stake preview (no real transaction)
> stake 10 TAO to Taostats on subnet 1
[Preview Mode]
Command: btcli stake add --amount 10 --hotkey 5FFA... --netuid 1
This is a demo - no real transaction will be executed.
```

## Safe Staking Exploration

### View Before You Act

Always check validators before staking:

```bash
# View top validators
taox validators --netuid 1

# Search for a specific validator
taox validators --search "Taostats"

# Check validator details
> tell me about Taostats validator
```

### Transaction Confirmation

taox always asks for confirmation before executing transactions:

```bash
> stake 10 TAO to Taostats

I'll stake 10 τ to Taostats (5FFA...52v) on subnet 1.

⚠️  Transaction Preview:
   Amount: 10 τ
   Validator: Taostats
   Subnet: 1
   Fee: ~0.001 τ

Proceed with this stake? [y/N]:
```

### High-Value Warnings

Extra confirmation for amounts >= 10 TAO:

```bash
> stake 100 TAO to Taostats

⚠️  HIGH VALUE TRANSACTION
   Amount: 100 τ (approximately $45,000 USD)

This is a significant transaction. Please double-check:
- Validator: Taostats (5FFA...52v)
- Subnet: 1
- Your wallet: default

Type 'CONFIRM' to proceed:
```

## Dry-Run Mode

Preview commands without executing:

```bash
# Use btcli passthrough with --dry-run (when supported)
taox -- stake add --amount 10 --netuid 1 --dry-run

# Or use demo mode for full preview
taox --demo chat
> stake 10 TAO to Taostats
[Shows full command that would be executed]
```

## Balance and Portfolio Commands (Read-Only)

These commands are always safe - they only read data:

```bash
# Check balance
taox balance
taox balance --wallet myWallet

# View portfolio
taox portfolio

# List wallets
taox wallet list

# View subnets
taox subnets

# View validators
taox validators --netuid 1
```

## Environment Check

Before doing any real transactions, run the doctor command:

```bash
taox doctor
```

This will verify:
- Python version
- btcli installation
- Wallet configuration
- API keys

## Testing Workflow

### For New Users

1. **Start with demo mode**
   ```bash
   taox --demo chat
   ```

2. **Run environment check**
   ```bash
   taox doctor
   ```

3. **Configure API keys (optional)**
   ```bash
   taox setup
   ```

4. **Check real balance (read-only)**
   ```bash
   taox balance
   ```

5. **Start with small amounts**
   ```bash
   > stake 0.1 TAO to Taostats on subnet 1
   ```

### For Developers

1. **Run tests in demo mode**
   ```bash
   pytest  # Automatically uses demo mode
   ```

2. **Test with sample data**
   ```bash
   TAOX_DEMO_MODE=true python -c "
   from taox.data.taostats import TaostatsClient
   import asyncio

   async def test():
       client = TaostatsClient()
       validators = await client.get_validators(netuid=1)
       print(f'Found {len(validators)} validators')

   asyncio.run(test())
   "
   ```

## Configuration for Safety

### Recommended config (~/.taox/config.yml)

```yaml
# Require confirmation for all transactions
confirm_transactions: true

# Extra confirmation for high-value transactions (in TAO)
high_value_threshold: 10

# Default network (finney = mainnet)
default_network: finney

# Never auto-execute commands from chat
auto_execute: false
```

## Error Handling

taox provides clear error messages:

```bash
> stake 10 TAO
Missing required information:
- Validator: Which validator do you want to stake to?
- Subnet: Which subnet? (e.g., 1, 18, 64)

Tip: Try "stake 10 TAO to Taostats on subnet 1"

> stake 10000 TAO to Taostats
⚠️  Insufficient balance
   Available: 100 τ
   Requested: 10,000 τ
```

## Getting Help

```bash
# General help
taox --help

# Command-specific help
taox stake --help
taox validators --help

# Interactive help in chat
taox chat
> help
> how do I stake?
```
