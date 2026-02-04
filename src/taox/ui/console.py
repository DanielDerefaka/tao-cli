"""Rich console setup and output helpers for taox."""

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
