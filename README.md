# taox

AI-powered conversational CLI for Bittensor. Talk to your wallet in plain English instead of memorizing `btcli` commands.

```
You: stake 10 TAO to taostats on subnet 1
taox: Stake 10 τ to taostats on SN1? (yes/no)
You: yes
[executes btcli stake add...]
```

## Quick Start

```bash
pip install taox
taox doctor        # Check your setup
taox chat          # Start chatting
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

**Supported operations:**
- Check balance, portfolio, TAO price
- Stake/unstake to validators
- Transfer TAO
- View validators, subnets, metagraph
- Register on subnets

## Security

**taox is non-custodial.** It never has access to your private keys or seed phrases.

| What | How it's handled |
|------|------------------|
| Passwords | Hidden input via `getpass`, passed to `btcli` via `pexpect`, never logged |
| API keys | Stored in system keyring (macOS Keychain, Linux Secret Service, Windows Credential Manager) |
| Commands | Subprocess with `shell=False`, no shell injection possible |
| Transactions | Always require explicit confirmation |
| High-value | Extra confirmation for amounts ≥10 TAO |

**Before using with real funds:**
1. Review the source code
2. Try demo mode first: `taox --demo chat`
3. Start with small amounts

## Requirements

- Python 3.9+
- btcli (`pip install bittensor-cli`)
- A Bittensor wallet

## Configuration

API keys are optional but improve the experience:

```bash
taox setup
```

| Service | What it does | Get a key |
|---------|--------------|-----------|
| Chutes AI | Natural language understanding | [chutes.ai](https://chutes.ai) |
| Taostats | Real-time network data | [dash.taostats.io](https://dash.taostats.io) |

Without API keys, taox uses pattern matching and cached/demo data.

## Demo Mode

Safe mode for testing without real transactions:

```bash
taox --demo chat
```

Commands are previewed but not executed.

## Usage

**Chat mode:**
```bash
taox chat
> what's my balance?
> show validators on subnet 1
> stake 5 TAO to the top validator
```

**Direct commands:**
```bash
taox balance
taox portfolio
taox validators --netuid 1
taox stake --wizard
```

**Pass-through to btcli:**
```bash
taox -- wallet list
taox -- stake show
```

## Natural Language Examples

| You say | taox understands |
|---------|------------------|
| "what's my balance?" | Check wallet balance |
| "show my portfolio" | List all stake positions |
| "stake 10 TAO to taostats on subnet 1" | Stake operation |
| "send 5 TAO to 5xxx..." | Transfer TAO |
| "show validators on subnet 1" | List validators |
| "help" | Show available commands |

## Development

```bash
git clone https://github.com/taox-project/taox
cd taox
pip install -e ".[dev]"
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## Status

taox is alpha software. It works, but expect rough edges.

**What's working:**
- Balance/portfolio queries
- Staking to validators
- Transfers
- Subnet info

**Roadmap:**
- Improved error messages
- Transaction history
- Multi-wallet support
- Better natural language patterns

## License

MIT
