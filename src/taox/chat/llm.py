"""LLM client for Chutes AI integration."""

import json
import logging
from typing import Optional, AsyncGenerator

from openai import OpenAI, AsyncOpenAI

from taox.config.settings import get_settings
from taox.security.credentials import CredentialManager
from taox.chat.intents import Intent, IntentType, MockIntentParser
from taox.chat.context import ConversationContext


logger = logging.getLogger(__name__)


# System prompt for intent classification
INTENT_SYSTEM_PROMPT = """You are taox, an AI assistant for the Bittensor network. You help users manage their TAO tokens, stake to validators, and interact with subnets.

When users request actions, extract the following into JSON format:
{
    "intent": "STAKE" | "UNSTAKE" | "TRANSFER" | "BALANCE" | "PORTFOLIO" | "METAGRAPH" | "REGISTER" | "VALIDATORS" | "SUBNETS" | "INFO" | "HELP",
    "amount": number or null,
    "amount_all": boolean (true if user said "all"),
    "validator_name": string or null,
    "validator_ss58": string or null (SS58 address if provided),
    "netuid": number or null (subnet ID),
    "destination": string or null (SS58 address for transfers),
    "wallet_name": string or null
}

Rules:
- For STAKE: extract amount, validator_name or validator_ss58, and netuid
- For UNSTAKE: extract amount and optionally validator and netuid
- For TRANSFER: extract amount and destination address
- For BALANCE/PORTFOLIO: no additional fields needed
- For METAGRAPH/VALIDATORS: extract netuid if specified
- If user says "all", set amount_all to true
- If unclear, set intent to "INFO" and ask for clarification

Current context:
{context}

Respond ONLY with the JSON object, no other text."""


# System prompt for conversational responses
CHAT_SYSTEM_PROMPT = """You are taox, a friendly and knowledgeable AI assistant for the Bittensor network.

Your role is to help users:
- Manage their TAO tokens (check balance, stake, unstake, transfer)
- Understand the Bittensor network (subnets, validators, metagraph)
- Execute btcli commands through natural conversation

Guidelines:
- Be concise but helpful
- Always confirm understanding before suggesting actions
- For amounts over 10 TAO, emphasize the confirmation requirement
- Use the tau symbol (τ) when mentioning TAO amounts
- Format SS58 addresses clearly

Current context:
{context}"""


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
                temperature=0.3,  # Lower temperature for more deterministic parsing
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

            # Map to Intent object
            intent_type = IntentType(data.get("intent", "unknown").lower())

            return Intent(
                type=intent_type,
                raw_input=user_input,
                confidence=0.95,
                amount=data.get("amount"),
                amount_all=data.get("amount_all", False),
                validator_name=data.get("validator_name"),
                validator_ss58=data.get("validator_ss58"),
                netuid=data.get("netuid"),
                destination=data.get("destination"),
                wallet_name=data.get("wallet_name"),
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            return MockIntentParser.parse(user_input)
        except Exception as e:
            logger.warning(f"LLM parsing failed, using mock parser: {e}")
            return MockIntentParser.parse(user_input)

    async def parse_intent_async(
        self, user_input: str, context: ConversationContext
    ) -> Intent:
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
                temperature=0.3,
                max_tokens=500,
            )

            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            data = json.loads(content)
            intent_type = IntentType(data.get("intent", "unknown").lower())

            return Intent(
                type=intent_type,
                raw_input=user_input,
                confidence=0.95,
                amount=data.get("amount"),
                amount_all=data.get("amount_all", False),
                validator_name=data.get("validator_name"),
                validator_ss58=data.get("validator_ss58"),
                netuid=data.get("netuid"),
                destination=data.get("destination"),
                wallet_name=data.get("wallet_name"),
            )

        except Exception as e:
            logger.warning(f"Async LLM parsing failed: {e}")
            return MockIntentParser.parse(user_input)

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
                    "content": CHAT_SYSTEM_PROMPT.format(
                        context=context.get_context_summary()
                    ),
                },
            ]
            messages.extend(context.get_history_for_llm())
            messages.append({"role": "user", "content": user_input})

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
                    "content": CHAT_SYSTEM_PROMPT.format(
                        context=context.get_context_summary()
                    ),
                },
            ]
            messages.extend(context.get_history_for_llm())
            messages.append({"role": "user", "content": user_input})

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

        responses = {
            IntentType.BALANCE: "I'll check your balance. In demo mode, your balance is: 100.0000 τ",
            IntentType.PORTFOLIO: "I'll show your portfolio. In demo mode, you have stakes across 3 subnets.",
            IntentType.STAKE: f"I understood you want to stake{f' {intent.amount} TAO' if intent.amount else ''}{f' to {intent.validator_name}' if intent.validator_name else ''}{f' on subnet {intent.netuid}' if intent.netuid else ''}. I'll prepare that command.",
            IntentType.UNSTAKE: f"I understood you want to unstake{f' {intent.amount} TAO' if intent.amount else ''}. I'll prepare that command.",
            IntentType.TRANSFER: f"I understood you want to transfer{f' {intent.amount} TAO' if intent.amount else ''}{f' to {intent.destination}' if intent.destination else ''}. I'll prepare that command.",
            IntentType.VALIDATORS: f"I'll show validators{f' on subnet {intent.netuid}' if intent.netuid else ''}.",
            IntentType.SUBNETS: "I'll list the available subnets.",
            IntentType.METAGRAPH: f"I'll show the metagraph{f' for subnet {intent.netuid}' if intent.netuid else ''}.",
            IntentType.HELP: "I can help you with:\n- Check balance: 'what is my balance?'\n- Stake TAO: 'stake 10 TAO to validator X on subnet 1'\n- Unstake: 'unstake 5 TAO'\n- Transfer: 'send 10 TAO to 5xxx...'\n- View validators: 'show validators on subnet 1'\n- View subnets: 'list subnets'",
            IntentType.UNKNOWN: "I'm not sure what you'd like to do. Try asking about your balance, staking, or type 'help' for more options.",
        }

        return responses.get(intent.type, responses[IntentType.UNKNOWN])
