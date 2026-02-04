"""Wallet operations for taox."""

from typing import Optional

from rich import box
from rich.table import Table

from taox.commands.executor import BtcliExecutor, build_transfer_command
from taox.config.settings import get_settings
from taox.data.sdk import BalanceInfo, BittensorSDK, WalletInfo
from taox.security.confirm import confirm_transaction
from taox.ui.console import console, format_address, format_tao, print_error, print_success
from taox.ui.theme import TaoxColors


async def list_wallets(sdk: BittensorSDK) -> list[WalletInfo]:
    """List all available wallets.

    Args:
        sdk: BittensorSDK instance

    Returns:
        List of WalletInfo objects
    """
    wallets = sdk.list_wallets()

    if not wallets:
        console.print("[muted]No wallets found.[/muted]")
        return []

    table = Table(
        title="[primary]Wallets[/primary]",
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
    )
    table.add_column("Name", style="primary")
    table.add_column("Coldkey", style="address")
    table.add_column("Hotkeys", style="muted")

    for wallet in wallets:
        hotkeys_str = ", ".join(wallet.hotkeys[:3])
        if len(wallet.hotkeys) > 3:
            hotkeys_str += f" (+{len(wallet.hotkeys) - 3} more)"

        table.add_row(
            wallet.name,
            format_address(wallet.coldkey_ss58) if wallet.coldkey_ss58 else "[muted]N/A[/muted]",
            hotkeys_str or "[muted]None[/muted]",
        )

    console.print(table)
    return wallets


async def show_balance(
    sdk: BittensorSDK,
    wallet_name: Optional[str] = None,
    address: Optional[str] = None,
) -> Optional[BalanceInfo]:
    """Show balance for a wallet or address.

    Args:
        sdk: BittensorSDK instance
        wallet_name: Name of the wallet
        address: SS58 address (alternative to wallet_name)

    Returns:
        BalanceInfo or None
    """
    settings = get_settings()

    # Get address
    if address:
        ss58 = address
    elif wallet_name:
        wallet = sdk.get_wallet(name=wallet_name)
        if not wallet:
            print_error(f"Wallet '{wallet_name}' not found")
            return None
        ss58 = wallet.coldkey.ss58_address
    else:
        # Use default wallet
        wallet = sdk.get_wallet()
        if not wallet:
            print_error("No default wallet found")
            return None
        wallet_name = settings.bittensor.default_wallet
        ss58 = wallet.coldkey.ss58_address

    # Get balance
    with console.status("[bold green]Fetching balance..."):
        balance = await sdk.get_balance_async(ss58)

    # Display
    console.print()
    console.print(f"[primary]Wallet:[/primary] {wallet_name or 'N/A'}")
    console.print(f"[primary]Address:[/primary] {format_address(ss58, truncate=False)}")
    console.print()
    console.print(f"[bold]Free Balance:[/bold]   {format_tao(balance.free)}")
    console.print(f"[bold]Staked:[/bold]         {format_tao(balance.staked)}")
    console.print(f"[bold]Total:[/bold]          {format_tao(balance.total)}")
    console.print()

    return balance


async def transfer_tao(
    executor: BtcliExecutor,
    sdk: BittensorSDK,
    amount: float,
    destination: str,
    wallet_name: Optional[str] = None,
    skip_confirm: bool = False,
    dry_run: bool = False,
) -> bool:
    """Transfer TAO to another address.

    Args:
        executor: BtcliExecutor instance
        sdk: BittensorSDK instance
        amount: Amount to transfer
        destination: Destination SS58 address
        wallet_name: Source wallet name
        skip_confirm: Skip confirmation prompt
        dry_run: Show command without executing

    Returns:
        True if successful
    """
    settings = get_settings()
    wallet_name = wallet_name or settings.bittensor.default_wallet

    # Get source wallet info
    wallet = sdk.get_wallet(name=wallet_name)
    from_address = wallet.coldkey.ss58_address if wallet else "Unknown"

    # Build command
    cmd_info = build_transfer_command(
        amount=amount,
        destination=destination,
        wallet_name=wallet_name,
    )

    if dry_run:
        console.print(f"[muted]Would transfer {amount} τ to {format_address(destination)}[/muted]")
        return True

    # Simple confirmation
    if not confirm_transaction(
        action="Transfer TAO",
        amount=amount,
        to_address=destination,
        from_address=from_address,
        skip_confirm=skip_confirm,
    ):
        console.print("[muted]Cancelled.[/muted]")
        return False

    # Execute with interactive password handling
    console.print("[muted]Executing transfer...[/muted]")
    result = executor.run_interactive(**cmd_info)

    if result.success:
        print_success(f"Sent {amount} τ to {format_address(destination)}")
        return True
    else:
        print_error(f"Transfer failed: {result.stderr}")
        return False
