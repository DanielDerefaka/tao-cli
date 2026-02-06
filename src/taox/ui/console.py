"""Rich console setup and output helpers for taox."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from taox.ui.theme import Symbols, TaoxColors, taox_theme

# Main console instance with taox theme
console = Console(theme=taox_theme)

# JSON output console (no styling)
json_console = Console(force_terminal=False, no_color=True)


def print_error(message: str, title: str = "Error") -> None:
    """Print an error message in a styled panel."""
    console.print(
        Panel(
            f"[error]{Symbols.CROSS} {message}[/error]",
            title=f"[error]{title}[/error]",
            border_style=TaoxColors.ERROR,
            box=box.ROUNDED,
        )
    )


def print_success(message: str, title: str = "Success") -> None:
    """Print a success message in a styled panel."""
    console.print(
        Panel(
            f"[success]{Symbols.CHECK} {message}[/success]",
            title=f"[success]{title}[/success]",
            border_style=TaoxColors.SUCCESS,
            box=box.ROUNDED,
        )
    )


def print_warning(message: str, title: str = "Warning") -> None:
    """Print a warning message in a styled panel."""
    console.print(
        Panel(
            f"[warning]{Symbols.WARN} {message}[/warning]",
            title=f"[warning]{title}[/warning]",
            border_style=TaoxColors.WARNING,
            box=box.ROUNDED,
        )
    )


def print_info(message: str, title: str = "Info") -> None:
    """Print an info message in a styled panel."""
    console.print(
        Panel(
            f"[info]{Symbols.INFO} {message}[/info]",
            title=f"[info]{title}[/info]",
            border_style=TaoxColors.INFO,
            box=box.ROUNDED,
        )
    )


def print_welcome() -> None:
    """Print the taox welcome banner."""
    banner = """
[tao]████████╗ █████╗  ██████╗ ██╗  ██╗[/tao]
[tao]╚══██╔══╝██╔══██╗██╔═══██╗╚██╗██╔╝[/tao]
[tao]   ██║   ███████║██║   ██║ ╚███╔╝ [/tao]
[tao]   ██║   ██╔══██║██║   ██║ ██╔██╗ [/tao]
[tao]   ██║   ██║  ██║╚██████╔╝██╔╝ ██╗[/tao]
[tao]   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝[/tao]

[muted]AI-powered CLI for Bittensor[/muted]
"""
    console.print(Panel(banner, border_style=TaoxColors.TAO, box=box.DOUBLE))


def format_tao(amount: float, symbol: bool = True) -> str:
    """Format a TAO amount with proper styling."""
    formatted = f"{amount:,.4f}"
    if symbol:
        return f"[tao]{formatted} {Symbols.TAO}[/tao]"
    return f"[tao]{formatted}[/tao]"


def format_address(address: str, truncate: bool = True) -> str:
    """Format an SS58 address with optional truncation."""
    display = f"{address[:8]}...{address[-8:]}" if truncate and len(address) > 16 else address
    return f"[address]{display}[/address]"


def format_alpha(amount: float, symbol: bool = True) -> str:
    """Format an alpha token amount with proper styling."""
    formatted = f"{amount:,.4f}"
    if symbol:
        return f"[alpha]{formatted} {Symbols.ALPHA}[/alpha]"
    return f"[alpha]{formatted}[/alpha]"


def create_table(title: str, columns: list[tuple[str, str]]) -> Table:
    """Create a styled table with the given columns.

    Args:
        title: Table title
        columns: List of (name, style) tuples for columns

    Returns:
        Configured Rich Table instance
    """
    table = Table(
        title=f"[primary]{title}[/primary]",
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
        header_style="table.header",
        show_lines=False,
    )
    for name, style in columns:
        table.add_column(name, style=style)
    return table


# =============================================================================
# Layout Helpers (Upgrade Pack)
# =============================================================================


@dataclass
class CommandContext:
    """Context for command execution display."""

    command: str
    network: Optional[str] = None
    wallet: Optional[str] = None
    hotkey: Optional[str] = None


def print_title_panel(
    ctx: CommandContext,
    subtitle: Optional[str] = None,
) -> None:
    """Print a consistent title panel for commands.

    Example:
    ┌ taox • Stake ─────────────────────────────────┐
    │ network: finney   wallet: dx   hotkey: dx_hot │
    └───────────────────────────────────────────────┘
    """
    # Build context line
    parts = []
    if ctx.network:
        parts.append(f"[muted]network:[/muted] [info]{ctx.network}[/info]")
    if ctx.wallet:
        parts.append(f"[muted]wallet:[/muted] [primary]{ctx.wallet}[/primary]")
    if ctx.hotkey:
        parts.append(f"[muted]hotkey:[/muted] [secondary]{ctx.hotkey}[/secondary]")

    context_line = "   ".join(parts) if parts else ""

    # Build content
    content = ""
    if subtitle:
        content = f"[muted]{subtitle}[/muted]\n"
    if context_line:
        content += context_line

    title = f"[tao]taox[/tao] [muted]•[/muted] [primary]{ctx.command}[/primary]"

    console.print(
        Panel(
            content.strip() if content.strip() else " ",
            title=title,
            title_align="left",
            border_style=TaoxColors.TAO,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def print_next_steps(steps: list[str], title: str = "Next") -> None:
    """Print a next-steps footer.

    Example:
    Next:
    ➜ taox portfolio
    ➜ taox stake --wizard
    """
    if not steps:
        return

    lines = [f"[muted]{title}:[/muted]"]
    for step in steps:
        lines.append(f"  [success]{Symbols.NEXT}[/success] [command]{step}[/command]")

    console.print("\n".join(lines))


# =============================================================================
# Transaction Lifecycle UI
# =============================================================================


class TxPhase(Enum):
    """Transaction lifecycle phases."""

    PLANNING = "planning"
    SIGNING = "signing"
    BROADCASTING = "broadcasting"
    IN_BLOCK = "in_block"
    FINALIZED = "finalized"
    FAILED = "failed"


@dataclass
class TxStatus:
    """Transaction status information."""

    phase: TxPhase
    message: Optional[str] = None
    tx_hash: Optional[str] = None
    block_number: Optional[int] = None
    error: Optional[str] = None


def get_phase_display(phase: TxPhase) -> tuple[str, str]:
    """Get symbol and style for a tx phase."""
    phase_map = {
        TxPhase.PLANNING: (Symbols.INFO, "info"),
        TxPhase.SIGNING: (Symbols.SIGNING, "warning"),
        TxPhase.BROADCASTING: (Symbols.BROADCAST, "info"),
        TxPhase.IN_BLOCK: (Symbols.IN_BLOCK, "info"),
        TxPhase.FINALIZED: (Symbols.FINALIZED, "success"),
        TxPhase.FAILED: (Symbols.FAILED, "error"),
    }
    return phase_map.get(phase, (Symbols.INFO, "muted"))


def print_tx_status(status: TxStatus) -> None:
    """Print transaction status with lifecycle indicator."""
    symbol, style = get_phase_display(status.phase)

    # Build status line
    phase_name = status.phase.value.replace("_", " ").title()
    line = f"[{style}]{symbol} {phase_name}[/{style}]"

    if status.message:
        line += f"  [muted]{status.message}[/muted]"

    console.print(line)

    # Show tx hash if available
    if status.tx_hash:
        truncated = f"{status.tx_hash[:10]}...{status.tx_hash[-8:]}"
        console.print(f"  [muted]tx:[/muted] [address]{truncated}[/address]")

    # Show block if available
    if status.block_number:
        console.print(f"  [muted]block:[/muted] [info]{status.block_number}[/info]")

    # Show error if failed
    if status.error and status.phase == TxPhase.FAILED:
        console.print(f"  [error]{status.error}[/error]")


def print_tx_lifecycle(statuses: list[TxStatus]) -> None:
    """Print full transaction lifecycle with all phases."""
    for status in statuses:
        print_tx_status(status)


# =============================================================================
# Plan View
# =============================================================================


@dataclass
class PlanItem:
    """An item in a transaction plan."""

    label: str
    value: str
    style: str = "primary"
    is_warning: bool = False


def print_plan(
    title: str,
    items: list[PlanItem],
    warnings: Optional[list[str]] = None,
    dry_run: bool = False,
) -> None:
    """Print a transaction plan for confirmation.

    Example:
    ┌ Plan ────────────────────────────────┐
    │ Action:    Stake                     │
    │ Amount:    10.0000 τ                 │
    │ Validator: taostats                  │
    │ Subnet:    1                         │
    │ Est. Fee:  ~0.0001 τ                 │
    │                                      │
    │ ⚠ High-value transaction             │
    └──────────────────────────────────────┘
    """
    lines = []

    # Add plan items
    max_label_len = max(len(item.label) for item in items) if items else 0
    for item in items:
        padded_label = item.label.ljust(max_label_len)
        if item.is_warning:
            lines.append(f"[warning]{padded_label}:[/warning] [{item.style}]{item.value}[/{item.style}]")
        else:
            lines.append(f"[muted]{padded_label}:[/muted] [{item.style}]{item.value}[/{item.style}]")

    # Add warnings
    if warnings:
        lines.append("")
        for warning in warnings:
            lines.append(f"[warning]{Symbols.WARN} {warning}[/warning]")

    # Add dry-run notice
    if dry_run:
        lines.append("")
        lines.append(f"[info]{Symbols.INFO} Dry run - no transaction will be executed[/info]")

    content = "\n".join(lines)
    panel_title = f"[primary]{title}[/primary]"
    if dry_run:
        panel_title += " [muted](dry-run)[/muted]"

    console.print(
        Panel(
            content,
            title=panel_title,
            title_align="left",
            border_style=TaoxColors.PRIMARY,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def print_confirmation_prompt() -> None:
    """Print a confirmation prompt."""
    console.print("\n[prompt]Confirm? (y/n)[/prompt] ", end="")


# =============================================================================
# Share Mode Helpers
# =============================================================================


def redact_address(address: str, mode: str = "truncate") -> str:
    """Redact an address for share mode.

    Args:
        address: Full SS58 address
        mode: "truncate" (show first/last 4) or "hide" (show ***)

    Returns:
        Redacted address string
    """
    if mode == "hide":
        return "***"
    if len(address) > 8:
        return f"{address[:4]}...{address[-4:]}"
    return address


def redact_wallet_name(name: str) -> str:
    """Redact wallet name for share mode."""
    return "(hidden)"


def format_balance_range(amount: float) -> str:
    """Format balance as a range for share mode."""
    if amount < 1:
        return "<1 τ"
    elif amount < 10:
        return "1-10 τ"
    elif amount < 100:
        return "10-100 τ"
    elif amount < 1000:
        return "100-1K τ"
    elif amount < 10000:
        return "1K-10K τ"
    else:
        return ">10K τ"


def print_share_notice() -> None:
    """Print notice that output is anonymized."""
    console.print("[muted](anonymized for sharing)[/muted]\n")
