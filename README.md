# taox

AI-powered conversational CLI for Bittensor.

## Installation

```bash
pip install -e .
```

## Usage

```bash
# Start chat mode
taox chat

# Demo mode (no real transactions)
taox --demo chat

# Configure API keys
taox setup

# Direct commands
taox balance
taox validators
taox subnets

# Pass through to btcli
taox -- wallet list
```

## Chat Examples

```
You: what is my balance?
You: stake 10 TAO to taostats on subnet 1
You: show validators on subnet 18
You: list subnets
```
