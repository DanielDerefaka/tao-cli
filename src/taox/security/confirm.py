"""Transaction and action confirmation utilities."""

import asyncio
from typing import Optional

from InquirerPy import inquirer
from rich import box
from rich.panel import Panel

from taox.config.settings import get_settings
from taox.ui.console import console, format_address, format_tao
from taox.ui.theme import Symbols, TaoxColors


def _is_event_loop_running() -> bool:
    """Check if we're inside a running asyncio event loop."""
    try:
        loop = asyncio.get_running_loop()
        return loop is not None
    except RuntimeError:
        return False


def _simple_confirm(message: str, default: bool = False) -> bool:
    """Simple confirmation prompt using standard input.

    Used when InquirerPy can't run (inside async event loop).
    """
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        response = console.input(f"[bold]{message}[/bold] {suffix} ").strip().lower()
        if not response:
            return default
        return response in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _simple_text_input(message: str) -> str:
    """Simple text input using standard input.

    Used when InquirerPy can't run (inside async event loop).
    """
    try:
        return console.input(f"[bold]{message}[/bold] ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def confirm_action(
    message: str,
    default: bool = False,
    skip_confirm: bool = False,
) -> bool:
    """Prompt user for confirmation of an action.

    Args:
        message: The confirmation message to display
        default: Default value if user just presses Enter
        skip_confirm: If True, skip confirmation and return True

    Returns:
        True if user confirmed, False otherwise
    """
    if skip_confirm:
        return True

    settings = get_settings()
    if not settings.security.require_confirmation:
        return True

    # Use simple prompt if inside event loop (InquirerPy can't run there)
    if _is_event_loop_running():
        return _simple_confirm(message, default)

    return inquirer.confirm(
        message=message,
        default=default,
    ).execute()


def confirm_transaction(
    action: str,
    amount: Optional[float] = None,
    to_address: Optional[str] = None,
    from_address: Optional[str] = None,
    netuid: Optional[int] = None,
    validator_name: Optional[str] = None,
    extra_info: Optional[dict] = None,
    skip_confirm: bool = False,
) -> bool:
    """Prompt user for confirmation of a blockchain transaction.

    For large amounts (>= threshold), requires typing address prefix.

    Args:
        action: Description of the action (e.g., "Stake", "Transfer", "Unstake")
        amount: Amount of TAO involved (if applicable)
        to_address: Destination address (if applicable)
        from_address: Source address (if applicable)
        netuid: Subnet ID (if applicable)
        validator_name: Validator name (if applicable)
        extra_info: Additional key-value pairs to display
        skip_confirm: If True, skip confirmation and return True

    Returns:
        True if user confirmed, False otherwise
    """
    if skip_confirm:
        return True

    settings = get_settings()
    if not settings.security.require_confirmation:
        return True

    # Build simple confirmation message
    parts = []
    if amount is not None:
        parts.append(f"{amount} τ")
    if validator_name:
        parts.append(f"to {validator_name}")
    elif to_address:
        parts.append(f"to {format_address(to_address)}")
    if netuid is not None:
        parts.append(f"on SN{netuid}")

    confirm_msg = f"{action}: {' '.join(parts)}?" if parts else f"{action}?"

    # For large amounts, require extra verification
    is_large_amount = (
        amount is not None
        and settings.ui.confirm_large_tx
        and amount >= settings.ui.large_tx_threshold
    )

    if is_large_amount and to_address:
        console.print(f"[warning]{Symbols.WARN} Large amount: {format_tao(amount)}[/warning]")
        prefix_length = 8
        expected_prefix = to_address[:prefix_length].lower()

        if _is_event_loop_running():
            user_input = _simple_text_input(
                f"Type first {prefix_length} chars of address to confirm:"
            )
        else:
            user_input = inquirer.text(
                message=f"Type first {prefix_length} chars of address to confirm:",
            ).execute()

        if user_input.lower() != expected_prefix:
            console.print("[error]Address mismatch. Cancelled.[/error]")
            return False

    # Simple confirmation
    return _simple_confirm(confirm_msg, default=False)


def show_transaction_preview(
    command: str,
    description: str,
    dry_run: bool = False,
) -> None:
    """Display a preview of the command that will be executed.

    Args:
        command: The btcli command string
        description: Human-readable description of what will happen
        dry_run: If True, indicates this is a preview only
    """
    mode = "[muted](dry run)[/muted]" if dry_run else ""

    content = f"""[bold]Description:[/bold] {description}

[bold]Command:[/bold]
[command]{command}[/command]
{mode}"""

    console.print(
        Panel(
            content,
            title=f"[primary]{Symbols.INFO} Command Preview[/primary]",
            border_style=TaoxColors.PRIMARY,
            box=box.ROUNDED,
        )
    )
