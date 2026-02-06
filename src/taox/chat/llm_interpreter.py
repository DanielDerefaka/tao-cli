"""LLM Interpreter - The brain of taox.

This module implements LLM-first intent understanding where the LLM is always
the primary decision maker, not a fallback. It orchestrates:
- Intent classification
- Slot extraction
- Conversational responses
- Tool/API calls (taostats, btcli)
"""

import json
import logging
from enum import Enum
from typing import Optional

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from taox.config.settings import get_settings
from taox.security.credentials import CredentialManager

logger = logging.getLogger(__name__)


class IntentType(str, Enum):
    """All supported intents."""

    # Wallet operations
    BALANCE = "balance"
    PORTFOLIO = "portfolio"
    TRANSFER = "transfer"

    # Staking
    STAKE = "stake"
    UNSTAKE = "unstake"

    # Network info
    VALIDATORS = "validators"
    SUBNETS = "subnets"
    SUBNET_INFO = "subnet_info"
    METAGRAPH = "metagraph"
    PRICE = "price"

    # Registration
    REGISTER = "register"

    # History
    HISTORY = "history"

    # Config
    SET_CONFIG = "set_config"

    # Diagnostics & tools
    DOCTOR = "doctor"
    PORTFOLIO_DELTA = "portfolio_delta"
    RECOMMEND = "recommend"
    WATCH = "watch"
    REBALANCE = "rebalance"

    # Meta
    HELP = "help"
    GREETING = "greeting"
    CONVERSATION = "conversation"  # General chat about Bittensor
    UNCLEAR = "unclear"  # Need clarification


class Slots(BaseModel):
    """Extracted slots from user input."""

    amount: Optional[float] = None
    amount_all: bool = False
    validator_name: Optional[str] = None
    validator_hotkey: Optional[str] = None
    netuid: Optional[int] = None
    destination: Optional[str] = None
    wallet_name: Optional[str] = None
    hotkey_name: Optional[str] = None
    config_key: Optional[str] = None  # For SET_CONFIG
    config_value: Optional[str] = None
    price_only: bool = False  # For SUBNET_INFO: show price only vs full details
    days: Optional[int] = None  # For PORTFOLIO_DELTA: number of days to compare


class LLMResponse(BaseModel):
    """Structured response from LLM interpreter."""

    intent: IntentType
    slots: Slots = Field(default_factory=Slots)
    reply: str  # Natural language response to show user
    needs_confirmation: bool = False
    missing_info: Optional[str] = None  # What info is still needed
    ready_to_execute: bool = False  # All required slots filled


# Import the comprehensive prompt from prompts module
from taox.chat.prompts import SYSTEM_PROMPT


class LLMInterpreter:
    """LLM-first interpreter for taox commands."""

    def __init__(self):
        """Initialize the interpreter."""
        self.settings = get_settings()
        self._client: Optional[OpenAI] = None
        self._pending_intent: Optional[LLMResponse] = None

    @property
    def api_key(self) -> Optional[str]:
        """Get Chutes API key."""
        return CredentialManager.get_chutes_key()

    @property
    def is_available(self) -> bool:
        """Check if LLM is available."""
        return (
            self.api_key is not None
            and self.settings.llm.mode != "off"
            and not self.settings.demo_mode
        )

    def _get_client(self) -> OpenAI:
        """Get or create OpenAI client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("No Chutes API key")
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.settings.llm.base_url,
            )
        return self._client

    def interpret(
        self,
        user_input: str,
        wallet: str = "default",
        hotkey: str = "default",
        network: str = "finney",
    ) -> LLMResponse:
        """Interpret user input and return structured response.

        Args:
            user_input: What the user said
            wallet: Current wallet name
            hotkey: Current hotkey name
            network: Current network

        Returns:
            Structured LLMResponse with intent, slots, and reply
        """
        if not self.is_available:
            return self._fallback_interpret(user_input)

        try:
            client = self._get_client()

            # Build context-aware system prompt
            system = SYSTEM_PROMPT.format(
                wallet=wallet,
                hotkey=hotkey,
                network=network,
            )

            # If we have a pending intent, include context
            messages = [{"role": "system", "content": system}]

            if self._pending_intent:
                # Add context about what we're waiting for
                messages.append(
                    {
                        "role": "assistant",
                        "content": json.dumps(self._pending_intent.model_dump()),
                    }
                )

            messages.append({"role": "user", "content": user_input})

            response = client.chat.completions.create(
                model=self.settings.llm.model,
                messages=messages,
                temperature=self.settings.llm.temperature,
                max_tokens=self.settings.llm.max_tokens,
            )

            content = response.choices[0].message.content
            if content is None:
                logger.debug("LLM returned empty content")
                return self._fallback_interpret(user_input)

            content = content.strip()
            logger.debug(f"LLM raw response (first 300 chars): {content[:300]}")

            # Check if response looks incomplete
            if len(content) < 20 or ('"intent"' in content and "}" not in content):
                logger.debug(f"LLM response appears truncated: {content[:100]}")
                return self._fallback_interpret(user_input)

            return self._parse_response(content, user_input)

        except Exception as e:
            logger.debug(f"LLM interpret failed: {type(e).__name__}: {e}")
            return self._fallback_interpret(user_input)

    def _parse_response(self, content: str, original_input: str) -> LLMResponse:
        """Parse and validate LLM response."""
        import re

        # Strip markdown code blocks if present
        if "```" in content:
            # Extract content between code blocks
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if match:
                content = match.group(1).strip()
            else:
                # Just remove the markers
                content = content.replace("```json", "").replace("```", "").strip()

        # Try to find JSON object in the content
        # Look for content between { and }
        if "{" in content:
            start = content.find("{")
            # Find matching closing brace
            brace_count = 0
            end = start
            for i, char in enumerate(content[start:], start):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end = i + 1
                        break
            if end > start:
                content = content[start:end]
        elif '"intent"' in content:
            # LLM returned JSON without braces - try to wrap it
            content = "{" + content.strip()
            if not content.endswith("}"):
                content += "}"

        content = content.strip()

        try:
            data = json.loads(content)

            # Ensure slots values are properly typed
            if "slots" in data and isinstance(data["slots"], dict):
                slots = data["slots"]
                # Convert string numbers to float/int
                import contextlib

                if slots.get("amount") is not None:
                    with contextlib.suppress(ValueError, TypeError):
                        slots["amount"] = float(slots["amount"])
                if slots.get("netuid") is not None:
                    with contextlib.suppress(ValueError, TypeError):
                        slots["netuid"] = int(slots["netuid"])
                if slots.get("days") is not None:
                    with contextlib.suppress(ValueError, TypeError):
                        slots["days"] = int(slots["days"])

            response = LLMResponse(**data)

            # Track pending intent for multi-turn
            if response.missing_info and not response.ready_to_execute:
                self._pending_intent = response
            else:
                self._pending_intent = None

            return response

        except (json.JSONDecodeError, ValidationError, KeyError, TypeError) as e:
            logger.debug(f"Failed to parse LLM response: {type(e).__name__}: {e}")
            logger.debug(f"Content to parse: {content[:300]}")
            # Return a safe fallback
            return LLMResponse(
                intent=IntentType.UNCLEAR,
                reply="I didn't quite catch that. Could you rephrase?",
                ready_to_execute=False,
            )

    def _fallback_interpret(self, user_input: str) -> LLMResponse:
        """Fallback to pattern matching when LLM unavailable."""
        from taox.chat.intents import IntentType as OldIntent
        from taox.chat.intents import MockIntentParser

        old_intent = MockIntentParser.parse(user_input)

        # Map old intent to new
        intent_map = {
            OldIntent.BALANCE: IntentType.BALANCE,
            OldIntent.PORTFOLIO: IntentType.PORTFOLIO,
            OldIntent.STAKE: IntentType.STAKE,
            OldIntent.UNSTAKE: IntentType.UNSTAKE,
            OldIntent.TRANSFER: IntentType.TRANSFER,
            OldIntent.VALIDATORS: IntentType.VALIDATORS,
            OldIntent.SUBNETS: IntentType.SUBNETS,
            OldIntent.SUBNET_INFO: IntentType.SUBNET_INFO,
            OldIntent.METAGRAPH: IntentType.METAGRAPH,
            OldIntent.REGISTER: IntentType.REGISTER,
            OldIntent.PRICE: IntentType.PRICE,
            OldIntent.HISTORY: IntentType.HISTORY,
            OldIntent.SET_CONFIG: IntentType.SET_CONFIG,
            OldIntent.DOCTOR: IntentType.DOCTOR,
            OldIntent.PORTFOLIO_DELTA: IntentType.PORTFOLIO_DELTA,
            OldIntent.RECOMMEND: IntentType.RECOMMEND,
            OldIntent.WATCH: IntentType.WATCH,
            OldIntent.REBALANCE: IntentType.REBALANCE,
            OldIntent.HELP: IntentType.HELP,
            OldIntent.GREETING: IntentType.GREETING,
            OldIntent.UNKNOWN: IntentType.UNCLEAR,
        }

        intent = intent_map.get(old_intent.type, IntentType.UNCLEAR)

        # Build slots
        slots = Slots(
            amount=old_intent.amount,
            amount_all=old_intent.amount_all,
            validator_name=old_intent.validator_name,
            validator_hotkey=old_intent.validator_ss58,
            netuid=old_intent.netuid,
            destination=old_intent.destination,
            wallet_name=old_intent.wallet_name,
            hotkey_name=old_intent.hotkey_name,
            config_key=old_intent.extra.get("config_key"),
            config_value=old_intent.extra.get("config_value"),
            price_only=old_intent.extra.get("price_only", False),
            days=old_intent.extra.get("days"),
        )

        # Generate SET_CONFIG reply
        if intent == IntentType.SET_CONFIG and slots.config_key and slots.config_value:
            config_label = "wallet" if slots.config_key == "wallet" else "hotkey"
            set_config_reply = f"Updated {config_label} to {slots.config_value}."
        else:
            set_config_reply = "What setting would you like to change? (e.g. 'my wallet is dx')"

        # Generate reply based on intent
        replies = {
            IntentType.BALANCE: "Checking your balance...",
            IntentType.PORTFOLIO: "Loading your portfolio...",
            IntentType.PRICE: "Fetching TAO price...",
            IntentType.STAKE: f"Staking {slots.amount or '?'} τ...",
            IntentType.VALIDATORS: "Fetching validators...",
            IntentType.SUBNETS: "Loading subnets...",
            IntentType.SUBNET_INFO: (
                f"Fetching subnet {slots.netuid} info..."
                if slots.netuid
                else "Which subnet? (e.g. 'sn 1' or 'subnet 64')"
            ),
            IntentType.METAGRAPH: "Loading metagraph...",
            IntentType.HISTORY: "Loading transaction history...",
            IntentType.REGISTER: "Register on subnet "
            + (
                str(slots.netuid)
                if slots.netuid
                else "— which subnet? (e.g. 'register on subnet 1')"
            ),
            IntentType.TRANSFER: "Transfer — specify amount and destination address.",
            IntentType.SET_CONFIG: set_config_reply,
            IntentType.DOCTOR: "Running environment check...",
            IntentType.PORTFOLIO_DELTA: f"Checking portfolio changes over {slots.days or 7} days...",
            IntentType.RECOMMEND: (
                f"Finding best validators for {slots.amount} τ..."
                if slots.amount
                else "How much TAO would you like staking recommendations for?"
            ),
            IntentType.WATCH: "Setting up monitoring...",
            IntentType.REBALANCE: (
                f"Planning rebalance for {slots.amount} τ..."
                if slots.amount
                else "How much TAO to rebalance across validators?"
            ),
            IntentType.GREETING: "Hey! What can I help you with?",
            IntentType.HELP: "Here's what I can do...",
            IntentType.UNCLEAR: "Not sure what you mean. Try 'help' for options.",
        }

        reply = replies.get(intent, "Processing...")

        # Determine if ready to execute
        ready = intent in (
            IntentType.BALANCE,
            IntentType.PORTFOLIO,
            IntentType.VALIDATORS,
            IntentType.SUBNETS,
            IntentType.PRICE,
            IntentType.HELP,
            IntentType.GREETING,
            IntentType.HISTORY,
            IntentType.METAGRAPH,
            IntentType.CONVERSATION,
            IntentType.DOCTOR,
            IntentType.PORTFOLIO_DELTA,
            IntentType.WATCH,
        )

        # For transactions, check if we have required slots
        if intent == IntentType.STAKE:
            ready = slots.amount is not None and slots.validator_name is not None
        elif intent == IntentType.TRANSFER:
            ready = slots.amount is not None and slots.destination is not None
        elif intent == IntentType.REGISTER or intent == IntentType.SUBNET_INFO:
            ready = slots.netuid is not None
        elif intent == IntentType.SET_CONFIG:
            ready = slots.config_key is not None and slots.config_value is not None
        elif intent in (IntentType.RECOMMEND, IntentType.REBALANCE):
            ready = slots.amount is not None

        # If not ready, adjust reply to prompt for missing info
        if not ready and intent not in (IntentType.UNCLEAR, IntentType.GREETING, IntentType.HELP):
            reply = replies.get(intent, "I need more details. Try 'help' for examples.")

        return LLMResponse(
            intent=intent,
            slots=slots,
            reply=reply,
            needs_confirmation=intent
            in (
                IntentType.STAKE,
                IntentType.UNSTAKE,
                IntentType.TRANSFER,
                IntentType.REGISTER,
                IntentType.REBALANCE,
            ),
            ready_to_execute=ready,
        )

    def clear_pending(self):
        """Clear any pending multi-turn context."""
        self._pending_intent = None


# Singleton instance
_interpreter: Optional[LLMInterpreter] = None


def get_interpreter() -> LLMInterpreter:
    """Get the global interpreter instance."""
    global _interpreter
    if _interpreter is None:
        _interpreter = LLMInterpreter()
    return _interpreter
