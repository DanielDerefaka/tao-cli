"""Table display utilities for taox."""

from typing import Optional

from rich import box
from rich.table import Table

from taox.ui.console import console, format_address, format_tao
from taox.ui.theme import TaoxColors


def display_balance_table(
    wallet_name: str,
    address: str,
    free: float,
    staked: float,
    total: float,
    usd_price: Optional[float] = None,
) -> None:
    """Display a formatted balance table.

    Args:
        wallet_name: Name of the wallet
        address: SS58 address
        free: Free balance in TAO
        staked: Staked balance in TAO
        total: Total balance in TAO
        usd_price: Current TAO price in USD (optional)
    """
    table = Table(
        title=f"[primary]Balance - {wallet_name}[/primary]",
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
        show_header=False,
    )
    table.add_column("Label", style="bold")
    table.add_column("Value", style="tao", justify="right")

    if usd_price:
        table.add_column("USD", style="muted", justify="right")
        table.add_row("Free", format_tao(free, symbol=False), f"${free * usd_price:,.2f}")
        table.add_row("Staked", format_tao(staked, symbol=False), f"${staked * usd_price:,.2f}")
        table.add_row("Total", format_tao(total, symbol=False), f"${total * usd_price:,.2f}")
    else:
        table.add_row("Free", format_tao(free))
        table.add_row("Staked", format_tao(staked))
        table.add_row("Total", format_tao(total))

    console.print()
    console.print(f"[muted]Address: {format_address(address, truncate=False)}[/muted]")
    console.print(table)


def display_portfolio_table(
    positions: list[dict],
    total_staked: float,
    usd_price: Optional[float] = None,
) -> None:
    """Display a formatted portfolio table.

    Args:
        positions: List of stake positions with netuid, validator, stake
        total_staked: Total staked amount
        usd_price: Current TAO price in USD (optional)
    """
    table = Table(
        title="[primary]Portfolio[/primary]",
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
    )
    table.add_column("Subnet", style="subnet")
    table.add_column("Validator", style="validator")
    table.add_column("Stake", justify="right", style="tao")
    if usd_price:
        table.add_column("Value", justify="right", style="muted")

    for pos in positions:
        row = [
            f"SN{pos.get('netuid', '?')}",
            pos.get("validator_name", format_address(pos.get("hotkey", ""))),
            format_tao(pos.get("stake", 0), symbol=False),
        ]
        if usd_price:
            row.append(f"${pos.get('stake', 0) * usd_price:,.2f}")
        table.add_row(*row)

    console.print(table)
    console.print()
    console.print(f"[bold]Total Staked:[/bold] {format_tao(total_staked)}")
    if usd_price:
        console.print(f"[muted]Value: ${total_staked * usd_price:,.2f}[/muted]")


def display_validators_table(
    validators: list[dict],
    netuid: Optional[int] = None,
) -> None:
    """Display a formatted validators table.

    Args:
        validators: List of validator dicts
        netuid: Subnet ID (for title)
    """
    title = "Top Validators"
    if netuid is not None:
        title += f" (Subnet {netuid})"

    table = Table(
        title=f"[primary]{title}[/primary]",
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
    )
    table.add_column("#", justify="right", style="muted", width=4)
    table.add_column("Name", style="validator")
    table.add_column("Stake", justify="right", style="tao")
    table.add_column("Take", justify="right", style="warning")
    table.add_column("Hotkey", style="address")

    for i, v in enumerate(validators, 1):
        table.add_row(
            str(i),
            v.get("name") or "[muted]Unknown[/muted]",
            f"{v.get('stake', 0):,.0f}",
            f"{v.get('take', 0) * 100:.1f}%",
            format_address(v.get("hotkey", "")),
        )

    console.print(table)


def display_subnets_table(subnets: list[dict]) -> None:
    """Display a formatted subnets table.

    Args:
        subnets: List of subnet dicts
    """
    table = Table(
        title="[primary]Subnets[/primary]",
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
    )
    table.add_column("ID", justify="right", style="subnet", width=5)
    table.add_column("Name", style="primary")
    table.add_column("Emission", justify="right", style="tao")
    table.add_column("Validators", justify="right", style="muted")
    table.add_column("Burn", justify="right", style="warning")

    for s in sorted(subnets, key=lambda x: x.get("netuid", 0)):
        emission = s.get("emission", 0)
        emission_str = f"{emission * 100:.1f}%" if emission else "0%"

        table.add_row(
            str(s.get("netuid", "?")),
            s.get("name") or "[muted]Unknown[/muted]",
            emission_str,
            str(s.get("validators", 0)),
            format_tao(s.get("burn_cost", 0), symbol=False) if s.get("burn_cost") else "-",
        )

    console.print(table)


def display_transaction_result(
    success: bool,
    action: str,
    amount: Optional[float] = None,
    tx_hash: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Display transaction result.

    Args:
        success: Whether transaction succeeded
        action: Action performed (stake, transfer, etc.)
        amount: Amount involved
        tx_hash: Transaction hash (if available)
        error: Error message (if failed)
    """
    if success:
        msg = f"[success]✓ {action} successful![/success]"
        if amount:
            msg += f"\n  Amount: {format_tao(amount)}"
        if tx_hash:
            msg += f"\n  [muted]TX: {tx_hash}[/muted]"
        console.print(msg)
    else:
        msg = f"[error]✗ {action} failed[/error]"
        if error:
            msg += f"\n  [muted]{error}[/muted]"
        console.print(msg)
