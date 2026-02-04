"""Tests for the Router module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taox.chat.llm_interpreter import IntentType, LLMResponse, Slots
from taox.chat.router import ExecutionResult, Router


class TestExecutionResult:
    """Test the ExecutionResult dataclass."""

    def test_success_result(self):
        """Test creating a success result."""
        result = ExecutionResult(
            success=True,
            message="Balance: 100 τ",
            data={"balance": 100},
        )
        assert result.success is True
        assert result.message == "Balance: 100 τ"
        assert result.data["balance"] == 100
        assert result.error is None

    def test_error_result(self):
        """Test creating an error result."""
        result = ExecutionResult(
            success=False,
            message="Failed to fetch balance",
            error="Connection timeout",
        )
        assert result.success is False
        assert result.error == "Connection timeout"


class TestRouter:
    """Test the Router class."""

    @pytest.fixture
    def mock_clients(self):
        """Create mock clients for router."""
        taostats = AsyncMock()
        sdk = MagicMock()
        executor = MagicMock()
        return taostats, sdk, executor

    @pytest.fixture
    def router(self, mock_clients):
        """Create a router with mocked dependencies."""
        taostats, sdk, executor = mock_clients
        with patch("taox.chat.router.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                demo_mode=False,
                bittensor=MagicMock(
                    default_wallet="default",
                    default_hotkey="default",
                    network="finney",
                ),
            )
            return Router(taostats=taostats, sdk=sdk, executor=executor)

    @pytest.mark.asyncio
    async def test_handle_confirmation_yes(self, router):
        """Test handling 'yes' confirmation."""
        # Set up a pending confirmation
        router._pending_confirmation = LLMResponse(
            intent=IntentType.BALANCE,
            reply="Check balance?",
            ready_to_execute=True,
        )

        with patch.object(router, "_execute", new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = ExecutionResult(
                success=True,
                message="Balance: 50 τ",
            )

            result = await router._handle_confirmation("yes")
            assert result == "Balance: 50 τ"
            assert router._pending_confirmation is None

    @pytest.mark.asyncio
    async def test_handle_confirmation_no(self, router):
        """Test handling 'no' confirmation."""
        router._pending_confirmation = LLMResponse(
            intent=IntentType.STAKE,
            reply="Stake 10 τ?",
            ready_to_execute=True,
        )

        result = await router._handle_confirmation("no")
        assert "Cancelled" in result
        assert router._pending_confirmation is None

    @pytest.mark.asyncio
    async def test_handle_confirmation_unclear(self, router):
        """Test handling unclear confirmation response."""
        router._pending_confirmation = LLMResponse(
            intent=IntentType.STAKE,
            reply="Stake?",
            ready_to_execute=True,
        )

        result = await router._handle_confirmation("maybe")
        assert "yes" in result.lower() or "no" in result.lower()
        assert router._pending_confirmation is not None  # Still pending

    @pytest.mark.asyncio
    async def test_execute_price(self, router, mock_clients):
        """Test executing price intent."""
        taostats, _, _ = mock_clients
        taostats.get_price.return_value = MagicMock(usd=450.0, change_24h=2.5)

        result = await router._exec_price()
        assert result.success is True
        assert "$450" in result.message
        assert "+2.5%" in result.message

    @pytest.mark.asyncio
    async def test_execute_balance(self, router, mock_clients):
        """Test executing balance intent."""
        taostats, sdk, _ = mock_clients
        sdk.get_wallet.return_value = MagicMock(
            coldkey=MagicMock(ss58_address="5xxx...")
        )
        # Use AsyncMock for async method
        sdk.get_balance_async = AsyncMock(return_value=MagicMock(free=100.0, staked=50.0))

        slots = Slots(wallet_name="default")
        result = await router._exec_balance(slots)
        assert result.success is True

    def test_get_help(self, router):
        """Test help text generation."""
        help_text = router._get_help()
        assert "balance" in help_text.lower()
        assert "stake" in help_text.lower()
        assert "portfolio" in help_text.lower()

    def test_clear(self, router):
        """Test clearing router state."""
        router._pending_confirmation = LLMResponse(
            intent=IntentType.STAKE,
            reply="Pending...",
        )

        router.clear()
        assert router._pending_confirmation is None

    @pytest.mark.asyncio
    async def test_execute_greeting(self, router):
        """Test executing greeting intent."""
        response = LLMResponse(
            intent=IntentType.GREETING,
            reply="Hey! Ready to help with your TAO.",
        )

        result = await router._execute(response)
        assert result.success is True
        assert result.message == "Hey! Ready to help with your TAO."

    @pytest.mark.asyncio
    async def test_execute_help(self, router):
        """Test executing help intent."""
        response = LLMResponse(
            intent=IntentType.HELP,
            reply="Here's what I can do...",
        )

        result = await router._execute(response)
        assert result.success is True
        assert "balance" in result.message.lower()

    def test_exec_set_config_hotkey(self, router):
        """Test setting hotkey config."""
        with patch("taox.chat.state_machine.UserPreferences") as mock_prefs:
            mock_pref_instance = MagicMock()
            mock_prefs.load.return_value = mock_pref_instance

            slots = Slots(config_key="hotkey", config_value="my_hot")
            result = router._exec_set_config(slots)

            assert result.success is True
            assert "my_hot" in result.message
            mock_pref_instance.save.assert_called_once()

    def test_exec_set_config_wallet(self, router):
        """Test setting wallet config."""
        with patch("taox.chat.state_machine.UserPreferences") as mock_prefs:
            mock_pref_instance = MagicMock()
            mock_prefs.load.return_value = mock_pref_instance

            slots = Slots(config_key="wallet", config_value="my_wallet")
            result = router._exec_set_config(slots)

            assert result.success is True
            assert "my_wallet" in result.message

    @pytest.mark.asyncio
    async def test_execute_handles_exception(self, router):
        """Test that execute handles exceptions gracefully."""
        response = LLMResponse(
            intent=IntentType.BALANCE,
            slots=Slots(),
            reply="Checking...",
            ready_to_execute=True,
        )

        with patch.object(router, "_exec_balance", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("Network error")

            result = await router._execute(response)
            assert result.success is False
            assert "Network error" in result.error


class TestRouterConfirmationVariants:
    """Test various confirmation input formats."""

    @pytest.fixture
    def router(self):
        """Create router with mocked dependencies."""
        with patch("taox.chat.router.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                demo_mode=False,
                bittensor=MagicMock(
                    default_wallet="default",
                    default_hotkey="default",
                    network="finney",
                ),
            )
            return Router(
                taostats=AsyncMock(),
                sdk=MagicMock(),
                executor=MagicMock(),
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("positive", ["yes", "y", "ok", "okay", "confirm", "sure", "go", "do it", "proceed"])
    async def test_positive_confirmations(self, router, positive):
        """Test all positive confirmation variants."""
        router._pending_confirmation = LLMResponse(
            intent=IntentType.HELP,
            reply="Show help?",
            ready_to_execute=True,
        )

        with patch.object(router, "_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ExecutionResult(success=True, message="Done")
            result = await router._handle_confirmation(positive)
            mock_exec.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("negative", ["no", "n", "cancel", "stop", "nevermind", "abort"])
    async def test_negative_confirmations(self, router, negative):
        """Test all negative confirmation variants."""
        router._pending_confirmation = LLMResponse(
            intent=IntentType.STAKE,
            reply="Stake?",
            ready_to_execute=True,
        )

        result = await router._handle_confirmation(negative)
        assert "Cancelled" in result
        assert router._pending_confirmation is None
