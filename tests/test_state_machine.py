"""Tests for the conversation state machine."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from taox.chat.state_machine import (
    IntentType,
    SlotType,
    FilledSlots,
    ParsedIntent,
    UserPreferences,
    ConversationState,
    ConversationEngine,
    ResponseAction,
    ConversationResponse,
    INTENT_SLOTS,
)


class TestFilledSlots:
    """Test FilledSlots model."""

    def test_get_slot_amount(self):
        """Get amount slot."""
        slots = FilledSlots(amount=10.5)
        assert slots.get_slot(SlotType.AMOUNT) == 10.5

    def test_get_slot_amount_all(self):
        """Get amount when 'all' is specified."""
        slots = FilledSlots(amount_all=True)
        assert slots.get_slot(SlotType.AMOUNT) == "all"

    def test_set_slot_amount(self):
        """Set amount slot."""
        slots = FilledSlots()
        slots.set_slot(SlotType.AMOUNT, "25.5")
        assert slots.amount == 25.5

    def test_set_slot_amount_all(self):
        """Set amount to 'all'."""
        slots = FilledSlots()
        slots.set_slot(SlotType.AMOUNT, "all")
        assert slots.amount_all is True
        assert slots.amount is None

    def test_set_slot_validator_name(self):
        """Set validator by name."""
        slots = FilledSlots()
        slots.set_slot(SlotType.VALIDATOR, "Taostats")
        assert slots.validator_name == "Taostats"
        assert slots.validator_ss58 is None

    def test_set_slot_validator_ss58(self):
        """Set validator by SS58 address."""
        slots = FilledSlots()
        slots.set_slot(SlotType.VALIDATOR, "5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v")
        assert slots.validator_ss58 == "5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v"
        assert slots.validator_name is None

    def test_set_slot_netuid(self):
        """Set netuid slot."""
        slots = FilledSlots()
        slots.set_slot(SlotType.NETUID, "18")
        assert slots.netuid == 18


class TestParsedIntent:
    """Test ParsedIntent model."""

    def test_str_representation(self):
        """Test string representation."""
        intent = ParsedIntent(
            type=IntentType.STAKE,
            slots=FilledSlots(amount=10, validator_name="Taostats", netuid=1),
            raw_input="stake 10 TAO",
        )
        s = str(intent)
        assert "STAKE" in s.upper()
        assert "10" in s
        assert "Taostats" in s
        assert "1" in s


class TestUserPreferences:
    """Test UserPreferences persistence."""

    def test_default_values(self):
        """Test default preference values."""
        prefs = UserPreferences()
        assert prefs.default_network == "finney"
        assert prefs.default_wallet is None

    def test_set_default(self):
        """Test setting a default."""
        prefs = UserPreferences()
        prefs.default_wallet = "mytest"
        assert prefs.default_wallet == "mytest"

    def test_get_default(self):
        """Test getting a default."""
        prefs = UserPreferences(default_netuid=18)
        assert prefs.get_default("default_netuid") == 18


class TestConversationEngineBasic:
    """Test basic ConversationEngine functionality."""

    def test_initial_state_is_idle(self):
        """Engine starts in IDLE state."""
        engine = ConversationEngine()
        assert engine.state == ConversationState.IDLE

    def test_greeting_returns_display(self):
        """Greeting returns DISPLAY action."""
        engine = ConversationEngine()
        response = engine.process_input("hello")
        assert response.action == ResponseAction.DISPLAY
        assert "Hello" in response.message or "hello" in response.message.lower()

    def test_help_returns_display(self):
        """Help returns DISPLAY action with help text."""
        engine = ConversationEngine()
        response = engine.process_input("help")
        assert response.action == ResponseAction.DISPLAY
        assert "stake" in response.message.lower() or "balance" in response.message.lower()

    def test_unknown_returns_display(self):
        """Unknown input returns DISPLAY action."""
        engine = ConversationEngine()
        response = engine.process_input("asdfghjkl random gibberish")
        assert response.action == ResponseAction.DISPLAY

    def test_cancel_resets_state(self):
        """Cancel resets to IDLE."""
        engine = ConversationEngine()
        # Start something
        engine.process_input("stake 10 TAO")
        # Cancel
        response = engine.process_input("cancel")
        assert engine.state == ConversationState.IDLE
        assert "cancel" in response.message.lower()


class TestConversationEngineSlotFilling:
    """Test slot-filling behavior."""

    def test_missing_slots_triggers_ask(self):
        """Missing required slots trigger ASK action."""
        engine = ConversationEngine()
        response = engine.process_input("stake 10 TAO")
        # Should ask for validator or netuid
        assert response.action == ResponseAction.ASK
        assert engine.state == ConversationState.SLOT_FILLING

    def test_slot_filling_accepts_answer(self):
        """Slot-filling accepts user answer."""
        engine = ConversationEngine()
        # Start stake with only amount
        response1 = engine.process_input("stake 10 TAO")
        assert engine.state == ConversationState.SLOT_FILLING

        # Provide validator
        response2 = engine.process_input("Taostats")
        # Should ask for netuid or move to confirm
        assert response2.action in (ResponseAction.ASK, ResponseAction.CONFIRM)

    def test_full_command_goes_to_confirm(self):
        """Complete command skips slot-filling and goes to confirm."""
        engine = ConversationEngine()
        engine.preferences.default_wallet = "test"

        response = engine.process_input("stake 10 TAO to Taostats on subnet 1")
        # Should go directly to confirmation
        assert response.action == ResponseAction.CONFIRM
        assert engine.state == ConversationState.CONFIRMING


class TestConversationEngineConfirmation:
    """Test confirmation behavior."""

    def test_confirm_yes_executes(self):
        """Confirming with 'yes' triggers execution."""
        engine = ConversationEngine()
        engine.preferences.default_wallet = "test"

        # Full command
        engine.process_input("stake 10 TAO to Taostats on subnet 1")
        assert engine.state == ConversationState.CONFIRMING

        # Confirm
        response = engine.process_input("yes")
        assert response.action == ResponseAction.EXECUTE
        assert engine.state == ConversationState.IDLE

    def test_confirm_no_cancels(self):
        """Confirming with 'no' cancels."""
        engine = ConversationEngine()
        engine.preferences.default_wallet = "test"

        # Full command
        engine.process_input("stake 10 TAO to Taostats on subnet 1")

        # Decline
        response = engine.process_input("no")
        assert response.action == ResponseAction.DISPLAY
        assert "cancel" in response.message.lower()
        assert engine.state == ConversationState.IDLE

    def test_confirm_unclear_asks_again(self):
        """Unclear confirmation response asks again."""
        engine = ConversationEngine()
        engine.preferences.default_wallet = "test"

        # Full command
        engine.process_input("stake 10 TAO to Taostats on subnet 1")

        # Unclear response
        response = engine.process_input("maybe")
        assert response.action == ResponseAction.CONFIRM
        assert engine.state == ConversationState.CONFIRMING


class TestConversationEngineDefaults:
    """Test default value handling."""

    def test_apply_wallet_default(self):
        """Wallet default is applied."""
        engine = ConversationEngine()
        engine.preferences.default_wallet = "mydefault"

        intent = ParsedIntent(type=IntentType.BALANCE, slots=FilledSlots())
        engine._apply_defaults(intent)

        assert intent.slots.wallet == "mydefault"

    def test_apply_netuid_default(self):
        """Netuid default is applied for relevant intents."""
        engine = ConversationEngine()
        engine.preferences.default_netuid = 18

        intent = ParsedIntent(type=IntentType.STAKE, slots=FilledSlots())
        engine._apply_defaults(intent)

        assert intent.slots.netuid == 18

    def test_set_default_command(self):
        """'use wallet X' sets default."""
        engine = ConversationEngine()
        response = engine.process_input("use wallet myvalidator from now on")

        assert engine.preferences.default_wallet == "myvalidator"
        assert "myvalidator" in response.message


class TestConversationEngineFollowUps:
    """Test follow-up suggestions."""

    def test_follow_up_after_stake(self):
        """Get follow-up suggestions after stake."""
        engine = ConversationEngine()
        engine.last_completed_intent = IntentType.STAKE

        suggestions = engine.get_follow_up_suggestions()
        assert len(suggestions) > 0
        assert any("portfolio" in s.lower() for s in suggestions)

    def test_follow_up_after_balance(self):
        """Get follow-up suggestions after balance check."""
        engine = ConversationEngine()
        engine.last_completed_intent = IntentType.BALANCE

        suggestions = engine.get_follow_up_suggestions()
        assert len(suggestions) > 0


class TestConversationEngineQueryIntents:
    """Test query intents (no confirmation needed)."""

    def test_balance_executes_directly(self):
        """Balance query executes without confirmation."""
        engine = ConversationEngine()
        response = engine.process_input("what is my balance")

        assert response.action == ResponseAction.EXECUTE
        assert response.intent.type == IntentType.BALANCE

    def test_portfolio_executes_directly(self):
        """Portfolio query executes without confirmation."""
        engine = ConversationEngine()
        response = engine.process_input("show my portfolio")

        assert response.action == ResponseAction.EXECUTE
        assert response.intent.type == IntentType.PORTFOLIO

    def test_validators_executes_directly(self):
        """Validators query executes without confirmation."""
        engine = ConversationEngine()
        response = engine.process_input("show validators on subnet 1")

        assert response.action == ResponseAction.EXECUTE


class TestIntentSlotDefinitions:
    """Test that slot definitions are correct."""

    def test_stake_has_required_slots(self):
        """Stake intent has correct required slots."""
        slots = INTENT_SLOTS[IntentType.STAKE]
        required = [s for s in slots if s.required]

        slot_names = [s.name for s in required]
        assert SlotType.AMOUNT in slot_names
        assert SlotType.VALIDATOR in slot_names
        assert SlotType.NETUID in slot_names

    def test_transfer_has_required_slots(self):
        """Transfer intent has correct required slots."""
        slots = INTENT_SLOTS[IntentType.TRANSFER]
        required = [s for s in slots if s.required]

        slot_names = [s.name for s in required]
        assert SlotType.AMOUNT in slot_names
        assert SlotType.DESTINATION in slot_names

    def test_balance_has_no_required_slots(self):
        """Balance intent has no required slots."""
        slots = INTENT_SLOTS[IntentType.BALANCE]
        required = [s for s in slots if s.required]
        assert len(required) == 0


class TestConversationResponse:
    """Test ConversationResponse dataclass."""

    def test_display_response(self):
        """Create DISPLAY response."""
        response = ConversationResponse(
            message="Hello!",
            action=ResponseAction.DISPLAY,
        )
        assert response.action == ResponseAction.DISPLAY
        assert response.message == "Hello!"

    def test_execute_response_with_intent(self):
        """Create EXECUTE response with intent."""
        intent = ParsedIntent(type=IntentType.BALANCE, slots=FilledSlots())
        response = ConversationResponse(
            message="",
            action=ResponseAction.EXECUTE,
            intent=intent,
        )
        assert response.action == ResponseAction.EXECUTE
        assert response.intent == intent

    def test_ask_response_with_slot(self):
        """Create ASK response with slot info."""
        response = ConversationResponse(
            message="How much TAO?",
            action=ResponseAction.ASK,
            slot_being_filled=SlotType.AMOUNT,
        )
        assert response.slot_being_filled == SlotType.AMOUNT
