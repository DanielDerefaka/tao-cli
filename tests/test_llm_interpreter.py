"""Tests for the LLM interpreter module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from taox.chat.llm_interpreter import (
    IntentType,
    LLMInterpreter,
    LLMResponse,
    Slots,
)


class TestSlots:
    """Test the Slots model."""

    def test_default_slots(self):
        """Test that slots have sensible defaults."""
        slots = Slots()
        assert slots.amount is None
        assert slots.amount_all is False
        assert slots.validator_name is None
        assert slots.netuid is None

    def test_slots_with_values(self):
        """Test slots with actual values."""
        slots = Slots(
            amount=10.5,
            validator_name="taostats",
            netuid=1,
        )
        assert slots.amount == 10.5
        assert slots.validator_name == "taostats"
        assert slots.netuid == 1


class TestLLMResponse:
    """Test the LLMResponse model."""

    def test_minimal_response(self):
        """Test a minimal valid response."""
        response = LLMResponse(
            intent=IntentType.GREETING,
            reply="Hello!",
        )
        assert response.intent == IntentType.GREETING
        assert response.reply == "Hello!"
        assert response.needs_confirmation is False
        assert response.ready_to_execute is False

    def test_full_response(self):
        """Test a full response with all fields."""
        response = LLMResponse(
            intent=IntentType.STAKE,
            slots=Slots(amount=10, validator_name="taostats", netuid=1),
            reply="Got it! Stake 10 τ to Taostats on SN1. Confirm?",
            needs_confirmation=True,
            ready_to_execute=True,
        )
        assert response.intent == IntentType.STAKE
        assert response.slots.amount == 10
        assert response.needs_confirmation is True
        assert response.ready_to_execute is True


class TestLLMInterpreter:
    """Test the LLM interpreter."""

    @pytest.fixture
    def interpreter(self):
        """Create an interpreter instance."""
        return LLMInterpreter()

    def test_is_available_without_key(self, interpreter):
        """Test that interpreter reports unavailable without API key."""
        with patch("taox.chat.llm_interpreter.CredentialManager.get_chutes_key", return_value=None):
            assert interpreter.is_available is False

    def test_parse_response_valid_json(self, interpreter):
        """Test parsing a valid JSON response."""
        content = json.dumps(
            {
                "intent": "balance",
                "slots": {},
                "reply": "Checking your balance...",
                "needs_confirmation": False,
                "missing_info": None,
                "ready_to_execute": True,
            }
        )

        response = interpreter._parse_response(content, "what is my balance")
        assert response.intent == IntentType.BALANCE
        assert response.ready_to_execute is True

    def test_parse_response_with_markdown(self, interpreter):
        """Test parsing response wrapped in markdown code blocks."""
        content = """```json
{
    "intent": "stake",
    "slots": {"amount": 10, "validator_name": "taostats", "netuid": 1},
    "reply": "Staking 10 TAO",
    "needs_confirmation": true,
    "missing_info": null,
    "ready_to_execute": true
}
```"""

        response = interpreter._parse_response(content, "stake 10 tao")
        assert response.intent == IntentType.STAKE
        assert response.slots.amount == 10
        assert response.slots.validator_name == "taostats"

    def test_parse_response_invalid_json(self, interpreter):
        """Test fallback when JSON is invalid."""
        content = "This is not JSON at all"

        response = interpreter._parse_response(content, "hello")
        assert response.intent == IntentType.UNCLEAR
        assert "catch that" in response.reply

    def test_parse_response_with_preamble(self, interpreter):
        """Test parsing response with text before JSON."""
        content = """Sure! Here's the response:

{
    "intent": "greeting",
    "slots": {},
    "reply": "Hey! What can I help with?",
    "needs_confirmation": false,
    "missing_info": null,
    "ready_to_execute": false
}"""

        response = interpreter._parse_response(content, "hi")
        assert response.intent == IntentType.GREETING
        assert "help" in response.reply.lower()

    def test_parse_response_with_nested_braces(self, interpreter):
        """Test parsing response with nested JSON structures."""
        content = """{
    "intent": "stake",
    "slots": {"amount": 10, "netuid": 1},
    "reply": "Stake 10 τ?",
    "needs_confirmation": true,
    "missing_info": null,
    "ready_to_execute": true
}"""

        response = interpreter._parse_response(content, "stake 10")
        assert response.intent == IntentType.STAKE
        assert response.slots.amount == 10
        assert response.slots.netuid == 1

    def test_fallback_interpret_balance(self, interpreter):
        """Test fallback parsing for balance intent."""
        response = interpreter._fallback_interpret("what is my balance")
        assert response.intent == IntentType.BALANCE
        assert response.ready_to_execute is True

    def test_fallback_interpret_stake(self, interpreter):
        """Test fallback parsing for stake intent."""
        response = interpreter._fallback_interpret("stake 10 tao to taostats on subnet 1")
        assert response.intent == IntentType.STAKE
        assert response.slots.amount == 10
        assert response.needs_confirmation is True

    def test_fallback_interpret_greeting(self, interpreter):
        """Test fallback parsing for greeting."""
        response = interpreter._fallback_interpret("hello")
        assert response.intent == IntentType.GREETING

    def test_fallback_interpret_help(self, interpreter):
        """Test fallback parsing for help."""
        response = interpreter._fallback_interpret("help")
        assert response.intent == IntentType.HELP

    def test_fallback_interpret_validators(self, interpreter):
        """Test fallback parsing for validators."""
        response = interpreter._fallback_interpret("show validators")
        assert response.intent == IntentType.VALIDATORS

    def test_fallback_interpret_subnets(self, interpreter):
        """Test fallback parsing for subnets."""
        response = interpreter._fallback_interpret("list subnets")
        assert response.intent == IntentType.SUBNETS

    def test_interpret_with_mocked_llm(self, interpreter):
        """Test full interpretation with mocked LLM."""
        # Mock the OpenAI client response
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {
                "intent": "stake",
                "slots": {"amount": 50, "validator_name": "Foundry", "netuid": 1},
                "reply": "Stake 50 τ to Foundry on SN1?",
                "needs_confirmation": True,
                "missing_info": None,
                "ready_to_execute": True,
            }
        )
        mock_client.chat.completions.create.return_value = mock_response

        # Patch both is_available property and the client method
        with (
            patch.object(
                type(interpreter), "is_available", new_callable=lambda: property(lambda self: True)
            ),
            patch.object(interpreter, "_get_client", return_value=mock_client),
        ):
            response = interpreter.interpret("stake 50 tao to foundry")

        assert response.intent == IntentType.STAKE
        assert response.slots.amount == 50
        # Note: LLM can return different cases, test case-insensitive
        assert response.slots.validator_name.lower() == "foundry"
        assert response.needs_confirmation is True

    def test_clear_pending(self, interpreter):
        """Test clearing pending intent."""
        # Set a pending intent
        interpreter._pending_intent = LLMResponse(
            intent=IntentType.STAKE,
            reply="How much?",
            missing_info="amount",
        )

        interpreter.clear_pending()
        assert interpreter._pending_intent is None


class TestIntentTypes:
    """Test intent type coverage."""

    def test_all_intent_types_exist(self):
        """Verify all expected intent types are defined."""
        expected = [
            "BALANCE",
            "PORTFOLIO",
            "TRANSFER",
            "STAKE",
            "UNSTAKE",
            "VALIDATORS",
            "SUBNETS",
            "METAGRAPH",
            "PRICE",
            "REGISTER",
            "HISTORY",
            "SET_CONFIG",
            "HELP",
            "GREETING",
            "CONVERSATION",
            "UNCLEAR",
        ]
        for intent_name in expected:
            assert hasattr(IntentType, intent_name), f"Missing intent type: {intent_name}"

    def test_intent_values_are_lowercase(self):
        """Verify intent values are lowercase strings."""
        for intent in IntentType:
            assert intent.value == intent.value.lower()
