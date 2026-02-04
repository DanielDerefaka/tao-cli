# Master prompt for building taox: An AI-powered Bittensor CLI

This comprehensive research document provides all technical details needed to build **taox** — a production-quality, open-source, AI-powered conversational CLI for Bittensor that wraps btcli with natural language understanding.

---

## Project overview and architecture

**Taox** transforms Bittensor network interaction from memorizing complex btcli commands into natural conversation. Users can say "stake 100 TAO to the top validator on subnet 18" and taox translates this into the appropriate btcli operations, confirms with the user, and executes securely.

The core architecture consists of five layers: a **TUI presentation layer** using Rich and InquirerPy for beautiful terminal output; a **natural language processing layer** powered by Chutes AI for intent recognition; a **command translation layer** that maps intents to btcli operations; a **Bittensor SDK integration layer** for direct Python operations; and a **data enrichment layer** using Taostats API for real-time network intelligence.

---

## btcli codebase architecture

The btcli repository at `github.com/opentensor/btcli` follows a modern Python structure using **Typer** as the CLI framework (built on Click). The source code lives in `src/btcli/` with commands organized into modules: `wallet.py`, `stake.py`, `subnet.py`, `root.py`, `sudo.py`, and `config.py`. Each command group supports aliases (e.g., `wallet`, `w`, `wallets` all work).

Wallets are stored at `~/.bittensor/wallets/` in this structure:
```
~/.bittensor/wallets/
└── <wallet_name>/
    ├── coldkey              # Encrypted JSON keyfile
    ├── coldkeypub.txt       # Public key (SS58 address)
    └── hotkeys/
        └── <hotkey_name>    # Hotkey file
```

The wallet functionality uses **bittensor-wallet**, a separate Rust-based package with Python bindings via Maturin. Keys use EdDSA cryptography with SS58 address encoding.

Network connection happens via WebSocket using `async-substrate-interface`. The default endpoints are:
- **finney (mainnet)**: `wss://finney.opentensor.ai`
- **test**: `wss://test.finney.opentensor.ai`  
- **local**: `ws://127.0.0.1:9944`

Configuration at `~/.bittensor/config.yml` supports:
```yaml
chain: ws://127.0.0.1:9945      # Direct endpoint (highest priority)
network: finney                  # Network name
wallet_name: default             # Default coldkey
wallet_hotkey: default           # Default hotkey
wallet_path: ~/.bittensor/wallets
safe_staking: true               # MEV protection
rate_tolerance: 0.1              # Slippage tolerance
metagraph_cols:                  # Customizable display columns
  ACTIVE: true
  EMISSION: true
  # ... additional columns
```

Environment variables `BT_NETWORK`, `BT_CHAIN_ENDPOINT`, and `BTCLI_CONFIG_PATH` override config values.

---

## Bittensor Python SDK programmatic usage

Install with `pip install bittensor bittensor-wallet`. The SDK provides both synchronous and async interfaces, with async preferred for concurrent operations.

**Core imports and setup:**
```python
import bittensor as bt
from bittensor.core.subtensor import Subtensor
from bittensor.core.async_subtensor import AsyncSubtensor
from bittensor.core.metagraph import Metagraph
from bittensor_wallet import Wallet
from bittensor.utils.balance import Balance, tao, rao
```

**Wallet operations:**
```python
wallet = bt.Wallet(name="my_wallet", hotkey="my_hotkey")
wallet.unlock_coldkey()  # Required for signing
coldkey_ss58 = wallet.coldkey.ss58_address
hotkey_ss58 = wallet.hotkey.ss58_address
```

**Balance queries:**
```python
sub = bt.Subtensor(network="finney")
balance = sub.get_balance(wallet.coldkey.ss58_address)
print(f"Balance: {balance.tao} TAO")
```

**Staking operations (SDK v10 requires Balance objects):**
```python
result = sub.add_stake(
    wallet=wallet,
    hotkey_ss58="5VALIDATOR_HOTKEY...",
    netuid=1,
    amount=tao(100.0),
    wait_for_inclusion=True
)
```

**Unstaking:**
```python
async with bt.AsyncSubtensor(network='finney') as subtensor:
    result = await subtensor.unstake(
        wallet=wallet,
        netuid=1,
        hotkey_ss58="5VALIDATOR_HOTKEY...",
        amount=bt.Balance.from_tao(10)
    )
```

**Transfers:**
```python
result = sub.transfer(
    wallet=wallet,
    dest="5DESTINATION_SS58...",
    amount=tao(1.0),
    wait_for_inclusion=True
)
```

**Metagraph queries:**
```python
metagraph = Metagraph(netuid=1, network="finney", sync=True)
print(f"Total neurons: {metagraph.n.item()}")
print(f"Stakes: {metagraph.S}")  # Numpy array of stakes
print(f"Hotkeys: {metagraph.hotkeys}")  # List of hotkey SS58s

# Find top validators by stake
validators = sorted(
    [(uid, metagraph.hotkeys[uid], metagraph.S[uid]) 
     for uid in range(len(metagraph.hotkeys))],
    key=lambda x: x[2], reverse=True
)[:10]
```

**List subnets:**
```python
async with bt.AsyncSubtensor(network='finney') as subtensor:
    subnets = await subtensor.all_subnets()
    for subnet in subnets:
        print(f"Subnet {subnet.netuid}: {subnet.tao_in_emission} TAO emission")
```

**Registration:**
```python
result = sub.burned_register(wallet=wallet, netuid=3)
burn_cost = sub.burn(netuid=3)  # Check cost first
```

Important SDK v10 notes: **minimum transaction amount is 500,000 RAO (0.0005 TAO)**; floats/ints are deprecated for amounts — use `tao()`, `rao()`, or `Balance.from_tao()`.

---

## Taostats API integration

The Taostats API provides rich network data. **Base URL**: `https://api.taostats.io/api/`

**Authentication** via header:
```
Authorization: YOUR_API_KEY
```

Get API keys at `dash.taostats.io` by creating an organization and project.

**Key endpoints for taox:**

| Purpose | Endpoint |
|---------|----------|
| Network stats | `GET /stats/latest/v1` |
| Subnet list | `GET /subnets/v1` |
| Subnet details | `GET /subnet/history/v1` |
| Validator info | `GET /validator/v1` |
| Validator performance | `GET /validator/performance/v1` |
| TAO price | `GET /price/v1` |
| Price history | `GET /price/history/v1` |
| Stake balance | `GET /stake/balance/v1` |
| Metagraph | `GET /metagraph/v1` |
| Account info | `GET /account/v1` |
| Hotkey emissions | `GET /hotkey/emissions/v1` |
| Subnet prices | `GET /subnet/prices/sum/v1` |
| Alpha burned | `GET /subnet/burned-alpha/v1` |

**Python integration example:**
```python
import requests

API_KEY = "YOUR_API_KEY"
BASE_URL = "https://api.taostats.io/api"
headers = {"Authorization": API_KEY}

# Get network stats
stats = requests.get(f"{BASE_URL}/stats/latest/v1", headers=headers).json()
print(f"Total staked: {stats['data'][0]['staked']}")

# Get top validators
validators = requests.get(f"{BASE_URL}/validator/v1", headers=headers).json()
```

All responses follow paginated format with `pagination` and `data` fields. The live API at `/api/v1/live/` reads directly from the chain for real-time data.

---

## Chutes AI API for LLM inference

**Chutes** (Subnet 64) is a decentralized serverless AI compute platform on Bittensor serving **51+ models** including DeepSeek R1/V3, Qwen3 235B, Llama 3.x, Mistral, and Gemma variants.

**Base URL**: `https://llm.chutes.ai/v1`

**Authentication:**
```bash
Authorization: Bearer cpk_your_api_key
# or
X-API-Key: cpk_your_api_key
```

Chutes is **fully OpenAI API compatible**, enabling drop-in replacement:
```python
from openai import OpenAI

client = OpenAI(
    api_key="cpk_your_chutes_key",
    base_url="https://llm.chutes.ai/v1"
)

response = client.chat.completions.create(
    model="meta-llama/Llama-3.1-8B-Instruct",
    messages=[{"role": "user", "content": "What is staking in Bittensor?"}],
    max_tokens=500,
    stream=True  # Streaming supported
)
```

**Recommended models for taox:**
- **General assistant**: `meta-llama/Llama-3.1-8B-Instruct` (fast, cost-effective)
- **Complex reasoning**: `deepseek/deepseek-v3.1` (hybrid thinking)
- **Free tier**: `gpt-oss-20b`, `GLM-4.5-Air`

**Registration process:**
```bash
pip install chutes
chutes register  # Creates/links Bittensor wallet
chutes keys create --name taox-key --admin
```

Bittensor validators can link identity for **free developer access** with `chutes link`.

---

## Terminal UI implementation

**Rich library** for output formatting:
```python
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn
from rich.live import Live

console = Console()

# Styled tables
table = Table(title="Stake Positions")
table.add_column("Subnet", style="cyan")
table.add_column("Validator", style="magenta")
table.add_column("Amount", justify="right", style="green")
table.add_row("SN1", "Taostats", "150.5 τ")
console.print(table)

# Panels with borders
console.print(Panel("[bold cyan]Welcome to taox[/]", border_style="green"))

# Progress/spinners
with console.status("[bold green]Querying blockchain...") as status:
    # do work
    pass

# Live updating dashboards
with Live(generate_dashboard(), refresh_per_second=4) as live:
    while True:
        live.update(generate_dashboard())
```

**InquirerPy** for interactive prompts:
```python
from InquirerPy import inquirer

# Select menu
action = inquirer.select(
    message="What would you like to do?",
    choices=[
        {"name": "💰 Stake TAO", "value": "stake"},
        {"name": "📊 View Portfolio", "value": "portfolio"},
        {"name": "🔄 Transfer", "value": "transfer"},
    ],
    pointer="❯"
).execute()

# Fuzzy search for validators
validator = inquirer.fuzzy(
    message="Select validator:",
    choices=validator_list,
    max_height="70%"
).execute()

# Confirmation with amounts
confirm = inquirer.confirm(
    message=f"Stake 100 TAO to {validator}?",
    default=False
).execute()
```

**Textual** for full TUI applications with CSS-like styling, reactive attributes, and widget composition. Use for complex dashboard views.

**Theme centralization pattern:**
```python
from dataclasses import dataclass
from rich.theme import Theme

@dataclass
class TaoxColors:
    PRIMARY = "#61afef"
    SUCCESS = "#98c379"
    WARNING = "#e5c07b"
    ERROR = "#e06c75"
    TAO = "#00d4aa"

taox_theme = Theme({
    "tao": TaoxColors.TAO,
    "success": f"bold {TaoxColors.SUCCESS}",
    "error": f"bold {TaoxColors.ERROR}",
})
```

---

## Security implementation requirements

**Credential handling — never log sensitive data:**
```python
import logging

class SensitiveDataFilter(logging.Filter):
    SENSITIVE = ['private_key', 'mnemonic', 'seed', 'password']
    def filter(self, record):
        msg = str(record.msg).lower()
        if any(s in msg for s in self.SENSITIVE):
            record.msg = "[REDACTED]"
        return True
```

**Use system keyring for API keys:**
```python
import keyring

class CredentialManager:
    SERVICE = "taox"
    
    @classmethod
    def store(cls, key_name: str, value: str):
        keyring.set_password(cls.SERVICE, key_name, value)
    
    @classmethod
    def get(cls, key_name: str) -> str:
        return keyring.get_password(cls.SERVICE, key_name)
```

**Secure file permissions:**
```python
import os
import stat
from pathlib import Path

def create_secure_file(filepath: Path, content: str):
    filepath.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    filepath.write_text(content)
    os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR)  # 600
```

**Secure input (never accept secrets as CLI arguments):**
```python
from getpass import getpass

def get_sensitive_input(prompt: str) -> str:
    if not sys.stdin.isatty():
        raise RuntimeError("Use environment variables for non-interactive mode")
    return getpass(prompt)
```

**Transaction confirmation with address verification:**
```python
def confirm_transaction(to_address: str, amount: float) -> bool:
    console.print(Panel(f"To: {to_address}\nAmount: {amount} τ", title="⚠️ CONFIRM"))
    
    if amount >= 10.0:  # Large amount extra confirmation
        check = inquirer.text(
            message=f"Type first 8 chars of address to confirm:"
        ).execute()
        if check.lower() != to_address[:8].lower():
            return False
    
    return inquirer.confirm(message="Execute transaction?", default=False).execute()
```

**Subprocess security (always use list args, never shell=True):**
```python
import subprocess

def run_btcli(args: list[str]) -> str:
    result = subprocess.run(
        ["btcli"] + args,
        shell=False,
        capture_output=True,
        text=True,
        timeout=60
    )
    return result.stdout
```

---

## Complete btcli command reference

### Wallet commands (`btcli wallet` / `btcli w`)
- `create` — Create complete wallet (coldkey + hotkey)
- `new-coldkey` / `new-hotkey` — Create individual keys
- `regen-coldkey` / `regen-hotkey` — Regenerate from mnemonic/seed/JSON
- `list` — Display all wallets
- `balance` — Check balance (supports `--all`, `--ss58`)
- `transfer` — Send TAO (`--dest`, `--amount`)
- `swap-hotkey` — Swap hotkeys on-chain (1 TAO cost)
- `set-identity` / `get-identity` — On-chain identity
- `sign` / `verify` — Message signing

### Stake commands (`btcli stake` / `btcli st`)
- `add` — Stake TAO (`--amount`, `--netuid`, `--safe`, `--tolerance`)
- `remove` — Unstake TAO
- `list` — Show positions (`--live` for real-time)
- `move` — Move between hotkeys
- `transfer` — Transfer between coldkeys
- `swap` — Swap between subnets
- `wizard` — Interactive stake movement
- `claim` / `set-claim` — Set root claim type (keep/swap)
- `child get/set/revoke/take` — Child hotkey management

### Subnet commands (`btcli subnets` / `btcli s`)
- `list` — List all subnets
- `metagraph` — View subnet metagraph (`--netuid`, `--json-output`)
- `hyperparameters` — View hyperparameters
- `register` — Burned registration
- `pow-register` — Proof-of-work registration
- `create` — Create new subnet
- `burn-cost` — Show registration cost
- `set-identity` / `get-identity` — Subnet identity
- `price` — Historical price (4h)

### Sudo commands (`btcli sudo` / `btcli su`)
- `set` / `get` — Hyperparameters (owner only)
- `senate` — Show Senate members
- `proposals` — View proposals
- `senate-vote` — Vote (`--vote-aye` / `--vote-nay`)
- `set-take` / `get-take` — Delegate take (0-18%)

### Config commands (`btcli config` / `btcli c`)
- `set` — Set defaults (`--wallet-name`, `--network`, `--safe-staking`)
- `get` — Display config
- `clear` — Reset config

### Common flags
```
--wallet-name, --name       Wallet name
--wallet-path, -p           Wallet directory
--hotkey, -H                Hotkey name
--network                   Network (finney/test/local)
--netuid, -n                Subnet ID(s)
--amount                    TAO amount
--all, -a                   All items
--safe, --safe-staking      MEV protection
--tolerance                 Rate tolerance %
--json-output               JSON format
--prompt/--no-prompt, -y    Interactive prompts
```

---

## Taox implementation specification

### Core features to implement

**1. Natural language command parsing:**
```
User: "stake 50 tao to taostats on subnet 1"
→ Parse intent: STAKE
→ Extract: amount=50, validator="taostats", netuid=1
→ Resolve validator SS58 via Taostats API
→ Generate: btcli stake add --amount 50 --netuid 1 --include-hotkeys 5Taostats...
→ Confirm with user
→ Execute
```

**2. Conversational context:**
- Remember current wallet, network, recent operations
- Support follow-ups: "now do the same for subnet 18"
- Track conversation history for context-aware responses

**3. Smart defaults and suggestions:**
- Fetch top validators from Taostats when user says "stake to best validator"
- Calculate optimal amounts based on balance and existing positions
- Warn about gas costs, minimum amounts, registration costs

**4. Portfolio dashboard:**
- Real-time stake positions across subnets
- TAO balance and value (USD via Taostats price API)
- Pending emissions and rewards
- Historical performance charts (ASCII)

**5. Command modes:**
- **Chat mode**: Natural language conversation
- **Direct mode**: Pass-through to btcli (`taox -- stake add ...`)
- **Interactive mode**: Guided wizards with InquirerPy

### Recommended project structure
```
taox/
├── pyproject.toml
├── src/
│   └── taox/
│       ├── __init__.py
│       ├── cli.py              # Typer CLI entry point
│       ├── chat/
│       │   ├── __init__.py
│       │   ├── llm.py          # Chutes API client
│       │   ├── intents.py      # Intent classification
│       │   └── context.py      # Conversation state
│       ├── commands/
│       │   ├── __init__.py
│       │   ├── stake.py        # Stake operations
│       │   ├── wallet.py       # Wallet operations
│       │   ├── subnet.py       # Subnet operations
│       │   └── executor.py     # btcli subprocess wrapper
│       ├── data/
│       │   ├── __init__.py
│       │   ├── taostats.py     # Taostats API client
│       │   ├── sdk.py          # Bittensor SDK wrapper
│       │   └── cache.py        # Response caching
│       ├── ui/
│       │   ├── __init__.py
│       │   ├── theme.py        # Colors, styles
│       │   ├── dashboard.py    # Rich layouts
│       │   ├── prompts.py      # InquirerPy helpers
│       │   └── tables.py       # Data display
│       ├── security/
│       │   ├── __init__.py
│       │   ├── keyring.py      # Credential storage
│       │   ├── confirm.py      # Transaction confirmation
│       │   └── sanitize.py     # Input validation
│       └── config/
│           ├── __init__.py
│           └── settings.py     # Config management
├── tests/
└── README.md
```

### Configuration file (`~/.taox/config.yml`)
```yaml
# LLM settings
llm:
  provider: chutes
  api_key_keyring: taox_chutes_key  # Stored in system keyring
  model: meta-llama/Llama-3.1-8B-Instruct
  temperature: 0.7
  
# Bittensor settings
bittensor:
  network: finney
  wallet_path: ~/.bittensor/wallets
  default_wallet: default
  default_hotkey: default

# Taostats settings  
taostats:
  api_key_keyring: taox_taostats_key

# UI settings
ui:
  theme: dark
  confirm_large_tx: true
  large_tx_threshold: 10.0  # TAO

# Security
security:
  require_confirmation: true
  mask_addresses: false
```

### Example chat flow implementation
```python
async def process_message(user_input: str, context: ConversationContext):
    # 1. Get LLM to classify intent and extract entities
    classification = await llm.classify_intent(user_input, context.history)
    
    # 2. Enrich with network data
    if classification.intent == "STAKE":
        if classification.validator_name and not classification.validator_ss58:
            # Resolve name to SS58 via Taostats
            validators = await taostats.search_validators(classification.validator_name)
            classification.validator_ss58 = validators[0].hotkey_ss58
        
        if classification.amount == "all":
            balance = await sdk.get_balance(context.wallet)
            classification.amount = balance.tao - 0.1  # Keep some for gas
    
    # 3. Generate command preview
    cmd = build_btcli_command(classification)
    
    # 4. Show confirmation UI
    console.print(Panel(
        f"[cyan]Command:[/] btcli {' '.join(cmd)}\n"
        f"[yellow]Amount:[/] {classification.amount} τ\n"
        f"[green]To:[/] {classification.validator_name}",
        title="📋 Review Transaction"
    ))
    
    # 5. Confirm and execute
    if await confirm_transaction(classification):
        result = await execute_btcli(cmd)
        context.add_to_history(user_input, result)
        return f"✅ Staked {classification.amount} TAO successfully!"
    
    return "Transaction cancelled."
```

### System prompt for Chutes LLM
```
You are taox, an AI assistant for the Bittensor network. You help users manage their TAO tokens, stake to validators, and interact with subnets.

When users request actions, extract the following into JSON:
- intent: STAKE | UNSTAKE | TRANSFER | BALANCE | PORTFOLIO | METAGRAPH | REGISTER | INFO
- amount: number or "all"
- validator_name: string (if mentioned)
- validator_ss58: SS58 address (if provided directly)
- netuid: subnet number
- wallet_name: string
- destination: SS58 address (for transfers)

Current context:
- Active wallet: {wallet_name}
- Network: {network}
- Recent actions: {recent_history}

Always confirm understanding before suggesting commands. For amounts over 10 TAO, emphasize the confirmation requirement.
```

---

## Dependencies

```toml
[project]
dependencies = [
    "bittensor>=8.0.0",
    "bittensor-wallet>=2.0.0",
    "typer>=0.9.0",
    "rich>=13.0.0",
    "textual>=0.40.0",
    "InquirerPy>=0.3.4",
    "openai>=1.0.0",  # For Chutes API compatibility
    "aiohttp>=3.9.0",
    "httpx>=0.25.0",
    "keyring>=24.0.0",
    "pyyaml>=6.0",
    "pydantic>=2.0.0",
    "cachetools>=5.3.0",
]
```

---

## Implementation priorities

**Phase 1 — Core functionality:**
1. CLI skeleton with Typer
2. Chutes LLM integration for intent parsing
3. Basic stake/unstake/transfer commands
4. Rich console output
5. Security fundamentals (keyring, confirmation)

**Phase 2 — Data enrichment:**
1. Taostats API integration
2. Validator search/ranking
3. Portfolio dashboard
4. Balance display with USD value

**Phase 3 — Advanced features:**
1. Conversation context and history
2. Interactive wizards with InquirerPy
3. Full TUI dashboard with Textual
4. Child hotkey management
5. Subnet registration flows

**Phase 4 — Polish:**
1. Error handling and recovery
2. Offline mode with cached data
3. Multi-wallet support
4. Transaction history export
5. Comprehensive test suite

---

This document provides all technical specifications needed to build taox. The combination of Chutes for AI inference, Taostats for network intelligence, the Bittensor SDK for programmatic operations, and Rich/Textual/InquirerPy for beautiful terminal interfaces enables a production-quality conversational CLI that makes Bittensor accessible to users of all technical levels.

