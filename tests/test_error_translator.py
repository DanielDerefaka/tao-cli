"""Golden tests for error translator.

Tests cover:
- Rate limit error patterns
- Registration interval full patterns
- Insufficient balance patterns
- Network/RPC patterns
- Unknown error handling
"""

import pytest

from taox.errors import (
    ErrorCategory,
    TranslatedError,
    format_error_for_display,
    is_retryable,
    translate_error,
)


class TestErrorTranslator:
    """Tests for translate_error function."""

    def test_rate_limit_custom_error_6(self):
        """Test rate limit detection from 'Custom error: 6'."""
        error = "Custom error: 6 - RateLimitExceeded"
        result = translate_error(error)

        assert result.category == ErrorCategory.RATE_LIMIT
        assert "rate limit" in result.user_message.lower()
        assert result.safe_to_retry_now is False
        assert len(result.recommended_actions) > 0

    def test_rate_limit_explicit(self):
        """Test explicit rate limit message."""
        error = "Error: RateLimitExceeded - too many requests"
        result = translate_error(error)

        assert result.category == ErrorCategory.RATE_LIMIT
        assert result.safe_to_retry_now is False

    def test_registration_interval_full(self):
        """Test registration interval full with block count."""
        error = "Registration for subnet 24 is full. Try again in 150 blocks."
        result = translate_error(error, netuid=24)

        assert result.category == ErrorCategory.INTERVAL_FULL
        assert result.retry_after_blocks == 150
        assert "150" in result.user_message
        assert result.safe_to_retry_now is False

    def test_registration_full_no_blocks(self):
        """Test registration full without block count."""
        error = "Registration is full, interval full"
        result = translate_error(error)

        assert result.category == ErrorCategory.INTERVAL_FULL
        assert result.safe_to_retry_now is False

    def test_insufficient_balance(self):
        """Test insufficient balance detection."""
        error = "InsufficientBalance: not enough TAO for transfer"
        result = translate_error(error)

        assert result.category == ErrorCategory.INSUFFICIENT_BALANCE
        assert "not enough" in result.user_message.lower() or "tao" in result.user_message.lower()
        assert any("balance" in a.lower() for a in result.recommended_actions)

    def test_insufficient_balance_variant(self):
        """Test insufficient balance variant."""
        error = "Balance too low for this operation"
        result = translate_error(error)

        assert result.category == ErrorCategory.INSUFFICIENT_BALANCE

    def test_invalid_address(self):
        """Test invalid address detection."""
        error = "Invalid SS58 address format"
        result = translate_error(error)

        assert result.category == ErrorCategory.INVALID_ADDRESS
        assert result.safe_to_retry_now is True

    def test_network_error(self):
        """Test network error detection."""
        error = "Connection refused: could not connect to RPC endpoint"
        result = translate_error(error)

        assert result.category == ErrorCategory.NETWORK_ERROR
        assert result.safe_to_retry_now is True
        assert result.retry_after_seconds is not None

    def test_rpc_error(self):
        """Test RPC error detection."""
        error = "RPC error: endpoint unreachable"
        result = translate_error(error)

        assert result.category == ErrorCategory.NETWORK_ERROR

    def test_invalid_transaction(self):
        """Test invalid transaction detection."""
        error = "Transaction rejected: stale nonce"
        result = translate_error(error)

        assert result.category == ErrorCategory.INVALID_TRANSACTION
        assert result.safe_to_retry_now is False

    def test_wallet_not_found(self):
        """Test wallet not found detection."""
        error = "Error: wallet 'mywall' not found"
        result = translate_error(error)

        assert result.category == ErrorCategory.WALLET_NOT_FOUND
        assert result.safe_to_retry_now is True

    def test_hotkey_not_found(self):
        """Test hotkey not found detection."""
        error = "Cannot find hotkey 'myhot'"
        result = translate_error(error)

        assert result.category == ErrorCategory.HOTKEY_NOT_FOUND
        assert result.safe_to_retry_now is True

    def test_already_registered(self):
        """Test already registered detection."""
        error = "AlreadyRegistered: you're already on this subnet"
        result = translate_error(error)

        assert result.category == ErrorCategory.ALREADY_REGISTERED
        assert result.safe_to_retry_now is False

    def test_not_registered(self):
        """Test not registered detection."""
        error = "NotRegistered: must be registered to perform this action"
        result = translate_error(error, netuid=1)

        assert result.category == ErrorCategory.NOT_REGISTERED
        assert "register" in " ".join(result.recommended_actions).lower()

    def test_permission_denied(self):
        """Test permission denied detection."""
        error = "Error: wrong password"
        result = translate_error(error)

        assert result.category == ErrorCategory.PERMISSION_DENIED
        assert result.safe_to_retry_now is True

    def test_timeout(self):
        """Test timeout detection."""
        error = "Request timed out after 30 seconds"
        result = translate_error(error)

        assert result.category == ErrorCategory.TIMEOUT
        assert result.safe_to_retry_now is True

    def test_unknown_error(self):
        """Test unknown error fallback."""
        error = "Some completely unknown error that doesn't match any pattern xyz123"
        result = translate_error(error)

        assert result.category == ErrorCategory.UNKNOWN
        assert result.original_error is not None

    def test_original_error_preserved(self):
        """Test that original error is preserved."""
        error = "RateLimitExceeded: full error message here"
        result = translate_error(error)

        assert result.original_error == error

    def test_long_error_truncated(self):
        """Test that long errors are truncated."""
        error = "A" * 1000
        result = translate_error(error)

        assert len(result.original_error) <= 500


class TestRetryHint:
    """Tests for retry hint generation."""

    def test_retry_hint_safe_now(self):
        """Test retry hint for immediately retryable errors."""
        result = TranslatedError(
            category=ErrorCategory.NETWORK_ERROR,
            user_message="test",
            safe_to_retry_now=True,
        )
        assert "immediately" in result.retry_hint.lower()

    def test_retry_hint_blocks(self):
        """Test retry hint with block count."""
        result = TranslatedError(
            category=ErrorCategory.INTERVAL_FULL,
            user_message="test",
            retry_after_blocks=150,
        )
        # 150 blocks * 12 seconds = 1800 seconds = 30 minutes
        assert "minute" in result.retry_hint.lower()

    def test_retry_hint_seconds(self):
        """Test retry hint with seconds."""
        result = TranslatedError(
            category=ErrorCategory.RATE_LIMIT,
            user_message="test",
            retry_after_seconds=45,
        )
        assert "45" in result.retry_hint or "second" in result.retry_hint.lower()

    def test_retry_hint_none(self):
        """Test no retry hint when not applicable."""
        result = TranslatedError(
            category=ErrorCategory.INSUFFICIENT_BALANCE,
            user_message="test",
            safe_to_retry_now=False,
        )
        assert result.retry_hint is None


class TestFormatErrorForDisplay:
    """Tests for error display formatting."""

    def test_format_includes_message(self):
        """Test that formatted output includes the message."""
        result = TranslatedError(
            category=ErrorCategory.RATE_LIMIT,
            user_message="You are rate limited",
            recommended_actions=["Wait 2 minutes", "Run: taox doctor"],
        )
        formatted = format_error_for_display(result)

        assert "rate limited" in formatted.lower()

    def test_format_includes_actions(self):
        """Test that formatted output includes actions."""
        result = TranslatedError(
            category=ErrorCategory.RATE_LIMIT,
            user_message="Error",
            recommended_actions=["Wait 2 minutes", "Run: taox doctor"],
        )
        formatted = format_error_for_display(result)

        assert "taox doctor" in formatted
        assert "Wait 2 minutes" in formatted

    def test_format_highlights_commands(self):
        """Test that commands are highlighted."""
        result = TranslatedError(
            category=ErrorCategory.RATE_LIMIT,
            user_message="Error",
            recommended_actions=["Run: taox balance"],
        )
        formatted = format_error_for_display(result)

        assert "[command]" in formatted


class TestIsRetryable:
    """Tests for is_retryable function."""

    def test_network_error_retryable(self):
        """Test network errors are retryable."""
        assert is_retryable(ErrorCategory.NETWORK_ERROR) is True

    def test_timeout_retryable(self):
        """Test timeouts are retryable."""
        assert is_retryable(ErrorCategory.TIMEOUT) is True

    def test_rate_limit_not_retryable(self):
        """Test rate limits are not immediately retryable."""
        assert is_retryable(ErrorCategory.RATE_LIMIT) is False

    def test_insufficient_balance_not_retryable(self):
        """Test insufficient balance is not retryable."""
        assert is_retryable(ErrorCategory.INSUFFICIENT_BALANCE) is False


class TestErrorCategoryTranslator:
    """Tests for ErrorCategory enum in translator."""

    def test_all_categories_exist(self):
        """Test that all expected categories exist."""
        expected = [
            "RATE_LIMIT",
            "INTERVAL_FULL",
            "INSUFFICIENT_BALANCE",
            "INVALID_ADDRESS",
            "NETWORK_ERROR",
            "INVALID_TRANSACTION",
            "WALLET_NOT_FOUND",
            "HOTKEY_NOT_FOUND",
            "ALREADY_REGISTERED",
            "NOT_REGISTERED",
            "PERMISSION_DENIED",
            "TIMEOUT",
            "UNKNOWN",
        ]

        for name in expected:
            assert hasattr(ErrorCategory, name)
