"""Error handling utilities for taox."""

import asyncio
import functools
import logging
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

import httpx

from taox.ui.console import console, print_error

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ErrorCategory(Enum):
    """Categories of errors for user-friendly messages."""

    NETWORK = "network"
    AUTH = "authentication"
    VALIDATION = "validation"
    WALLET = "wallet"
    BLOCKCHAIN = "blockchain"
    UNKNOWN = "unknown"


class TaoxError(Exception):
    """Base exception for taox errors."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        suggestion: Optional[str] = None,
        original: Optional[Exception] = None,
    ):
        self.message = message
        self.category = category
        self.suggestion = suggestion
        self.original = original
        super().__init__(message)

    def display(self) -> None:
        """Display the error to the user."""
        print_error(self.message)
        if self.suggestion:
            console.print(f"[muted]Suggestion: {self.suggestion}[/muted]")


class NetworkError(TaoxError):
    """Network-related errors."""

    def __init__(
        self, message: str, suggestion: Optional[str] = None, original: Optional[Exception] = None
    ):
        super().__init__(
            message,
            category=ErrorCategory.NETWORK,
            suggestion=suggestion or "Check your internet connection and try again",
            original=original,
        )


class AuthenticationError(TaoxError):
    """Authentication-related errors."""

    def __init__(
        self, message: str, suggestion: Optional[str] = None, original: Optional[Exception] = None
    ):
        super().__init__(
            message,
            category=ErrorCategory.AUTH,
            suggestion=suggestion or "Run 'taox setup' to configure API keys",
            original=original,
        )


class ValidationError(TaoxError):
    """Input validation errors."""

    def __init__(
        self, message: str, suggestion: Optional[str] = None, original: Optional[Exception] = None
    ):
        super().__init__(
            message,
            category=ErrorCategory.VALIDATION,
            suggestion=suggestion,
            original=original,
        )


class WalletError(TaoxError):
    """Wallet-related errors."""

    def __init__(
        self, message: str, suggestion: Optional[str] = None, original: Optional[Exception] = None
    ):
        super().__init__(
            message,
            category=ErrorCategory.WALLET,
            suggestion=suggestion or "Check your wallet configuration with 'btcli wallet list'",
            original=original,
        )


class BlockchainError(TaoxError):
    """Blockchain interaction errors."""

    def __init__(
        self, message: str, suggestion: Optional[str] = None, original: Optional[Exception] = None
    ):
        super().__init__(
            message,
            category=ErrorCategory.BLOCKCHAIN,
            suggestion=suggestion or "The network may be congested. Try again later.",
            original=original,
        )


def classify_error(error: Exception) -> TaoxError:
    """Classify an exception into a TaoxError category.

    Args:
        error: The original exception

    Returns:
        A TaoxError with appropriate category and suggestion
    """
    error_str = str(error).lower()

    # Network errors
    if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout, ConnectionError)):
        return NetworkError(
            "Unable to connect to the network",
            suggestion="Check your internet connection",
            original=error,
        )

    if isinstance(error, httpx.TimeoutException):
        return NetworkError(
            "Request timed out",
            suggestion="The server may be slow. Try again.",
            original=error,
        )

    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status == 401 or status == 403:
            return AuthenticationError(
                "API authentication failed",
                suggestion="Check your API key with 'taox setup'",
                original=error,
            )
        elif status == 429:
            return NetworkError(
                "Rate limit exceeded",
                suggestion="Wait a moment and try again",
                original=error,
            )
        elif status >= 500:
            return NetworkError(
                f"Server error (HTTP {status})",
                suggestion="The service may be experiencing issues",
                original=error,
            )

    # Wallet errors
    if "wallet" in error_str and ("not found" in error_str or "does not exist" in error_str):
        return WalletError(
            "Wallet not found",
            suggestion="Create a wallet with 'btcli wallet create'",
            original=error,
        )

    if "coldkey" in error_str or "hotkey" in error_str:
        return WalletError(
            f"Wallet key error: {error}",
            original=error,
        )

    # Blockchain errors
    if "insufficient" in error_str and ("balance" in error_str or "funds" in error_str):
        return BlockchainError(
            "Insufficient balance for this operation",
            suggestion="Check your balance with 'taox balance'",
            original=error,
        )

    if "nonce" in error_str or "already in pool" in error_str:
        return BlockchainError(
            "Transaction conflict",
            suggestion="Wait for pending transactions to complete",
            original=error,
        )

    # Default
    return TaoxError(
        str(error),
        category=ErrorCategory.UNKNOWN,
        original=error,
    )


def handle_errors(
    fallback: Optional[T] = None,
    show_error: bool = True,
    reraise: bool = False,
) -> Callable:
    """Decorator to handle errors gracefully.

    Args:
        fallback: Value to return on error (default None)
        show_error: Whether to display error to user
        reraise: Whether to re-raise the error after handling

    Returns:
        Decorated function
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return func(*args, **kwargs)
            except TaoxError as e:
                logger.error(f"{e.category.value} error: {e.message}", exc_info=True)
                if show_error:
                    e.display()
                if reraise:
                    raise
                return fallback
            except Exception as e:
                taox_error = classify_error(e)
                logger.error(f"Unexpected error: {e}", exc_info=True)
                if show_error:
                    taox_error.display()
                if reraise:
                    raise taox_error from e
                return fallback

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return await func(*args, **kwargs)
            except TaoxError as e:
                logger.error(f"{e.category.value} error: {e.message}", exc_info=True)
                if show_error:
                    e.display()
                if reraise:
                    raise
                return fallback
            except Exception as e:
                taox_error = classify_error(e)
                logger.error(f"Unexpected error: {e}", exc_info=True)
                if show_error:
                    taox_error.display()
                if reraise:
                    raise taox_error from e
                return fallback

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


async def retry_async(
    func: Callable[..., T],
    *args: Any,
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    **kwargs: Any,
) -> T:
    """Retry an async function with exponential backoff.

    Args:
        func: Async function to retry
        *args: Positional arguments for func
        max_attempts: Maximum number of attempts
        delay: Initial delay between attempts in seconds
        backoff: Multiplier for delay after each attempt
        exceptions: Tuple of exceptions to catch and retry
        **kwargs: Keyword arguments for func

    Returns:
        Result of func

    Raises:
        Last exception if all attempts fail
    """
    last_error = None
    current_delay = delay

    for attempt in range(1, max_attempts + 1):
        try:
            return await func(*args, **kwargs)
        except exceptions as e:
            last_error = e
            if attempt < max_attempts:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} failed: {e}. "
                    f"Retrying in {current_delay:.1f}s..."
                )
                await asyncio.sleep(current_delay)
                current_delay *= backoff
            else:
                logger.error(f"All {max_attempts} attempts failed")

    raise last_error


def retry_sync(
    func: Callable[..., T],
    *args: Any,
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    **kwargs: Any,
) -> T:
    """Retry a sync function with exponential backoff.

    Args:
        func: Function to retry
        *args: Positional arguments for func
        max_attempts: Maximum number of attempts
        delay: Initial delay between attempts in seconds
        backoff: Multiplier for delay after each attempt
        exceptions: Tuple of exceptions to catch and retry
        **kwargs: Keyword arguments for func

    Returns:
        Result of func

    Raises:
        Last exception if all attempts fail
    """
    import time

    last_error = None
    current_delay = delay

    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except exceptions as e:
            last_error = e
            if attempt < max_attempts:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} failed: {e}. "
                    f"Retrying in {current_delay:.1f}s..."
                )
                time.sleep(current_delay)
                current_delay *= backoff
            else:
                logger.error(f"All {max_attempts} attempts failed")

    raise last_error
