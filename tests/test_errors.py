"""Tests for error handling utilities."""

from unittest.mock import MagicMock

import httpx
import pytest

from taox.utils.errors import (
    AuthenticationError,
    BlockchainError,
    ErrorCategory,
    NetworkError,
    TaoxError,
    ValidationError,
    WalletError,
    classify_error,
    handle_errors,
    retry_async,
    retry_sync,
)


class TestTaoxError:
    """Tests for TaoxError base class."""

    def test_basic_error(self):
        """Test basic error creation."""
        error = TaoxError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.category == ErrorCategory.UNKNOWN

    def test_error_with_suggestion(self):
        """Test error with suggestion."""
        error = TaoxError(
            "Connection failed",
            category=ErrorCategory.NETWORK,
            suggestion="Check your internet",
        )
        assert error.suggestion == "Check your internet"

    def test_error_with_original(self):
        """Test error with original exception."""
        original = ValueError("Original error")
        error = TaoxError("Wrapped error", original=original)
        assert error.original is original


class TestSpecializedErrors:
    """Tests for specialized error classes."""

    def test_network_error(self):
        """Test NetworkError."""
        error = NetworkError("Connection timeout")
        assert error.category == ErrorCategory.NETWORK
        assert "internet connection" in error.suggestion.lower()

    def test_auth_error(self):
        """Test AuthenticationError."""
        error = AuthenticationError("Invalid API key")
        assert error.category == ErrorCategory.AUTH
        assert "setup" in error.suggestion.lower()

    def test_validation_error(self):
        """Test ValidationError."""
        error = ValidationError("Invalid amount", suggestion="Amount must be positive")
        assert error.category == ErrorCategory.VALIDATION
        assert error.suggestion == "Amount must be positive"

    def test_wallet_error(self):
        """Test WalletError."""
        error = WalletError("Wallet not found")
        assert error.category == ErrorCategory.WALLET

    def test_blockchain_error(self):
        """Test BlockchainError."""
        error = BlockchainError("Transaction failed")
        assert error.category == ErrorCategory.BLOCKCHAIN


class TestClassifyError:
    """Tests for classify_error function."""

    def test_classify_connection_error(self):
        """Test classifying connection errors."""
        original = ConnectionError("Connection refused")
        error = classify_error(original)
        assert isinstance(error, NetworkError)

    def test_classify_timeout_error(self):
        """Test classifying timeout errors."""
        original = httpx.TimeoutException("Request timed out")
        error = classify_error(original)
        assert isinstance(error, NetworkError)

    def test_classify_http_401(self):
        """Test classifying HTTP 401 error."""
        response = MagicMock()
        response.status_code = 401
        original = httpx.HTTPStatusError("Unauthorized", request=MagicMock(), response=response)
        error = classify_error(original)
        assert isinstance(error, AuthenticationError)

    def test_classify_http_429(self):
        """Test classifying HTTP 429 rate limit error."""
        response = MagicMock()
        response.status_code = 429
        original = httpx.HTTPStatusError("Rate limited", request=MagicMock(), response=response)
        error = classify_error(original)
        assert isinstance(error, NetworkError)
        assert "rate limit" in error.message.lower()

    def test_classify_http_500(self):
        """Test classifying HTTP 500 error."""
        response = MagicMock()
        response.status_code = 500
        original = httpx.HTTPStatusError("Server error", request=MagicMock(), response=response)
        error = classify_error(original)
        assert isinstance(error, NetworkError)

    def test_classify_wallet_not_found(self):
        """Test classifying wallet not found error."""
        original = Exception("wallet not found")
        error = classify_error(original)
        assert isinstance(error, WalletError)

    def test_classify_insufficient_balance(self):
        """Test classifying insufficient balance error."""
        original = Exception("insufficient balance for transfer")
        error = classify_error(original)
        assert isinstance(error, BlockchainError)

    def test_classify_unknown_error(self):
        """Test classifying unknown errors."""
        original = Exception("Something completely random")
        error = classify_error(original)
        assert isinstance(error, TaoxError)
        assert error.category == ErrorCategory.UNKNOWN


class TestHandleErrorsDecorator:
    """Tests for handle_errors decorator."""

    def test_successful_function(self):
        """Test decorator on successful function."""

        @handle_errors(fallback="fallback")
        def success_func():
            return "success"

        result = success_func()
        assert result == "success"

    def test_function_with_error_returns_fallback(self):
        """Test decorator returns fallback on error."""

        @handle_errors(fallback="fallback", show_error=False)
        def failing_func():
            raise ValueError("Error!")

        result = failing_func()
        assert result == "fallback"

    def test_function_with_taox_error(self):
        """Test decorator handles TaoxError."""

        @handle_errors(fallback=None, show_error=False)
        def taox_error_func():
            raise NetworkError("Network down")

        result = taox_error_func()
        assert result is None

    def test_reraise_option(self):
        """Test reraise option."""

        @handle_errors(reraise=True, show_error=False)
        def failing_func():
            raise ValueError("Error!")

        with pytest.raises(TaoxError):
            failing_func()


@pytest.mark.asyncio
class TestHandleErrorsAsyncDecorator:
    """Tests for handle_errors decorator on async functions."""

    async def test_successful_async_function(self):
        """Test decorator on successful async function."""

        @handle_errors(fallback="fallback")
        async def success_func():
            return "success"

        result = await success_func()
        assert result == "success"

    async def test_async_function_with_error(self):
        """Test decorator returns fallback on async error."""

        @handle_errors(fallback="fallback", show_error=False)
        async def failing_func():
            raise ValueError("Error!")

        result = await failing_func()
        assert result == "fallback"


class TestRetrySync:
    """Tests for retry_sync function."""

    def test_successful_first_try(self):
        """Test function succeeds on first try."""
        call_count = 0

        def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = retry_sync(success_func, max_attempts=3, delay=0.01)
        assert result == "success"
        assert call_count == 1

    def test_retry_on_failure(self):
        """Test function retries on failure."""
        call_count = 0

        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary error")
            return "success"

        result = retry_sync(flaky_func, max_attempts=3, delay=0.01)
        assert result == "success"
        assert call_count == 3

    def test_max_attempts_exceeded(self):
        """Test raises after max attempts."""

        def always_fails():
            raise ValueError("Always fails")

        with pytest.raises(ValueError):
            retry_sync(always_fails, max_attempts=3, delay=0.01)

    def test_specific_exception_types(self):
        """Test retry only catches specified exceptions."""
        call_count = 0

        def raises_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("Type error")

        with pytest.raises(TypeError):
            retry_sync(
                raises_type_error,
                max_attempts=3,
                delay=0.01,
                exceptions=(ValueError,),  # Only catch ValueError
            )

        assert call_count == 1  # No retries


@pytest.mark.asyncio
class TestRetryAsync:
    """Tests for retry_async function."""

    async def test_successful_first_try(self):
        """Test async function succeeds on first try."""
        call_count = 0

        async def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await retry_async(success_func, max_attempts=3, delay=0.01)
        assert result == "success"
        assert call_count == 1

    async def test_async_retry_on_failure(self):
        """Test async function retries on failure."""
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary error")
            return "success"

        result = await retry_async(flaky_func, max_attempts=3, delay=0.01)
        assert result == "success"
        assert call_count == 3

    async def test_async_max_attempts_exceeded(self):
        """Test async raises after max attempts."""

        async def always_fails():
            raise ValueError("Always fails")

        with pytest.raises(ValueError):
            await retry_async(always_fails, max_attempts=3, delay=0.01)
