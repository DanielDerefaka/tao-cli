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
from typing import Any, Optional

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
    METAGRAPH = "metagraph"
    PRICE = "price"

    # Registration
    REGISTER = "register"

    # History
    HISTORY = "history"

    # Config
    SET_CONFIG = "set_config"

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


class LLMResponse(BaseModel):
    """Structured response from LLM interpreter."""

    intent: IntentType
    slots: Slots = Field(default_factory=Slots)
    reply: str  # Natural language response to show user
    needs_confirmation: bool = False
    missing_info: Optional[str] = None  # What info is still needed
    ready_to_execute: bool = False  # All required slots filled


# System prompt that makes the LLM understand its role
# Note: Double braces {{ }} are escaped for Python .format() - they become single braces in output
SYSTEM_PROMPT = """You are taox, an AI assistant for Bittensor. You help users manage their TAO - checking balances, staking, transfers, and more.

IMPORTANT RULES:
1. Be conversational and friendly, but concise (1-3 sentences)
2. ALWAYS respond with valid JSON matching the schema below
3. Extract intent and slots from user messages
4. If info is missing, ask ONE clarifying question in your reply
5. Never ask for seed phrases or private keys
6. Use τ symbol for TAO amounts

YOUR CAPABILITIES:
- balance: Check wallet balance
- portfolio: Show stake positions
- stake: Stake TAO to validators
- unstake: Remove stake
- transfer: Send TAO to addresses
- validators: List top validators
- subnets: List subnets
- metagraph: Show subnet metagraph
- price: Current TAO price
- register: Register on subnet
- history: Transaction history
- set_config: Update settings (hotkey, wallet)
- help: Show help
- greeting: Respond to greetings
- conversation: General Bittensor chat
- unclear: Need more info

JSON SCHEMA (respond with ONLY this JSON, no markdown):
{{
  "intent": "<intent_type>",
  "slots": {{
    "amount": <number or null>,
    "amount_all": <boolean>,
    "validator_name": "<string or null>",
    "validator_hotkey": "<string or null>",
    "netuid": <number or null>,
    "destination": "<ss58 address or null>",
    "wallet_name": "<string or null>",
    "hotkey_name": "<string or null>",
    "config_key": "<string or null>",
    "config_value": "<string or null>"
  }},
  "reply": "<your conversational response>",
  "needs_confirmation": <boolean - true for transactions>,
  "missing_info": "<what's missing, or null>",
  "ready_to_execute": <boolean - true if all required slots filled>
}}

EXAMPLES:

User: "hey whats good"
{{"intent": "greeting", "slots": {{}}, "reply": "Hey! Ready to help with your TAO. What do you need?", "needs_confirmation": false, "missing_info": null, "ready_to_execute": false}}

User: "stake 10 tao to taostats on subnet 1"
{{"intent": "stake", "slots": {{"amount": 10, "validator_name": "taostats", "netuid": 1}}, "reply": "Got it! Stake 10 τ to Taostats on SN1. Confirm?", "needs_confirmation": true, "missing_info": null, "ready_to_execute": true}}

User: "i want to stake some tao"
{{"intent": "stake", "slots": {{}}, "reply": "Sure! How much TAO and to which validator?", "needs_confirmation": false, "missing_info": "amount and validator", "ready_to_execute": false}}

User: "my hotkey is dx_hot"
{{"intent": "set_config", "slots": {{"config_key": "hotkey", "config_value": "dx_hot"}}, "reply": "Got it! Updated hotkey to dx_hot.", "needs_confirmation": false, "missing_info": null, "ready_to_execute": true}}

User: "how much tao do i have"
{{"intent": "balance", "slots": {{}}, "reply": "Let me check your balance.", "needs_confirmation": false, "missing_info": null, "ready_to_execute": true}}

User: "what is bittensor"
{{"intent": "conversation", "slots": {{}}, "reply": "Bittensor is a decentralized AI network where miners contribute compute and validators ensure quality. TAO is its native token.", "needs_confirmation": false, "missing_info": null, "ready_to_execute": false}}

CURRENT CONTEXT:
Wallet: {wallet}
Hotkey: {hotkey}
Network: {network}
"""


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
                messages.append({
                    "role": "assistant",
                    "content": json.dumps(self._pending_intent.model_dump()),
                })

            messages.append({"role": "user", "content": user_input})

            response = client.chat.completions.create(
                model=self.settings.llm.model,
                messages=messages,
                temperature=self.settings.llm.temperature,
                max_tokens=self.settings.llm.max_tokens,
            )

            content = response.choices[0].message.content
            if content is None:
                logger.warning("LLM returned empty content")
                return self._fallback_interpret(user_input)

            content = content.strip()
            logger.debug(f"LLM raw response (first 300 chars): {content[:300]}")

            # Check if response looks incomplete
            if len(content) < 20 or ('"intent"' in content and "}" not in content):
                logger.warning(f"LLM response appears truncated: {content[:100]}")
                return self._fallback_interpret(user_input)

            return self._parse_response(content, user_input)

        except Exception as e:
            logger.warning(f"LLM interpret failed: {type(e).__name__}: {e}")
            return self._fallback_interpret(user_input)

    def _parse_response(self, content: str, original_input: str) -> LLMResponse:
        """Parse and validate LLM response."""
        import re

        original_content = content  # Keep for debugging

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
                if slots.get("amount") is not None:
                    try:
                        slots["amount"] = float(slots["amount"])
                    except (ValueError, TypeError):
                        pass
                if slots.get("netuid") is not None:
                    try:
                        slots["netuid"] = int(slots["netuid"])
                    except (ValueError, TypeError):
                        pass

            response = LLMResponse(**data)

            # Track pending intent for multi-turn
            if response.missing_info and not response.ready_to_execute:
                self._pending_intent = response
            else:
                self._pending_intent = None

            return response

        except (json.JSONDecodeError, ValidationError, KeyError, TypeError) as e:
            logger.warning(f"Failed to parse LLM response: {type(e).__name__}: {e}")
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
            OldIntent.METAGRAPH: IntentType.METAGRAPH,
            OldIntent.REGISTER: IntentType.REGISTER,
            OldIntent.HISTORY: IntentType.HISTORY,
            OldIntent.SET_CONFIG: IntentType.SET_CONFIG,
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
        )

        # Generate reply based on intent
        replies = {
            IntentType.BALANCE: "Checking your balance...",
            IntentType.PORTFOLIO: "Loading your portfolio...",
            IntentType.STAKE: f"Staking {slots.amount or '?'} τ...",
            IntentType.VALIDATORS: "Fetching validators...",
            IntentType.SUBNETS: "Loading subnets...",
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
        )

        # For transactions, check if we have required slots
        if intent == IntentType.STAKE:
            ready = slots.amount is not None and slots.validator_name is not None
        elif intent == IntentType.TRANSFER:
            ready = slots.amount is not None and slots.destination is not None
        elif intent == IntentType.REGISTER:
            ready = slots.netuid is not None

        return LLMResponse(
            intent=intent,
            slots=slots,
            reply=reply,
            needs_confirmation=intent in (IntentType.STAKE, IntentType.UNSTAKE, IntentType.TRANSFER, IntentType.REGISTER),
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
