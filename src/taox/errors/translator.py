"""Error Translator - Turn chain errors into human steps.

This module converts raw btcli/subtensor errors into:
- A short human explanation
- Actionable next steps
- Safe retry guidance

High-impact feature that makes failures understandable.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ErrorCategory(Enum):
    """Categories of errors for consistent handling."""

    RATE_LIMIT = "rate_limit"
    INTERVAL_FULL = "interval_full"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    INVALID_ADDRESS = "invalid_address"
    NETWORK_ERROR = "network_error"
    INVALID_TRANSACTION = "invalid_transaction"
    WALLET_NOT_FOUND = "wallet_not_found"
    HOTKEY_NOT_FOUND = "hotkey_not_found"
    ALREADY_REGISTERED = "already_registered"
    NOT_REGISTERED = "not_registered"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class TranslatedError:
    """A human-friendly error with guidance."""

    category: ErrorCategory
    user_message: str
    recommended_actions: list[str] = field(default_factory=list)
    safe_to_retry_now: bool = False
    retry_after_blocks: Optional[int] = None
    retry_after_seconds: Optional[int] = None
    original_error: Optional[str] = None

    @property
    def retry_hint(self) -> Optional[str]:
        """Get retry timing hint."""
        if self.safe_to_retry_now:
            return "Safe to retry immediately"
        if self.retry_after_blocks:
            seconds = self.retry_after_blocks * 12  # ~12s per block
            if seconds > 60:
                minutes = seconds // 60
                return f"Wait ~{minutes} minute(s) before retrying"
            return f"Wait ~{seconds} seconds before retrying"
        if self.retry_after_seconds:
            if self.retry_after_seconds > 60:
                minutes = self.retry_after_seconds // 60
                return f"Wait ~{minutes} minute(s) before retrying"
            return f"Wait ~{self.retry_after_seconds} seconds before retrying"
        return None


# Error patterns - centralized and tested
ERROR_PATTERNS = [
    # Rate limit errors
    {
        "pattern": r"(RateLimitExceeded|rate.?limit|Custom error:?\s*6)",
        "category": ErrorCategory.RATE_LIMIT,
        "message": "You're rate limited. Stop retrying and wait before trying again.",
        "actions": [
            "Wait 2-5 minutes before retrying",
            "Run: taox doctor",
        ],
        "safe_to_retry": False,
        "retry_seconds": 180,
    },
    # Registration interval full
    {
        "pattern": r"(registration.*full|interval.*full|try again in\s*(\d+)\s*blocks?)",
        "category": ErrorCategory.INTERVAL_FULL,
        "message": "Subnet registration is full right now.",
        "actions": [
            "Try again in {blocks} blocks (~{seconds} seconds)",
            "Do not spam retries",
            "Run: taox watch --registration {netuid}",
        ],
        "safe_to_retry": False,
        "extract_blocks": r"try again in\s*(\d+)\s*blocks?",
    },
    # Insufficient balance
    {
        "pattern": r"(insufficient|not enough|balance too low|InsufficientBalance)",
        "category": ErrorCategory.INSUFFICIENT_BALANCE,
        "message": "Not enough free TAO to cover amount + fee.",
        "actions": [
            "Check balance: taox balance",
            "Reduce the amount or wait for unstaking",
        ],
        "safe_to_retry": False,
    },
    # Invalid address
    {
        "pattern": r"(invalid.*address|invalid.*ss58|bad address|InvalidAddress)",
        "category": ErrorCategory.INVALID_ADDRESS,
        "message": "The address you provided is invalid.",
        "actions": [
            "Double-check the SS58 address",
            "Make sure it's a valid Bittensor address (starts with 5)",
        ],
        "safe_to_retry": True,
    },
    # Network/RPC errors
    {
        "pattern": r"(network error|connection refused|timeout|could not connect|RPC.*error|endpoint.*unreachable)",
        "category": ErrorCategory.NETWORK_ERROR,
        "message": "Cannot reach the network. Check your connection or RPC endpoint.",
        "actions": [
            "Check your internet connection",
            "Run: taox doctor",
            "Try again in a few seconds",
        ],
        "safe_to_retry": True,
        "retry_seconds": 10,
    },
    # Invalid transaction
    {
        "pattern": r"(invalid.*transaction|Transaction.*rejected|stale nonce|bad signature)",
        "category": ErrorCategory.INVALID_TRANSACTION,
        "message": "Transaction was rejected by the network.",
        "actions": [
            "Possible causes: stale nonce, insufficient fees, rate limit",
            "Run: taox doctor",
            "Run: taox balance",
        ],
        "safe_to_retry": False,
        "retry_seconds": 30,
    },
    # Wallet not found
    {
        "pattern": r"(wallet.*not found|no wallet|cannot find wallet|coldkey.*not found)",
        "category": ErrorCategory.WALLET_NOT_FOUND,
        "message": "Wallet not found.",
        "actions": [
            "Check wallet name: taox -- wallet list",
            "Create a new wallet: taox -- wallet new",
        ],
        "safe_to_retry": True,
    },
    # Hotkey not found
    {
        "pattern": r"(hotkey.*not found|no hotkey|cannot find hotkey)",
        "category": ErrorCategory.HOTKEY_NOT_FOUND,
        "message": "Hotkey not found.",
        "actions": [
            "Check hotkey: taox -- wallet list",
            "Create a new hotkey: taox -- wallet new_hotkey",
        ],
        "safe_to_retry": True,
    },
    # Already registered
    {
        "pattern": r"(already registered|AlreadyRegistered)",
        "category": ErrorCategory.ALREADY_REGISTERED,
        "message": "You're already registered on this subnet.",
        "actions": [
            "No action needed - you're already registered!",
            "Check your registration: taox metagraph --netuid {netuid}",
        ],
        "safe_to_retry": False,
    },
    # Not registered
    {
        "pattern": r"(not registered|NotRegistered|must be registered)",
        "category": ErrorCategory.NOT_REGISTERED,
        "message": "You need to be registered on this subnet first.",
        "actions": [
            "Register: taox register --netuid {netuid}",
        ],
        "safe_to_retry": False,
    },
    # Permission denied
    {
        "pattern": r"(permission denied|access denied|unauthorized|wrong password)",
        "category": ErrorCategory.PERMISSION_DENIED,
        "message": "Permission denied. Check your password or permissions.",
        "actions": [
            "Make sure you entered the correct password",
            "Check file permissions on wallet files",
        ],
        "safe_to_retry": True,
    },
    # Timeout
    {
        "pattern": r"(timed? ?out|deadline exceeded|took too long)",
        "category": ErrorCategory.TIMEOUT,
        "message": "Operation timed out.",
        "actions": [
            "The network may be congested",
            "Run: taox doctor",
            "Try again in a few seconds",
        ],
        "safe_to_retry": True,
        "retry_seconds": 15,
    },
]


def translate_error(
    error_text: str,
    exit_code: Optional[int] = None,
    netuid: Optional[int] = None,
) -> TranslatedError:
    """Translate raw error output into human-friendly format.

    Args:
        error_text: Raw stderr/stdout from btcli
        exit_code: Process exit code if available
        netuid: Subnet ID for context (optional)

    Returns:
        TranslatedError with explanation and guidance
    """
    error_lower = error_text.lower()

    for pattern_def in ERROR_PATTERNS:
        pattern = pattern_def["pattern"]
        if re.search(pattern, error_lower, re.IGNORECASE):
            category = pattern_def["category"]
            message = pattern_def["message"]
            actions = list(pattern_def["actions"])
            safe_to_retry = pattern_def.get("safe_to_retry", False)
            retry_seconds = pattern_def.get("retry_seconds")
            retry_blocks = None

            # Extract blocks from pattern if present
            if "extract_blocks" in pattern_def:
                blocks_match = re.search(pattern_def["extract_blocks"], error_lower, re.IGNORECASE)
                if blocks_match:
                    try:
                        retry_blocks = int(blocks_match.group(1))
                        seconds = retry_blocks * 12

                        # Update message and actions with extracted values
                        message = f"Subnet registration is full. Try again in {retry_blocks} blocks (~{seconds} seconds)."
                        actions = [
                            f"Wait ~{retry_blocks} blocks (~{seconds} seconds)",
                            "Do not spam retries - you'll get rate limited",
                        ]
                        if netuid:
                            actions.append(f"Run: taox watch --registration {netuid}")
                    except (ValueError, IndexError):
                        pass

            # Substitute netuid if provided
            if netuid:
                actions = [
                    a.format(
                        netuid=netuid, blocks=retry_blocks or "N", seconds=(retry_blocks or 0) * 12
                    )
                    for a in actions
                ]

            return TranslatedError(
                category=category,
                user_message=message,
                recommended_actions=actions,
                safe_to_retry_now=safe_to_retry,
                retry_after_blocks=retry_blocks,
                retry_after_seconds=retry_seconds,
                original_error=error_text[:500] if error_text else None,
            )

    # Unknown error
    return TranslatedError(
        category=ErrorCategory.UNKNOWN,
        user_message="Something went wrong. Check the error details below.",
        recommended_actions=[
            "Run: taox doctor",
            "Check logs for more details",
        ],
        safe_to_retry_now=False,
        original_error=error_text[:500] if error_text else None,
    )


def format_error_for_display(translated: TranslatedError) -> str:
    """Format translated error for Rich console display."""
    lines = []

    # Main message
    lines.append(f"[error]✗ {translated.user_message}[/error]")

    # Retry hint
    if translated.retry_hint:
        lines.append(f"[muted]{translated.retry_hint}[/muted]")

    # Actions
    if translated.recommended_actions:
        lines.append("")
        lines.append("[muted]Next steps:[/muted]")
        for action in translated.recommended_actions:
            if action.startswith("Run:"):
                cmd = action.replace("Run:", "").strip()
                lines.append(f"  [success]➜[/success] [command]{cmd}[/command]")
            else:
                lines.append(f"  [muted]•[/muted] {action}")

    return "\n".join(lines)


def is_retryable(category: ErrorCategory) -> bool:
    """Check if an error category is safe to retry immediately."""
    retryable = {
        ErrorCategory.NETWORK_ERROR,
        ErrorCategory.TIMEOUT,
        ErrorCategory.INVALID_ADDRESS,
        ErrorCategory.WALLET_NOT_FOUND,
        ErrorCategory.HOTKEY_NOT_FOUND,
        ErrorCategory.PERMISSION_DENIED,
    }
    return category in retryable
