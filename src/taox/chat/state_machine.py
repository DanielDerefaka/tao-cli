"""Conversational state machine for taox chat mode.

This module implements a slot-filling conversation engine that:
- Defines structured Intent + Slot models
- Asks for missing required information
- Maintains conversation state with persistent defaults
- Requires explicit confirmation before transactions
- Suggests follow-up actions after completion
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field

from taox.config.settings import get_settings

logger = logging.getLogger(__name__)

# User preferences file
PREFERENCES_FILE = Path.home() / ".taox" / "preferences.json"


# =============================================================================
# Intent Types
# =============================================================================


class IntentType(str, Enum):
    """Types of user intents that taox can handle."""

    # Transaction intents (require confirmation)
    STAKE = "stake"
    UNSTAKE = "unstake"
    TRANSFER = "transfer"
    REGISTER = "register"

    # Query intents (no confirmation needed)
    BALANCE = "balance"
    PORTFOLIO = "portfolio"
    VALIDATORS = "validators"
    SUBNETS = "subnets"
    METAGRAPH = "metagraph"
    HISTORY = "history"

    # Meta intents
    HELP = "help"
    SET_DEFAULT = "set_default"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    GREETING = "greeting"
    UNKNOWN = "unknown"


# =============================================================================
# Slot Definitions
# =============================================================================


class SlotType(str, Enum):
    """Types of slots that can be filled."""

    AMOUNT = "amount"
    DESTINATION = "destination"
    VALIDATOR = "validator"
    NETUID = "netuid"
    WALLET = "wallet"
    HOTKEY = "hotkey"
    NETWORK = "network"
    SAFETY = "safety"  # safe staking flag


@dataclass
class SlotDefinition:
    """Definition of a slot with its properties."""

    name: SlotType
    required: bool
    prompt: str  # Question to ask if missing
    default_key: Optional[str] = None  # Key in user preferences for default
    validator: Optional[Callable[[Any], bool]] = None
    examples: list[str] = field(default_factory=list)


# Slot definitions for each intent type
INTENT_SLOTS: dict[IntentType, list[SlotDefinition]] = {
    IntentType.STAKE: [
        SlotDefinition(
            name=SlotType.AMOUNT,
            required=True,
            prompt="How much TAO would you like to stake?",
            examples=["10", "50.5", "all"],
        ),
        SlotDefinition(
            name=SlotType.VALIDATOR,
            required=True,
            prompt="Which validator would you like to stake to?",
            examples=["Taostats", "OpenTensor Foundation", "5FFApa..."],
        ),
        SlotDefinition(
            name=SlotType.NETUID,
            required=True,
            prompt="On which subnet?",
            default_key="default_netuid",
            examples=["1", "18", "8"],
        ),
        SlotDefinition(
            name=SlotType.WALLET,
            required=False,
            prompt="Which wallet should I use?",
            default_key="default_wallet",
        ),
    ],
    IntentType.UNSTAKE: [
        SlotDefinition(
            name=SlotType.AMOUNT,
            required=True,
            prompt="How much TAO would you like to unstake?",
            examples=["10", "50.5", "all"],
        ),
        SlotDefinition(
            name=SlotType.VALIDATOR,
            required=True,
            prompt="From which validator?",
        ),
        SlotDefinition(
            name=SlotType.NETUID,
            required=True,
            prompt="From which subnet?",
            default_key="default_netuid",
        ),
        SlotDefinition(
            name=SlotType.WALLET,
            required=False,
            prompt="Which wallet should I use?",
            default_key="default_wallet",
        ),
    ],
    IntentType.TRANSFER: [
        SlotDefinition(
            name=SlotType.AMOUNT,
            required=True,
            prompt="How much TAO would you like to transfer?",
            examples=["10", "50.5"],
        ),
        SlotDefinition(
            name=SlotType.DESTINATION,
            required=True,
            prompt="What is the destination address? (SS58 format)",
            examples=["5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"],
        ),
        SlotDefinition(
            name=SlotType.WALLET,
            required=False,
            prompt="Which wallet should I use?",
            default_key="default_wallet",
        ),
    ],
    IntentType.REGISTER: [
        SlotDefinition(
            name=SlotType.NETUID,
            required=True,
            prompt="Which subnet would you like to register on?",
            examples=["1", "18"],
        ),
        SlotDefinition(
            name=SlotType.WALLET,
            required=False,
            prompt="Which wallet should I use?",
            default_key="default_wallet",
        ),
        SlotDefinition(
            name=SlotType.HOTKEY,
            required=False,
            prompt="Which hotkey should I register?",
            default_key="default_hotkey",
        ),
    ],
    IntentType.BALANCE: [
        SlotDefinition(
            name=SlotType.WALLET,
            required=False,
            prompt="Which wallet?",
            default_key="default_wallet",
        ),
    ],
    IntentType.PORTFOLIO: [
        SlotDefinition(
            name=SlotType.WALLET,
            required=False,
            prompt="Which wallet?",
            default_key="default_wallet",
        ),
    ],
    IntentType.VALIDATORS: [
        SlotDefinition(
            name=SlotType.NETUID,
            required=False,
            prompt="For which subnet? (leave blank for all)",
            default_key="default_netuid",
        ),
    ],
    IntentType.METAGRAPH: [
        SlotDefinition(
            name=SlotType.NETUID,
            required=True,
            prompt="Which subnet's metagraph would you like to see?",
            default_key="default_netuid",
        ),
    ],
}


# =============================================================================
# Pydantic Models for Slots
# =============================================================================


class FilledSlots(BaseModel):
    """Container for all filled slot values."""

    model_config = ConfigDict(extra="allow")  # Allow extra fields for flexibility

    amount: Optional[float] = None
    amount_all: bool = False  # True if user said "all"
    destination: Optional[str] = None
    validator_name: Optional[str] = None
    validator_ss58: Optional[str] = None
    netuid: Optional[int] = None
    wallet: Optional[str] = None
    hotkey: Optional[str] = None
    network: Optional[str] = None
    safety: bool = True  # Safe staking by default

    def get_slot(self, slot_type: SlotType) -> Optional[Any]:
        """Get value for a slot type."""
        mapping = {
            SlotType.AMOUNT: self.amount if not self.amount_all else "all",
            SlotType.DESTINATION: self.destination,
            SlotType.VALIDATOR: self.validator_name or self.validator_ss58,
            SlotType.NETUID: self.netuid,
            SlotType.WALLET: self.wallet,
            SlotType.HOTKEY: self.hotkey,
            SlotType.NETWORK: self.network,
            SlotType.SAFETY: self.safety,
        }
        return mapping.get(slot_type)

    def set_slot(self, slot_type: SlotType, value: Any) -> None:
        """Set value for a slot type."""
        if slot_type == SlotType.AMOUNT:
            if value == "all" or value == "ALL":
                self.amount_all = True
                self.amount = None
            else:
                self.amount = float(value) if value else None
        elif slot_type == SlotType.DESTINATION:
            self.destination = value
        elif slot_type == SlotType.VALIDATOR:
            # Check if it's an SS58 address (starts with 5 and ~48 chars)
            if value and isinstance(value, str) and value.startswith("5") and len(value) > 40:
                self.validator_ss58 = value
            else:
                self.validator_name = value
        elif slot_type == SlotType.NETUID:
            # Parse netuid from various formats: "1", "sn1", "sn 1", "subnet 1", etc.
            if value:
                import re
                text = str(value).strip().lower()
                # Try to extract number from formats like "sn 1", "subnet 1", "sn1"
                match = re.search(r"(?:subnet\s*|sn\s*)?(\d+)", text)
                if match:
                    self.netuid = int(match.group(1))
                else:
                    self.netuid = None
            else:
                self.netuid = None
        elif slot_type == SlotType.WALLET:
            self.wallet = value
        elif slot_type == SlotType.HOTKEY:
            self.hotkey = value
        elif slot_type == SlotType.NETWORK:
            self.network = value
        elif slot_type == SlotType.SAFETY:
            self.safety = bool(value)


class ParsedIntent(BaseModel):
    """A parsed intent with its slots."""

    type: IntentType
    slots: FilledSlots = Field(default_factory=FilledSlots)
    raw_input: str = ""
    confidence: float = 1.0

    def __str__(self) -> str:
        parts = [f"Intent({self.type.value}"]
        if self.slots.amount is not None:
            parts.append(f", amount={self.slots.amount}")
        if self.slots.amount_all:
            parts.append(", amount=ALL")
        if self.slots.validator_name:
            parts.append(f", validator={self.slots.validator_name}")
        if self.slots.netuid is not None:
            parts.append(f", netuid={self.slots.netuid}")
        if self.slots.destination:
            dest = self.slots.destination
            parts.append(
                f", dest={dest[:12]}...{dest[-6:]}" if len(dest) > 20 else f", dest={dest}"
            )
        parts.append(")")
        return "".join(parts)


# =============================================================================
# User Preferences (Memory)
# =============================================================================


class UserPreferences(BaseModel):
    """Persistent user preferences for defaults."""

    default_wallet: Optional[str] = None
    default_hotkey: Optional[str] = None
    default_network: str = "finney"
    default_netuid: Optional[int] = None
    last_validator: Optional[str] = None
    last_netuid: Optional[int] = None
    last_amount: Optional[float] = None
    updated_at: Optional[str] = None

    @classmethod
    def load(cls) -> "UserPreferences":
        """Load preferences from disk."""
        try:
            if PREFERENCES_FILE.exists():
                with open(PREFERENCES_FILE) as f:
                    data = json.load(f)
                    return cls(**data)
        except Exception as e:
            logger.warning(f"Failed to load preferences: {e}")
        return cls()

    def save(self) -> None:
        """Save preferences to disk."""
        try:
            PREFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.updated_at = datetime.now().isoformat()
            with open(PREFERENCES_FILE, "w") as f:
                json.dump(self.model_dump(), f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save preferences: {e}")

    def get_default(self, key: str) -> Optional[Any]:
        """Get a default value by key."""
        return getattr(self, key, None)

    def set_default(self, key: str, value: Any) -> None:
        """Set a default value and save."""
        if hasattr(self, key):
            setattr(self, key, value)
            self.save()


# =============================================================================
# Conversation State
# =============================================================================


class ConversationState(str, Enum):
    """States in the conversation state machine."""

    IDLE = "idle"  # Waiting for user input
    SLOT_FILLING = "slot_filling"  # Collecting missing information
    CONFIRMING = "confirming"  # Waiting for user confirmation
    EXECUTING = "executing"  # Running the command
    SUGGESTING = "suggesting"  # Offering follow-up actions


@dataclass
class PendingAction:
    """An action waiting for confirmation or slot-filling."""

    intent: ParsedIntent
    missing_slots: list[SlotDefinition] = field(default_factory=list)
    current_slot_index: int = 0
    confirmed: bool = False

    @property
    def current_missing_slot(self) -> Optional[SlotDefinition]:
        """Get the current slot being filled."""
        if self.current_slot_index < len(self.missing_slots):
            return self.missing_slots[self.current_slot_index]
        return None

    @property
    def all_slots_filled(self) -> bool:
        """Check if all required slots are filled."""
        return self.current_slot_index >= len(self.missing_slots)


class ConversationEngine:
    """Main conversation engine with state machine logic.

    Handles:
    - Intent parsing with slot extraction
    - Slot-filling loop for missing information
    - Plan + confirm step before transactions
    - Memory for defaults
    - Follow-up suggestions
    """

    # Transaction intents that require confirmation
    TRANSACTION_INTENTS = {
        IntentType.STAKE,
        IntentType.UNSTAKE,
        IntentType.TRANSFER,
        IntentType.REGISTER,
    }

    def __init__(self):
        """Initialize the conversation engine."""
        self.state = ConversationState.IDLE
        self.preferences = UserPreferences.load()
        self.pending_action: Optional[PendingAction] = None
        self.last_completed_intent: Optional[IntentType] = None

        # Sync with config settings
        settings = get_settings()
        if not self.preferences.default_wallet:
            self.preferences.default_wallet = settings.bittensor.default_wallet
        if not self.preferences.default_hotkey:
            self.preferences.default_hotkey = settings.bittensor.default_hotkey
        if not self.preferences.default_network:
            self.preferences.default_network = settings.bittensor.network

    def get_state_prompt(self) -> Optional[str]:
        """Get prompt for current state (if any)."""
        if self.state == ConversationState.SLOT_FILLING and self.pending_action:
            slot = self.pending_action.current_missing_slot
            if slot:
                prompt = slot.prompt
                if slot.examples:
                    prompt += f" (e.g., {', '.join(slot.examples[:2])})"
                return prompt

        elif self.state == ConversationState.CONFIRMING and self.pending_action:
            return self._build_confirmation_prompt()

        return None

    def _build_confirmation_prompt(self) -> str:
        """Build the confirmation prompt showing the planned action."""
        if not self.pending_action:
            return "Confirm? (yes/no)"

        intent = self.pending_action.intent
        slots = intent.slots

        lines = ["**Here's what I'll do:**", ""]

        if intent.type == IntentType.STAKE:
            amount = "all available" if slots.amount_all else f"{slots.amount} τ"
            validator = slots.validator_name or slots.validator_ss58 or "?"
            lines.append(f"• Stake **{amount}** to **{validator}** on subnet **{slots.netuid}**")
            if slots.wallet:
                lines.append(f"• Using wallet: **{slots.wallet}**")

        elif intent.type == IntentType.UNSTAKE:
            amount = "all" if slots.amount_all else f"{slots.amount} τ"
            validator = slots.validator_name or slots.validator_ss58 or "?"
            lines.append(
                f"• Unstake **{amount}** from **{validator}** on subnet **{slots.netuid}**"
            )

        elif intent.type == IntentType.TRANSFER:
            dest = slots.destination or "?"
            if len(dest) > 20:
                dest = f"{dest[:8]}...{dest[-6:]}"
            lines.append(f"• Transfer **{slots.amount} τ** to **{dest}**")
            if slots.wallet:
                lines.append(f"• From wallet: **{slots.wallet}**")

        elif intent.type == IntentType.REGISTER:
            lines.append(f"• Register on subnet **{slots.netuid}**")
            if slots.wallet:
                lines.append(f"• Using wallet: **{slots.wallet}**")
            if slots.hotkey:
                lines.append(f"• Hotkey: **{slots.hotkey}**")

        lines.append("")
        lines.append("**Proceed?** (yes/no)")

        return "\n".join(lines)

    def process_input(
        self, user_input: str, parsed_intent: Optional[ParsedIntent] = None
    ) -> "ConversationResponse":
        """Process user input and return appropriate response.

        Args:
            user_input: Raw user input
            parsed_intent: Pre-parsed intent (optional, will parse if not provided)

        Returns:
            ConversationResponse with action to take
        """
        text = user_input.strip().lower()

        # Handle state-specific processing
        if self.state == ConversationState.SLOT_FILLING:
            return self._handle_slot_input(user_input)

        elif self.state == ConversationState.CONFIRMING:
            return self._handle_confirmation_input(text)

        # IDLE state - parse new intent
        if parsed_intent is None:
            parsed_intent = self._parse_intent(user_input)

        # Handle meta intents
        if parsed_intent.type == IntentType.CANCEL:
            self._reset()
            return ConversationResponse(
                message="Cancelled. What else can I help with?",
                action=ResponseAction.DISPLAY,
            )

        if parsed_intent.type == IntentType.SET_DEFAULT:
            return self._handle_set_default(user_input)

        if parsed_intent.type == IntentType.HELP:
            return ConversationResponse(
                message=self._get_help_text(),
                action=ResponseAction.DISPLAY,
            )

        if parsed_intent.type == IntentType.GREETING:
            # Vary the greeting response
            import random

            greetings = [
                "Hey! What can I help you with?",
                "Hi there! Ready to manage your TAO.",
                "What's up! Balance, staking, or something else?",
                "Hey! Ask me anything about your wallet.",
            ]
            return ConversationResponse(
                message=random.choice(greetings),
                action=ResponseAction.DISPLAY,
            )

        if parsed_intent.type == IntentType.UNKNOWN:
            # More conversational fallback
            text = user_input.lower()
            # Check if it looks like a question
            if "?" in user_input or text.startswith(("what", "how", "why", "when", "where", "who")):
                return ConversationResponse(
                    message="I focus on Bittensor operations - balance, staking, transfers, and registrations. What would you like to do?",
                    action=ResponseAction.DISPLAY,
                )
            return ConversationResponse(
                message="Not sure I understood that. Try something like 'show my balance' or 'stake 10 TAO'.",
                action=ResponseAction.DISPLAY,
            )

        # Apply defaults and check for missing slots
        self._apply_defaults(parsed_intent)
        missing_slots = self._get_missing_slots(parsed_intent)

        if missing_slots:
            # Start slot-filling
            self.pending_action = PendingAction(
                intent=parsed_intent,
                missing_slots=missing_slots,
            )
            self.state = ConversationState.SLOT_FILLING

            slot = missing_slots[0]
            prompt = slot.prompt
            if slot.examples:
                prompt += f" (e.g., {', '.join(slot.examples[:2])})"

            return ConversationResponse(
                message=prompt,
                action=ResponseAction.ASK,
                slot_being_filled=slot.name,
            )

        # All slots filled - check if confirmation needed
        if parsed_intent.type in self.TRANSACTION_INTENTS:
            self.pending_action = PendingAction(intent=parsed_intent)
            self.state = ConversationState.CONFIRMING

            return ConversationResponse(
                message=self._build_confirmation_prompt(),
                action=ResponseAction.CONFIRM,
                intent=parsed_intent,
            )

        # Query intent - execute directly
        return ConversationResponse(
            message="",
            action=ResponseAction.EXECUTE,
            intent=parsed_intent,
        )

    def _handle_slot_input(self, user_input: str) -> "ConversationResponse":
        """Handle input when in slot-filling state."""
        if not self.pending_action:
            self._reset()
            return ConversationResponse(
                message="Something went wrong. Let's start over. What would you like to do?",
                action=ResponseAction.DISPLAY,
            )

        text = user_input.strip().lower()

        # Check for cancel
        if text in ("cancel", "nevermind", "stop", "no"):
            self._reset()
            return ConversationResponse(
                message="Cancelled. What else can I help with?",
                action=ResponseAction.DISPLAY,
            )

        # Get current slot and fill it
        slot = self.pending_action.current_missing_slot
        if slot:
            try:
                self.pending_action.intent.slots.set_slot(slot.name, user_input.strip())
            except (ValueError, TypeError):
                return ConversationResponse(
                    message=f"That doesn't look right. {slot.prompt}",
                    action=ResponseAction.ASK,
                    slot_being_filled=slot.name,
                )

            self.pending_action.current_slot_index += 1

        # Check if more slots needed
        if not self.pending_action.all_slots_filled:
            next_slot = self.pending_action.current_missing_slot
            if next_slot:
                prompt = next_slot.prompt
                if next_slot.examples:
                    prompt += f" (e.g., {', '.join(next_slot.examples[:2])})"
                return ConversationResponse(
                    message=prompt,
                    action=ResponseAction.ASK,
                    slot_being_filled=next_slot.name,
                )

        # All slots filled - move to confirmation if transaction
        intent = self.pending_action.intent
        if intent.type in self.TRANSACTION_INTENTS:
            self.state = ConversationState.CONFIRMING
            return ConversationResponse(
                message=self._build_confirmation_prompt(),
                action=ResponseAction.CONFIRM,
                intent=intent,
            )

        # Query - execute directly
        self.state = ConversationState.IDLE
        result_intent = self.pending_action.intent
        self.pending_action = None

        return ConversationResponse(
            message="",
            action=ResponseAction.EXECUTE,
            intent=result_intent,
        )

    def _handle_confirmation_input(self, text: str) -> "ConversationResponse":
        """Handle input when in confirmation state."""
        if not self.pending_action:
            self._reset()
            return ConversationResponse(
                message="Something went wrong. Let's start over.",
                action=ResponseAction.DISPLAY,
            )

        # Check for positive confirmation
        if text in ("yes", "y", "ok", "okay", "confirm", "sure", "go", "do it", "proceed"):
            self.pending_action.confirmed = True
            intent = self.pending_action.intent

            # Update last used values in preferences
            slots = intent.slots
            if slots.validator_name:
                self.preferences.last_validator = slots.validator_name
            if slots.netuid is not None:
                self.preferences.last_netuid = slots.netuid
            if slots.amount is not None:
                self.preferences.last_amount = slots.amount
            self.preferences.save()

            self.last_completed_intent = intent.type
            self.state = ConversationState.IDLE
            result_intent = intent
            self.pending_action = None

            return ConversationResponse(
                message="",
                action=ResponseAction.EXECUTE,
                intent=result_intent,
            )

        # Check for negative
        if text in ("no", "n", "cancel", "stop", "nevermind"):
            self._reset()
            return ConversationResponse(
                message="Cancelled. What else can I help with?",
                action=ResponseAction.DISPLAY,
            )

        # Unclear response
        return ConversationResponse(
            message="Please confirm with 'yes' or 'no'.",
            action=ResponseAction.CONFIRM,
            intent=self.pending_action.intent,
        )

    def get_follow_up_suggestions(self) -> list[str]:
        """Get suggested follow-up actions based on last completed action."""
        if not self.last_completed_intent:
            return []

        suggestions = {
            IntentType.STAKE: [
                "View updated portfolio",
                "Check balance",
                "Stake to another validator",
            ],
            IntentType.UNSTAKE: [
                "View updated portfolio",
                "Check balance",
                "Stake to a new validator",
            ],
            IntentType.TRANSFER: [
                "Check balance",
                "View transaction history",
            ],
            IntentType.BALANCE: [
                "View portfolio",
                "Show top validators",
            ],
            IntentType.PORTFOLIO: [
                "Stake more TAO",
                "Unstake from a position",
            ],
            IntentType.VALIDATORS: [
                "Stake to a validator",
                "View metagraph",
            ],
        }

        return suggestions.get(self.last_completed_intent, [])

    def _parse_intent(self, user_input: str) -> ParsedIntent:
        """Parse user input into a ParsedIntent using pattern matching."""
        from taox.chat.intents import IntentType as OldIntentType
        from taox.chat.intents import MockIntentParser

        # Use existing mock parser
        old_intent = MockIntentParser.parse(user_input)

        # Map old intent type to new
        type_mapping = {
            OldIntentType.STAKE: IntentType.STAKE,
            OldIntentType.UNSTAKE: IntentType.UNSTAKE,
            OldIntentType.TRANSFER: IntentType.TRANSFER,
            OldIntentType.BALANCE: IntentType.BALANCE,
            OldIntentType.PORTFOLIO: IntentType.PORTFOLIO,
            OldIntentType.METAGRAPH: IntentType.METAGRAPH,
            OldIntentType.REGISTER: IntentType.REGISTER,
            OldIntentType.VALIDATORS: IntentType.VALIDATORS,
            OldIntentType.SUBNETS: IntentType.SUBNETS,
            OldIntentType.HISTORY: IntentType.HISTORY,
            OldIntentType.SET_CONFIG: IntentType.SET_DEFAULT,  # Map to SET_DEFAULT
            OldIntentType.HELP: IntentType.HELP,
            OldIntentType.CONFIRM: IntentType.CONFIRM,
            OldIntentType.GREETING: IntentType.GREETING,
            OldIntentType.UNKNOWN: IntentType.UNKNOWN,
        }

        intent_type = type_mapping.get(old_intent.type, IntentType.UNKNOWN)

        # Check for cancel intent
        text = user_input.strip().lower()
        if text in ("cancel", "nevermind", "stop", "abort"):
            intent_type = IntentType.CANCEL

        # Check for set default/config commands
        if any(
            phrase in text
            for phrase in [
                "use wallet",
                "default wallet",
                "switch to",
                "my hotkey is",
                "hotkey is",
                "my wallet is",
                "wallet is",
                "set hotkey",
                "change hotkey",
                "set wallet",
                "change wallet",
            ]
        ):
            intent_type = IntentType.SET_DEFAULT

        # Build slots from old intent
        slots = FilledSlots(
            amount=old_intent.amount,
            amount_all=old_intent.amount_all,
            destination=old_intent.destination,
            validator_name=old_intent.validator_name,
            validator_ss58=old_intent.validator_ss58,
            netuid=old_intent.netuid,
            wallet=old_intent.wallet_name,
            hotkey=old_intent.hotkey_name,
        )

        return ParsedIntent(
            type=intent_type,
            slots=slots,
            raw_input=user_input,
            confidence=old_intent.confidence,
        )

    def _apply_defaults(self, intent: ParsedIntent) -> None:
        """Apply user defaults to unfilled slots."""
        slots = intent.slots

        # Apply wallet default
        if not slots.wallet and self.preferences.default_wallet:
            slots.wallet = self.preferences.default_wallet

        # Apply hotkey default
        if not slots.hotkey and self.preferences.default_hotkey:
            slots.hotkey = self.preferences.default_hotkey

        # Apply network default
        if not slots.network and self.preferences.default_network:
            slots.network = self.preferences.default_network

        # For certain intents, apply last-used values
        if intent.type in (IntentType.STAKE, IntentType.UNSTAKE, IntentType.METAGRAPH):
            # Apply default netuid
            if slots.netuid is None and self.preferences.default_netuid:
                slots.netuid = self.preferences.default_netuid

    def _get_missing_slots(self, intent: ParsedIntent) -> list[SlotDefinition]:
        """Get list of missing required slots for an intent."""
        slot_defs = INTENT_SLOTS.get(intent.type, [])
        missing = []

        for slot_def in slot_defs:
            if not slot_def.required:
                continue

            value = intent.slots.get_slot(slot_def.name)
            if value is None:
                missing.append(slot_def)

        return missing

    def _handle_set_default(self, user_input: str) -> "ConversationResponse":
        """Handle 'set default' commands."""
        import re

        text = user_input.lower()

        # Match "my hotkey is X" or "hotkey is X" or "set hotkey to X"
        hotkey_match = re.search(
            r"(?:my\s+)?hotkey\s+(?:is|should be|=)\s*(\w+)|"
            r"(?:set|use|change)\s+(?:my\s+)?hotkey\s+(?:to\s+)?(\w+)",
            text,
        )
        if hotkey_match:
            hotkey_name = hotkey_match.group(1) or hotkey_match.group(2)
            self.preferences.default_hotkey = hotkey_name
            self.preferences.save()
            return ConversationResponse(
                message=f"Got it! Updated hotkey to **{hotkey_name}**.",
                action=ResponseAction.DISPLAY,
            )

        # Match "my wallet is X" or "wallet is X" or "use wallet X"
        wallet_match = re.search(
            r"(?:my\s+)?wallet\s+(?:is|should be|=)\s*(\w+)|"
            r"(?:use|switch to|default|set|change)\s+(?:my\s+)?(?:wallet\s+)?(?:to\s+)?(\w+)",
            text,
        )
        if wallet_match:
            wallet_name = wallet_match.group(1) or wallet_match.group(2)
            self.preferences.default_wallet = wallet_name
            self.preferences.save()
            return ConversationResponse(
                message=f"Got it! Updated wallet to **{wallet_name}**.",
                action=ResponseAction.DISPLAY,
            )

        # Match "default subnet X" or "use subnet X"
        subnet_match = re.search(r"(?:use|default)\s+(?:subnet\s+)?(\d+)", text)
        if subnet_match:
            netuid = int(subnet_match.group(1))
            self.preferences.default_netuid = netuid
            self.preferences.save()
            return ConversationResponse(
                message=f"Got it! Default subnet set to **{netuid}**.",
                action=ResponseAction.DISPLAY,
            )

        return ConversationResponse(
            message="I can set defaults for you. Try: 'my hotkey is name' or 'use wallet name'",
            action=ResponseAction.DISPLAY,
        )

    def _get_help_text(self) -> str:
        """Get help text."""
        return """**I can help you with:**

**Queries:**
• "what's my balance?" - Check TAO balance
• "show my portfolio" - View stake positions
• "show validators on subnet 1" - List validators
• "list subnets" - Show all subnets
• "view transaction history" - Recent transactions

**Transactions:**
• "stake 10 TAO to Taostats on subnet 1"
• "unstake 5 TAO from OpenTensor"
• "transfer 20 TAO to 5xxx..."
• "register on subnet 18"

**Defaults:**
• "use wallet myname from now on"
• "default subnet 1"

**Other:**
• "cancel" - Cancel current action
• "clear" - Clear conversation
• "quit" - Exit chat"""

    def _reset(self) -> None:
        """Reset to idle state."""
        self.state = ConversationState.IDLE
        self.pending_action = None


# =============================================================================
# Response Types
# =============================================================================


class ResponseAction(str, Enum):
    """Type of action the CLI should take."""

    DISPLAY = "display"  # Just display the message
    ASK = "ask"  # Display message and wait for input (slot-filling)
    CONFIRM = "confirm"  # Display confirmation prompt
    EXECUTE = "execute"  # Execute the intent
    SUGGEST = "suggest"  # Show follow-up suggestions


@dataclass
class ConversationResponse:
    """Response from the conversation engine."""

    message: str
    action: ResponseAction
    intent: Optional[ParsedIntent] = None
    slot_being_filled: Optional[SlotType] = None
    suggestions: list[str] = field(default_factory=list)
