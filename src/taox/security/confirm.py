"""Transaction and action confirmation utilities."""

from typing import Optional
from rich.panel import Panel
from rich import box

from InquirerPy import inquirer

from taox.ui.console import console, format_tao, format_address
from taox.ui.theme import TaoxColors, Symbols
from taox.config.settings import get_settings


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

    # Build confirmation panel content
    lines = [f"[warning]{Symbols.WARN} {action}[/warning]", ""]

    if amount is not None:
        lines.append(f"[bold]Amount:[/bold] {format_tao(amount)}")

    if validator_name:
        lines.append(f"[bold]Validator:[/bold] [validator]{validator_name}[/validator]")

    if to_address:
        lines.append(f"[bold]To:[/bold] {format_address(to_address, truncate=False)}")

    if from_address:
        lines.append(f"[bold]From:[/bold] {format_address(from_address, truncate=False)}")

    if netuid is not None:
        lines.append(f"[bold]Subnet:[/bold] [subnet]SN{netuid}[/subnet]")

    if extra_info:
        lines.append("")
        for key, value in extra_info.items():
            lines.append(f"[bold]{key}:[/bold] {value}")

    # Display confirmation panel
    console.print(
        Panel(
            "\n".join(lines),
            title=f"[warning]{Symbols.WARN} Confirm Transaction[/warning]",
            border_style=TaoxColors.WARNING,
            box=box.DOUBLE,
        )
    )

    # For large amounts, require typing address prefix
    is_large_amount = (
        amount is not None
        and settings.ui.confirm_large_tx
        and amount >= settings.ui.large_tx_threshold
    )

    if is_large_amount and to_address:
        console.print(
            f"\n[warning]Large transaction detected ({format_tao(amount)})[/warning]"
        )
        prefix_length = 8
        expected_prefix = to_address[:prefix_length].lower()

        user_input = inquirer.text(
            message=f"Type first {prefix_length} characters of destination address to confirm:",
        ).execute()

        if user_input.lower() != expected_prefix:
            console.print("[error]Address prefix mismatch. Transaction cancelled.[/error]")
            return False

    # Final confirmation
    return inquirer.confirm(
        message="Execute this transaction?",
        default=False,
    ).execute()


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
[command]btcli {command}[/command]
{mode}"""

    console.print(
        Panel(
            content,
            title=f"[primary]{Symbols.INFO} Command Preview[/primary]",
            border_style=TaoxColors.PRIMARY,
            box=box.ROUNDED,
        )
    )
