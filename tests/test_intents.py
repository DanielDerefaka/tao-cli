"""Tests for intent parsing."""

import pytest
from taox.chat.intents import (
    IntentType,
    Intent,
    MockIntentParser,
    parse_intent,
)


class TestMockIntentParser:
    """Tests for MockIntentParser."""

    def setup_method(self):
        """Set up test fixtures."""
        self.parser = MockIntentParser()

    def test_parse_balance_intent(self):
        """Test parsing balance queries."""
        queries = [
            "what is my balance",
            "show my balance",
            "check balance",
            "how much tao do i have",
        ]
        for query in queries:
            intent = self.parser.parse(query)
            assert intent.type == IntentType.BALANCE, f"Failed for: {query}"

    def test_parse_portfolio_intent(self):
        """Test parsing portfolio queries."""
        queries = [
            "show my portfolio",
            "display portfolio",
            "show my stakes",
            "list my positions",
        ]
        for query in queries:
            intent = self.parser.parse(query)
            assert intent.type == IntentType.PORTFOLIO, f"Failed for: {query}"

    def test_parse_stake_intent_with_amount(self):
        """Test parsing stake commands with amounts."""
        intent = self.parser.parse("stake 10 tao to taostats on subnet 1")
        assert intent.type == IntentType.STAKE
        assert intent.amount == 10.0
        assert intent.netuid == 1

    def test_parse_stake_intent_decimal_amount(self):
        """Test parsing stake with decimal amounts."""
        intent = self.parser.parse("stake 5.5 tao")
        assert intent.type == IntentType.STAKE
        assert intent.amount == 5.5

    def test_parse_stake_all(self):
        """Test parsing 'stake all'."""
        intent = self.parser.parse("stake all tao")
        assert intent.type == IntentType.STAKE
        assert intent.amount_all is True

    def test_parse_unstake_intent(self):
        """Test parsing unstake commands."""
        intent = self.parser.parse("unstake 5 tao from subnet 1")
        assert intent.type == IntentType.UNSTAKE
        assert intent.amount == 5.0
        assert intent.netuid == 1

    def test_parse_transfer_intent(self):
        """Test parsing transfer commands."""
        intent = self.parser.parse("transfer 10 tao to 5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v")
        assert intent.type == IntentType.TRANSFER
        assert intent.amount == 10.0
        assert intent.destination == "5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v"

    def test_parse_validators_intent(self):
        """Test parsing validator queries."""
        queries = [
            "show validators",
            "list validators on subnet 1",
            "top validators",
        ]
        for query in queries:
            intent = self.parser.parse(query)
            assert intent.type == IntentType.VALIDATORS, f"Failed for: {query}"

    def test_parse_validators_with_netuid(self):
        """Test parsing validator query with netuid."""
        intent = self.parser.parse("show validators on subnet 18")
        assert intent.type == IntentType.VALIDATORS
        assert intent.netuid == 18

    def test_parse_subnets_intent(self):
        """Test parsing subnet queries."""
        queries = [
            "list subnets",
            "show subnets",
            "show all subnets",
        ]
        for query in queries:
            intent = self.parser.parse(query)
            assert intent.type == IntentType.SUBNETS, f"Failed for: {query}"

    def test_parse_metagraph_intent(self):
        """Test parsing metagraph queries."""
        intent = self.parser.parse("show metagraph for subnet 1")
        assert intent.type == IntentType.METAGRAPH
        assert intent.netuid == 1

    def test_parse_help_intent(self):
        """Test parsing help queries."""
        queries = ["help", "what can you do", "how do i"]
        for query in queries:
            intent = self.parser.parse(query)
            assert intent.type == IntentType.HELP, f"Failed for: {query}"

    def test_parse_unknown_intent(self):
        """Test handling unknown queries."""
        intent = self.parser.parse("random gibberish xyz")
        assert intent.type in [IntentType.INFO, IntentType.UNKNOWN]

    def test_parse_with_wallet_name(self):
        """Test parsing with wallet specification."""
        intent = self.parser.parse("check balance for wallet my_wallet")
        assert intent.type == IntentType.BALANCE
        # Wallet extraction is dependent on implementation

    def test_netuid_extraction(self):
        """Test various netuid extraction formats."""
        test_cases = [
            ("subnet 1", 1),
            ("subnet 18", 18),
            ("sn1", 1),
            ("sn18", 18),
            ("netuid 5", 5),
        ]
        for query, expected_netuid in test_cases:
            intent = self.parser.parse(f"show validators on {query}")
            assert intent.netuid == expected_netuid, f"Failed for: {query}"


class TestIntent:
    """Tests for Intent dataclass."""

    def test_intent_defaults(self):
        """Test Intent default values."""
        intent = Intent(type=IntentType.BALANCE, raw_input="test")
        assert intent.amount is None
        assert intent.netuid is None
        assert intent.validator_name is None
        assert intent.destination is None
        assert intent.wallet_name is None
        assert intent.amount_all is False

    def test_intent_with_values(self):
        """Test Intent with all values."""
        intent = Intent(
            type=IntentType.STAKE,
            raw_input="stake 100 to taostats",
            amount=100.0,
            netuid=1,
            validator_name="Taostats",
            wallet_name="default",
        )
        assert intent.type == IntentType.STAKE
        assert intent.amount == 100.0
        assert intent.netuid == 1
        assert intent.validator_name == "Taostats"


def test_parse_intent_function():
    """Test the parse_intent function."""
    intent = parse_intent("what is my balance")
    assert isinstance(intent, Intent)
    assert intent.type == IntentType.BALANCE
