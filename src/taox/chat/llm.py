"""LLM client for Chutes AI integration."""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Optional

from openai import AsyncOpenAI, OpenAI

from taox.chat.context import ConversationContext
from taox.chat.intents import Intent, IntentType, MockIntentParser
from taox.config.settings import get_settings
from taox.security.credentials import CredentialManager

logger = logging.getLogger(__name__)


# System prompt for intent classification (outputs structured JSON)
INTENT_SYSTEM_PROMPT = """You are taox, a Bittensor wallet assistant. Output ONLY valid JSON matching the schema below.

RULES:
- Never request seed phrases or private keys
- If information is missing, set fields to null and add a question in "clarifying_question"
- If the user asks to execute a transaction, set "requires_confirmation": true
- Extract amounts in TAO (not rao)
- Recognize common validators by name (Taostats, OpenTensor Foundation, etc.)

SCHEMA:
{{
  "intent": "BALANCE" | "PORTFOLIO" | "STAKE" | "UNSTAKE" | "TRANSFER" | "REGISTER" | "VALIDATORS" | "SUBNETS" | "METAGRAPH" | "HISTORY" | "HELP" | "INFO",
  "slots": {{
    "wallet_name": string | null,
    "hotkey": string | null,
    "network": "finney" | "test" | "local" | null,
    "netuid": number | null,
    "validator": string | null,
    "amount": number | null,
    "amount_all": boolean,
    "asset": "TAO" | "ALPHA" | null,
    "destination": string | null,
    "safety": "safe" | "partial" | "unsafe" | null
  }},
  "requires_confirmation": boolean,
  "clarifying_question": string | null
}}

EXAMPLES:
User: "stake 10 TAO to Taostats on subnet 1"
{{"intent": "STAKE", "slots": {{"amount": 10, "amount_all": false, "validator": "Taostats", "netuid": 1, "asset": "TAO"}}, "requires_confirmation": true, "clarifying_question": null}}

User: "what's my balance"
{{"intent": "BALANCE", "slots": {{}}, "requires_confirmation": false, "clarifying_question": null}}

User: "stake some TAO"
{{"intent": "STAKE", "slots": {{"amount_all": false}}, "requires_confirmation": true, "clarifying_question": "How much TAO would you like to stake, and to which validator?"}}

Current context:
{context}

Respond with ONLY the JSON object."""


# System prompt for conversational responses
CHAT_SYSTEM_PROMPT = """You are taox, an AI assistant for Bittensor. Be concise and helpful.

IMPORTANT RULES:
- Give SHORT responses (1-3 sentences max)
- NEVER repeat yourself or ask the same question twice
- Remember the conversation history - don't ask for info already provided
- When user confirms with "yes/ok/confirm", acknowledge and proceed
- Use τ for TAO amounts
- Keep addresses short: first 8...last 4 chars (e.g., 5FFApaS7...52v)
- Don't show raw btcli commands unless asked
- If a transaction was executed, include: what was attempted, status, tx hash if available
- For errors, provide: likely cause, 2-3 next steps

Current session:
{context}"""


# System prompt for error interpretation
ERROR_INTERPRETER_PROMPT = """You are taox. Interpret this btcli/subtensor error for a developer and for a user.

Return JSON with:
{{
  "user_explanation": "Brief explanation for non-technical user",
  "likely_causes": ["cause 1", "cause 2"],
  "next_steps": ["step 1", "step 2"],
  "safe_to_retry": boolean,
  "wait_time": "immediately" | "X seconds" | "X minutes" | null
}}

ERROR:
{error}

CONTEXT:
Intent: {intent}
Slots: {slots}

Respond with ONLY the JSON object."""


class LLMClient:
    """Client for LLM interactions via Chutes API (OpenAI-compatible)."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the LLM client.

        Args:
            api_key: Chutes API key (if not provided, will try to get from keyring)
        """
        self.settings = get_settings()
        self._api_key = api_key
        self._client: Optional[OpenAI] = None
        self._async_client: Optional[AsyncOpenAI] = None

    @property
    def api_key(self) -> Optional[str]:
        """Get the API key from provided value or keyring."""
        if self._api_key:
            return self._api_key
        return CredentialManager.get_chutes_key()

    @property
    def is_available(self) -> bool:
        """Check if LLM is available (has API key)."""
        return self.api_key is not None and not self.settings.demo_mode

    def _get_client(self) -> OpenAI:
        """Get or create the sync OpenAI client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("No Chutes API key available")
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.settings.llm.base_url,
            )
        return self._client

    def _get_async_client(self) -> AsyncOpenAI:
        """Get or create the async OpenAI client."""
        if self._async_client is None:
            if not self.api_key:
                raise ValueError("No Chutes API key available")
            self._async_client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.settings.llm.base_url,
            )
        return self._async_client

    def parse_intent(self, user_input: str, context: ConversationContext) -> Intent:
        """Parse user input into an Intent using LLM.

        Falls back to mock parser if LLM is unavailable.

        Args:
            user_input: Raw user input string
            context: Current conversation context

        Returns:
            Parsed Intent object
        """
        if not self.is_available:
            logger.debug("LLM not available, using mock parser")
            return MockIntentParser.parse(user_input)

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.settings.llm.model,
                messages=[
                    {
                        "role": "system",
                        "content": INTENT_SYSTEM_PROMPT.format(
                            context=context.get_context_summary()
                        ),
                    },
                    {"role": "user", "content": user_input},
                ],
                temperature=0.1,  # Very low temperature for structured output
                max_tokens=500,
            )

            # Parse JSON response
            content = response.choices[0].message.content.strip()

            # Try to extract JSON if wrapped in markdown code blocks
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            data = json.loads(content)

            # Handle new schema with "slots" nested object
            slots = data.get("slots", {})

            # Map to Intent object
            intent_type = IntentType(data.get("intent", "unknown").lower())

            # Extract from slots (new schema) or top-level (old schema for backwards compat)
            return Intent(
                type=intent_type,
                raw_input=user_input,
                confidence=0.95,
                amount=slots.get("amount") or data.get("amount"),
                amount_all=slots.get("amount_all", False) or data.get("amount_all", False),
                validator_name=slots.get("validator") or data.get("validator_name"),
                validator_ss58=data.get("validator_ss58"),
                netuid=slots.get("netuid") or data.get("netuid"),
                destination=slots.get("destination") or data.get("destination"),
                wallet_name=slots.get("wallet_name") or data.get("wallet_name"),
                extra={
                    "requires_confirmation": data.get("requires_confirmation", False),
                    "clarifying_question": data.get("clarifying_question"),
                    "safety": slots.get("safety"),
                    "asset": slots.get("asset"),
                },
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            return MockIntentParser.parse(user_input)
        except Exception as e:
            logger.warning(f"LLM parsing failed, using mock parser: {e}")
            return MockIntentParser.parse(user_input)

    async def parse_intent_async(self, user_input: str, context: ConversationContext) -> Intent:
        """Async version of parse_intent.

        Args:
            user_input: Raw user input string
            context: Current conversation context

        Returns:
            Parsed Intent object
        """
        if not self.is_available:
            return MockIntentParser.parse(user_input)

        try:
            client = self._get_async_client()
            response = await client.chat.completions.create(
                model=self.settings.llm.model,
                messages=[
                    {
                        "role": "system",
                        "content": INTENT_SYSTEM_PROMPT.format(
                            context=context.get_context_summary()
                        ),
                    },
                    {"role": "user", "content": user_input},
                ],
                temperature=0.1,
                max_tokens=500,
            )

            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            data = json.loads(content)
            slots = data.get("slots", {})
            intent_type = IntentType(data.get("intent", "unknown").lower())

            return Intent(
                type=intent_type,
                raw_input=user_input,
                confidence=0.95,
                amount=slots.get("amount") or data.get("amount"),
                amount_all=slots.get("amount_all", False) or data.get("amount_all", False),
                validator_name=slots.get("validator") or data.get("validator_name"),
                validator_ss58=data.get("validator_ss58"),
                netuid=slots.get("netuid") or data.get("netuid"),
                destination=slots.get("destination") or data.get("destination"),
                wallet_name=slots.get("wallet_name") or data.get("wallet_name"),
                extra={
                    "requires_confirmation": data.get("requires_confirmation", False),
                    "clarifying_question": data.get("clarifying_question"),
                    "safety": slots.get("safety"),
                    "asset": slots.get("asset"),
                },
            )

        except Exception as e:
            logger.warning(f"Async LLM parsing failed: {e}")
            return MockIntentParser.parse(user_input)

    def interpret_error(self, error: str, intent: Optional[Intent] = None) -> dict:
        """Interpret a btcli/subtensor error using LLM.

        Args:
            error: The error message (stderr + stdout)
            intent: The intent that caused the error (optional)

        Returns:
            Dict with user_explanation, likely_causes, next_steps, safe_to_retry, wait_time
        """
        if not self.is_available:
            return self._mock_error_interpretation(error)

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.settings.llm.model,
                messages=[
                    {
                        "role": "system",
                        "content": ERROR_INTERPRETER_PROMPT.format(
                            error=error,
                            intent=intent.type.value if intent else "unknown",
                            slots=str(intent.extra) if intent else "{}",
                        ),
                    },
                    {"role": "user", "content": "Interpret this error."},
                ],
                temperature=0.3,
                max_tokens=500,
            )

            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            return json.loads(content)

        except Exception as e:
            logger.warning(f"Error interpretation failed: {e}")
            return self._mock_error_interpretation(error)

    def _mock_error_interpretation(self, error: str) -> dict:
        """Generate a mock error interpretation.

        Args:
            error: The error message

        Returns:
            Basic error interpretation dict
        """
        error_lower = error.lower()

        if "insufficient" in error_lower or "balance" in error_lower:
            return {
                "user_explanation": "You don't have enough TAO for this operation.",
                "likely_causes": ["Insufficient balance", "Amount exceeds available funds"],
                "next_steps": ["Check your balance with 'taox balance'", "Try a smaller amount"],
                "safe_to_retry": False,
                "wait_time": None,
            }
        elif "timeout" in error_lower or "connection" in error_lower:
            return {
                "user_explanation": "Network connection issue occurred.",
                "likely_causes": ["Network timeout", "RPC endpoint unreachable"],
                "next_steps": ["Check your internet connection", "Try again in a few seconds"],
                "safe_to_retry": True,
                "wait_time": "30 seconds",
            }
        elif "password" in error_lower or "decrypt" in error_lower:
            return {
                "user_explanation": "Wallet password issue.",
                "likely_causes": ["Incorrect password", "Wallet locked"],
                "next_steps": ["Verify your password", "Check wallet file permissions"],
                "safe_to_retry": True,
                "wait_time": "immediately",
            }
        else:
            return {
                "user_explanation": f"An error occurred: {error[:100]}...",
                "likely_causes": ["Unknown error"],
                "next_steps": ["Check the full error message", "Try 'taox doctor' to diagnose"],
                "safe_to_retry": False,
                "wait_time": None,
            }

    def chat(self, user_input: str, context: ConversationContext) -> str:
        """Generate a conversational response.

        Args:
            user_input: User's message
            context: Current conversation context

        Returns:
            Assistant's response
        """
        if not self.is_available:
            return self._mock_chat_response(user_input, context)

        try:
            client = self._get_client()

            messages = [
                {
                    "role": "system",
                    "content": CHAT_SYSTEM_PROMPT.format(context=context.get_context_summary()),
                },
            ]
            # History already includes the current user message (added by _process_message)
            messages.extend(context.get_history_for_llm())

            response = client.chat.completions.create(
                model=self.settings.llm.model,
                messages=messages,
                temperature=self.settings.llm.temperature,
                max_tokens=self.settings.llm.max_tokens,
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Chat failed: {e}")
            return f"Sorry, I encountered an error: {e}"

    async def chat_stream(
        self, user_input: str, context: ConversationContext
    ) -> AsyncGenerator[str, None]:
        """Generate a streaming conversational response.

        Args:
            user_input: User's message
            context: Current conversation context

        Yields:
            Chunks of the assistant's response
        """
        if not self.is_available:
            yield self._mock_chat_response(user_input, context)
            return

        try:
            client = self._get_async_client()

            messages = [
                {
                    "role": "system",
                    "content": CHAT_SYSTEM_PROMPT.format(context=context.get_context_summary()),
                },
            ]
            # History already includes the current user message
            messages.extend(context.get_history_for_llm())

            stream = await client.chat.completions.create(
                model=self.settings.llm.model,
                messages=messages,
                temperature=self.settings.llm.temperature,
                max_tokens=self.settings.llm.max_tokens,
                stream=True,
            )

            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            logger.error(f"Streaming chat failed: {e}")
            yield f"Sorry, I encountered an error: {e}"

    def _mock_chat_response(self, user_input: str, context: ConversationContext) -> str:
        """Generate a mock response when LLM is unavailable.

        Args:
            user_input: User's message
            context: Current conversation context

        Returns:
            A helpful mock response
        """
        intent = MockIntentParser.parse(user_input)

        help_text = """Here's what I can help you with:

**Check Balances**
• "what is my balance?" - See your TAO balance
• "show my portfolio" - View all your stake positions

**Staking**
• "stake 10 TAO to Taostats on subnet 1" - Stake to a validator
• "unstake 5 TAO" - Remove stake from a position

**Transfers**
• "send 10 TAO to 5xxx..." - Transfer TAO to an address

**Network Info**
• "show validators on subnet 1" - List top validators
• "list subnets" - Show available subnets
• "metagraph for subnet 18" - View subnet metagraph

**History**
• "show my transaction history" - View recent transactions

**Other**
• "taox doctor" - Check your environment setup
• "taox --demo chat" - Try demo mode (no real transactions)

Just ask naturally - I'll figure out what you need!"""

        responses = {
            IntentType.BALANCE: "I'll check your balance. In demo mode, your balance is: 100.0000 τ",
            IntentType.PORTFOLIO: "I'll show your portfolio. In demo mode, you have stakes across 3 subnets.",
            IntentType.STAKE: f"I understood you want to stake{f' {intent.amount} TAO' if intent.amount else ''}{f' to {intent.validator_name}' if intent.validator_name else ''}{f' on subnet {intent.netuid}' if intent.netuid else ''}. I'll prepare that command.",
            IntentType.UNSTAKE: f"I understood you want to unstake{f' {intent.amount} TAO' if intent.amount else ''}. I'll prepare that command.",
            IntentType.TRANSFER: f"I understood you want to transfer{f' {intent.amount} TAO' if intent.amount else ''}{f' to {intent.destination}' if intent.destination else ''}. I'll prepare that command.",
            IntentType.VALIDATORS: f"I'll show validators{f' on subnet {intent.netuid}' if intent.netuid else ''}.",
            IntentType.SUBNETS: "I'll list the available subnets.",
            IntentType.METAGRAPH: f"I'll show the metagraph{f' for subnet {intent.netuid}' if intent.netuid else ''}.",
            IntentType.HISTORY: "I'll show your recent transaction history.",
            IntentType.HELP: help_text,
            IntentType.GREETING: "Hey! I'm taox, your Bittensor assistant. I can help you check balances, stake TAO, view validators, and more. What would you like to do?",
            IntentType.UNKNOWN: "I'm not sure what you'd like to do. Try asking about your balance, staking, or type 'help' for more options.",
        }

        return responses.get(intent.type, responses[IntentType.UNKNOWN])
