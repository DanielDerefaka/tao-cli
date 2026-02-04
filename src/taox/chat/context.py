"""Conversation context management for taox.

This module manages:
- Message history for context-aware responses
- Integration with the conversation state machine
- Session state (wallet, network)
- Follow-up command resolution
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from collections import deque

from taox.chat.intents import Intent, IntentType

if TYPE_CHECKING:
    from taox.chat.state_machine import ConversationEngine, ParsedIntent


@dataclass
class Message:
    """Represents a single message in the conversation."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    intent: Optional[Intent] = None


@dataclass
class ConversationContext:
    """Maintains conversation state and history.

    Tracks:
    - Recent messages for context-aware responses
    - Current wallet and network settings
    - Recent operations for follow-up commands
    - Integration with ConversationEngine for state machine
    """

    # Message history (limited to avoid memory issues)
    history: deque = field(default_factory=lambda: deque(maxlen=20))

    # Current session state
    current_wallet: Optional[str] = None
    current_hotkey: Optional[str] = None
    current_network: str = "finney"

    # Last operation context (for follow-ups like "do the same for subnet 18")
    last_intent: Optional[Intent] = None
    last_validator: Optional[str] = None
    last_netuid: Optional[int] = None
    last_amount: Optional[float] = None

    # State machine reference (set after initialization)
    _engine: Optional["ConversationEngine"] = None

    def set_engine(self, engine: "ConversationEngine") -> None:
        """Set the conversation engine reference.

        Args:
            engine: ConversationEngine instance
        """
        self._engine = engine

        # Sync engine preferences with context
        if engine.preferences.default_wallet:
            self.current_wallet = engine.preferences.default_wallet
        if engine.preferences.default_hotkey:
            self.current_hotkey = engine.preferences.default_hotkey
        if engine.preferences.default_network:
            self.current_network = engine.preferences.default_network

    @property
    def engine(self) -> Optional["ConversationEngine"]:
        """Get the conversation engine."""
        return self._engine

    def add_user_message(self, content: str, intent: Optional[Intent] = None) -> None:
        """Add a user message to the history.

        Args:
            content: The user's message
            intent: Parsed intent (if available)
        """
        self.history.append(
            Message(role="user", content=content, intent=intent)
        )

        # Update last operation context if intent provided
        if intent:
            self.last_intent = intent
            if intent.validator_name:
                self.last_validator = intent.validator_name
            if intent.netuid is not None:
                self.last_netuid = intent.netuid
            if intent.amount is not None:
                self.last_amount = intent.amount

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message to the history.

        Args:
            content: The assistant's response
        """
        self.history.append(Message(role="assistant", content=content))

    def get_recent_history(self, n: int = 10) -> list[Message]:
        """Get the n most recent messages.

        Args:
            n: Number of messages to return

        Returns:
            List of recent Message objects
        """
        return list(self.history)[-n:]

    def get_history_for_llm(self, n: int = 10) -> list[dict]:
        """Get history formatted for LLM API calls.

        Ensures the history starts with a user message and maintains
        proper user/assistant alternation for LLM APIs.

        Args:
            n: Number of messages to include

        Returns:
            List of dicts with 'role' and 'content' keys
        """
        recent = self.get_recent_history(n)

        # Ensure history starts with a user message (LLM API requirement)
        # If truncation caused us to start with assistant, skip it
        while recent and recent[0].role == "assistant":
            recent = recent[1:]

        # Also ensure alternation - remove any consecutive messages of same role
        if len(recent) > 1:
            cleaned = [recent[0]]
            for msg in recent[1:]:
                if msg.role != cleaned[-1].role:
                    cleaned.append(msg)
                # If same role, skip the duplicate (keep the earlier one)
            recent = cleaned

        return [
            {"role": msg.role, "content": msg.content}
            for msg in recent
        ]

    def resolve_follow_up(self, intent: Intent) -> Intent:
        """Resolve follow-up references using conversation context.

        Handles phrases like:
        - "do the same for subnet 18" -> uses last operation with new netuid
        - "stake 50 more" -> uses last validator/netuid
        - "to the same validator" -> uses last validator

        Args:
            intent: The newly parsed intent

        Returns:
            Intent with resolved references
        """
        # If netuid not specified but we have a last netuid, use it for certain intents
        if intent.netuid is None and self.last_netuid is not None:
            if intent.type in (IntentType.STAKE, IntentType.UNSTAKE, IntentType.METAGRAPH):
                intent.netuid = self.last_netuid

        # If validator not specified but we have a last validator
        if intent.validator_name is None and self.last_validator is not None:
            if intent.type == IntentType.STAKE:
                intent.validator_name = self.last_validator

        # Set wallet context if not specified
        if intent.wallet_name is None and self.current_wallet:
            intent.wallet_name = self.current_wallet

        return intent

    def set_wallet(self, wallet_name: str, hotkey_name: Optional[str] = None) -> None:
        """Set the current wallet context.

        Args:
            wallet_name: Name of the wallet
            hotkey_name: Name of the hotkey (optional)
        """
        self.current_wallet = wallet_name
        if hotkey_name:
            self.current_hotkey = hotkey_name

        # Sync with engine if available
        if self._engine:
            self._engine.preferences.default_wallet = wallet_name
            if hotkey_name:
                self._engine.preferences.default_hotkey = hotkey_name
            self._engine.preferences.save()

    def set_network(self, network: str) -> None:
        """Set the current network.

        Args:
            network: Network name (finney, test, local)
        """
        self.current_network = network

        # Sync with engine if available
        if self._engine:
            self._engine.preferences.default_network = network
            self._engine.preferences.save()

    def set_default_netuid(self, netuid: int) -> None:
        """Set the default subnet ID.

        Args:
            netuid: Subnet ID
        """
        self.last_netuid = netuid

        # Sync with engine if available
        if self._engine:
            self._engine.preferences.default_netuid = netuid
            self._engine.preferences.save()

    def clear(self) -> None:
        """Clear conversation history but keep wallet/network settings."""
        self.history.clear()
        self.last_intent = None
        self.last_validator = None
        self.last_netuid = None
        self.last_amount = None

        # Reset engine state if available
        if self._engine:
            self._engine._reset()

    def get_context_summary(self) -> str:
        """Get a summary of current context for LLM system prompt.

        Returns:
            String summary of current context
        """
        parts = []

        if self.current_wallet:
            parts.append(f"Active wallet: {self.current_wallet}")
        if self.current_hotkey:
            parts.append(f"Active hotkey: {self.current_hotkey}")
        parts.append(f"Network: {self.current_network}")

        if self.last_intent:
            parts.append(f"Last action: {self.last_intent.type.value}")
        if self.last_validator:
            parts.append(f"Last validator: {self.last_validator}")
        if self.last_netuid is not None:
            parts.append(f"Last subnet: {self.last_netuid}")

        # Add engine state if available
        if self._engine:
            from taox.chat.state_machine import ConversationState
            if self._engine.state != ConversationState.IDLE:
                parts.append(f"State: {self._engine.state.value}")
            if self._engine.pending_action:
                parts.append(f"Pending: {self._engine.pending_action.intent.type.value}")

        return "\n".join(parts)

    def get_state_prompt(self) -> Optional[str]:
        """Get any prompt from the current state machine state.

        Returns:
            Prompt string if in slot-filling or confirmation state, None otherwise
        """
        if self._engine:
            return self._engine.get_state_prompt()
        return None

    def get_follow_up_suggestions(self) -> list[str]:
        """Get suggested follow-up actions.

        Returns:
            List of suggested actions
        """
        if self._engine:
            return self._engine.get_follow_up_suggestions()
        return []
