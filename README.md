# taox

AI-powered conversational CLI for Bittensor. Talk to your wallet in plain English instead of memorizing `btcli` commands.

```
You: stake 10 TAO to taostats on subnet 1
taox: Stake 10 τ to taostats on SN1? (yes/no)
You: yes
✓ Staked 10 τ → taostats (SN1) | tx: 0x3f...a2
```

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/DanielDerefaka/tao-cli/main/install.sh | bash
```

The installer checks your environment, installs taox, and walks you through API key setup.

Or install manually:

```bash
pip install git+https://github.com/DanielDerefaka/tao-cli.git
taox          # guided setup starts automatically
```

## What It Does

Instead of:
```bash
btcli stake add --amount 10 --include-hotkeys 5xxx... --netuid 1 --wallet-name default
```

Just say:
```
stake 10 TAO to taostats on subnet 1
```

## Commands

### Chat Mode

```bash
taox chat                        # Interactive conversation
taox chat "what's my balance?"   # Single message
```

### Portfolio & Balance

```bash
taox balance                     # Check TAO balance
taox balance --wallet mywallet   # Specific wallet
taox portfolio                   # All stake positions
taox portfolio --delta 7d        # 7-day change view
taox portfolio --history 30d     # 30-day history table
taox price                       # Current TAO price
```

### Staking

```bash
taox stake --wizard              # Guided staking flow
taox stake --amount 10 --validator taostats --netuid 1
taox recommend 100               # Smart validator recommendations
taox recommend 500 --diversify   # Auto-split across validators
taox recommend 100 --risk high   # Risk-adjusted scoring
taox rebalance 100 --netuid 1    # Batch stake to top validators
taox rebalance 100 --dry-run     # Preview without executing
```

### Network Info

```bash
taox validators --netuid 1       # Top validators on a subnet
taox subnets                     # List all subnets
taox metagraph 1                 # Subnet metagraph
```

### Monitoring

```bash
taox watch --price ">500"                    # Alert when TAO crosses $500
taox watch --validator taostats              # Watch a validator for rank changes
taox watch --registration 0.5 --netuid 1     # Alert on cheap registration
taox watch --list                            # Show active alerts
taox watch --clear                           # Remove all alerts
```

### Wallet Management

```bash
taox wallets                     # List all wallets
taox register --wizard           # Register on a subnet
taox child --wizard              # Manage child hotkeys
taox history                     # Transaction history
```

### Utilities

```bash
taox doctor                      # Diagnose environment issues
taox doctor --json               # Machine-readable health check
taox setup                       # Configure API keys
taox welcome                     # Re-run wallet onboarding
taox --demo chat                 # Safe demo mode (no real tx)
taox -- wallet list              # Pass-through to btcli
```

## Natural Language Examples

| You say | taox understands |
|---------|------------------|
| "what's my balance?" | Check wallet balance |
| "show my portfolio" | List all stake positions |
| "stake 10 TAO to taostats on subnet 1" | Stake operation |
| "send 5 TAO to 5xxx..." | Transfer TAO |
| "show validators on subnet 1" | List validators |
| "who are the top validators?" | Validator ranking |
| "register on subnet 1" | Subnet registration |
| "help" | Show available commands |

## Security

**taox is non-custodial.** It never has access to your private keys or seed phrases.

| What | How |
|------|-----|
| Passwords | Hidden input via `getpass`, passed to `btcli` via `pexpect`, never logged |
| API keys | Stored in system keyring (macOS Keychain / Linux Secret Service / Windows Credential Manager) |
| Commands | Subprocess with `shell=False` — no shell injection possible |
| Transactions | Always require explicit confirmation before signing |
| High-value | Extra confirmation for amounts ≥ 10 TAO |
| Tx pipeline | Plan → Confirm → Execute → Verify (no shortcuts) |

**Before using with real funds:**
1. Review the source code
2. Try demo mode first: `taox --demo chat`
3. Start with small amounts

## Requirements

- Python 3.9+
- btcli (`pip install bittensor-cli`)
- A Bittensor wallet

## Configuration

On first run taox detects your wallets and guides you through setup. Reconfigure anytime:

```bash
taox setup      # API keys
taox welcome    # Wallet selection
```

| Service | What it does | Required? | Get a key |
|---------|-------------|-----------|-----------|
| Chutes AI | Natural language understanding | Optional — pattern matching fallback | [chutes.ai](https://chutes.ai) |
| Taostats | Real-time network data | Optional — limited data without | [dash.taostats.io](https://dash.taostats.io) |

Config: `~/.taox/config.yml`. API keys are stored in your system keyring, never in plain text.

## Development

```bash
git clone https://github.com/DanielDerefaka/tao-cli
cd tao-cli
pip install -e ".[dev]"
pytest
```

## License

MIT
