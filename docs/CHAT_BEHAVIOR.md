# Chat Behavior Guide

This document describes how taox's conversational chat mode works, including the state machine, slot-filling, confirmations, and memory system.

## Overview

taox chat mode uses a **conversation state machine** that enables natural multi-turn conversations:

1. **Slot-Filling**: Asks for missing information one question at a time
2. **Confirmations**: Always confirms before executing transactions
3. **Memory**: Remembers your defaults and recent actions
4. **Follow-up Suggestions**: Offers helpful next actions after completing tasks

## Conversation States

The chat engine operates in one of these states:

| State | Description | User Prompt |
|-------|-------------|-------------|
| `IDLE` | Waiting for new command | `You:` |
| `SLOT_FILLING` | Collecting missing info | `>` |
| `CONFIRMING` | Waiting for yes/no | `(yes/no)>` |
| `EXECUTING` | Running the command | (internal) |

## Intent Types

### Transaction Intents (Require Confirmation)

| Intent | Example | Required Slots |
|--------|---------|----------------|
| `STAKE` | "stake 10 TAO to Taostats" | amount, validator, netuid |
| `UNSTAKE` | "unstake 5 TAO" | amount, validator, netuid |
| `TRANSFER` | "send 20 TAO to 5xxx..." | amount, destination |
| `REGISTER` | "register on subnet 18" | netuid |

### Query Intents (No Confirmation)

| Intent | Example | Required Slots |
|--------|---------|----------------|
| `BALANCE` | "what's my balance?" | (none) |
| `PORTFOLIO` | "show my portfolio" | (none) |
| `VALIDATORS` | "show validators on subnet 1" | (none, netuid optional) |
| `SUBNETS` | "list subnets" | (none) |
| `METAGRAPH` | "show metagraph for subnet 18" | netuid |

### Meta Intents

| Intent | Triggers |
|--------|----------|
| `HELP` | "help", "what can you do" |
| `SET_DEFAULT` | "use wallet X from now on" |
| `CANCEL` | "cancel", "nevermind" |
| `GREETING` | "hi", "hello" |

## Slot-Filling Flow

When required information is missing, taox asks for it one question at a time:

```
You: stake 10 TAO
> Which validator would you like to stake to? (e.g., Taostats, OpenTensor Foundation)
> Taostats
> On which subnet? (e.g., 1, 18, 8)
> 1

**Here's what I'll do:**

• Stake **10 τ** to **Taostats** on subnet **1**
• Using wallet: **default**

**Proceed?** (yes/no)
(yes/no)> yes

Processing stake...
```

### Slot Types

| Slot | Description | Examples |
|------|-------------|----------|
| `amount` | TAO amount | `10`, `50.5`, `all` |
| `validator` | Validator name or SS58 | `Taostats`, `5FFApa...` |
| `netuid` | Subnet ID | `1`, `18` |
| `destination` | Transfer recipient (SS58) | `5GrwvaEF...` |
| `wallet` | Wallet name | `default`, `mywallet` |
| `hotkey` | Hotkey name | `default`, `miner1` |

## Confirmation Flow

All transaction intents require explicit confirmation:

```
**Here's what I'll do:**

• Stake **10 τ** to **Taostats** on subnet **1**
• Using wallet: **default**

**Proceed?** (yes/no)
```

### Confirmation Responses

| Positive | Negative |
|----------|----------|
| yes, y, ok, okay | no, n, cancel |
| confirm, sure | stop, nevermind |
| go, do it, proceed | |

## Memory System

taox remembers your preferences across sessions.

### Persistent Preferences

Stored in `~/.taox/preferences.json`:

| Preference | Description | Example |
|------------|-------------|---------|
| `default_wallet` | Default wallet name | `"myvalidator"` |
| `default_hotkey` | Default hotkey name | `"default"` |
| `default_network` | Default network | `"finney"` |
| `default_netuid` | Default subnet | `1` |
| `last_validator` | Last used validator | `"Taostats"` |
| `last_netuid` | Last used subnet | `18` |

### Setting Defaults

Use natural language to set defaults:

```
You: use wallet myvalidator from now on
Got it! I'll use wallet **myvalidator** by default from now on.

You: default subnet 18
Got it! I'll use subnet **18** by default from now on.
```

### Automatic Default Application

Defaults are automatically applied when slots are not specified:

```
You: stake 10 TAO to Taostats
# Uses default_netuid if set, otherwise asks
```

## Follow-up Suggestions

After completing an action, taox suggests relevant follow-ups:

```
Processed stake of 10 τ on subnet 1.

Suggestions:
  1. View updated portfolio
  2. Check balance
  3. Stake to another validator
```

### Suggestions by Intent

| After | Suggested Actions |
|-------|-------------------|
| Stake | View portfolio, Check balance, Stake more |
| Unstake | View portfolio, Check balance, Stake elsewhere |
| Transfer | Check balance, View history |
| Balance | View portfolio, Show validators |
| Portfolio | Stake more, Unstake |
| Validators | Stake to validator, View metagraph |

## Cancellation

Cancel any pending action at any time:

```
You: stake 10 TAO
> Which validator?
> cancel
Cancelled. What else can I help with?
```

Or press `Ctrl+C` to cancel and return to IDLE state.

## Example Conversations

### Complete Stake Flow

```
You: I want to stake some TAO
> How much TAO would you like to stake? (e.g., 10, 50.5, all)
> 50
> Which validator would you like to stake to? (e.g., Taostats, OpenTensor Foundation)
> Taostats
> On which subnet? (e.g., 1, 18, 8)
> 1

**Here's what I'll do:**

• Stake **50 τ** to **Taostats** on subnet **1**
• Using wallet: **default**

**Proceed?** (yes/no)
(yes/no)> yes

Processing stake...
✅ Staked 50 τ to Taostats

Suggestions:
  1. View updated portfolio
  2. Check balance
  3. Stake to another validator
```

### Quick Commands (All Info Provided)

```
You: stake 10 TAO to Taostats on subnet 1

**Here's what I'll do:**

• Stake **10 τ** to **Taostats** on subnet **1**
• Using wallet: **default**

**Proceed?** (yes/no)
(yes/no)> yes

Processing stake...
✅ Done
```

### Query Commands (No Confirmation)

```
You: what's my balance?

Balance for wallet 'default':
┌─────────────────┬────────────────┐
│ Type            │ Amount         │
├─────────────────┼────────────────┤
│ Free            │ 100.5000 τ     │
│ Staked          │ 500.0000 τ     │
│ Total           │ 600.5000 τ     │
└─────────────────┴────────────────┘
```

### Using Remembered Context

```
You: stake 10 TAO to Taostats on subnet 1
(confirmed and executed)

You: do the same on subnet 18
# Uses last_validator (Taostats) and asks only for amount

You: stake 20 more
# Uses last_validator AND last_netuid

```

## Technical Details

### State Machine Implementation

The conversation engine is in [state_machine.py](../src/taox/chat/state_machine.py):

- `ConversationEngine` - Main state machine class
- `ParsedIntent` - Pydantic model for parsed intents
- `FilledSlots` - Container for slot values
- `UserPreferences` - Persistent memory
- `PendingAction` - Tracks in-progress actions

### Integration with CLI

The chat loop in [cli.py](../src/taox/cli.py) uses `_process_message_v2()` which:

1. Passes input to `engine.process_input()`
2. Gets a `ConversationResponse` with action type
3. Handles `DISPLAY`, `ASK`, `CONFIRM`, or `EXECUTE` actions
4. Shows follow-up suggestions after execution

### Preferences File Location

```
~/.taox/preferences.json
```

### Clearing State

```
You: clear
# Clears conversation history but keeps preferences
```

## Design Principles

1. **Never Guess**: If required info is missing, ask. Don't assume.
2. **One Question at a Time**: Don't overwhelm. Ask for one slot at a time.
3. **Always Confirm Transactions**: Never execute money-moving operations without explicit yes/no.
4. **Remember Context**: Use memory to reduce friction for repeat users.
5. **Suggest Next Steps**: Help users discover what they can do next.
6. **Allow Escape**: Users can always cancel with "cancel" or Ctrl+C.
