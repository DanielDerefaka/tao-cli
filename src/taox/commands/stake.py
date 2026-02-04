"""Staking operations for taox."""

from typing import Optional
from rich.table import Table
from rich import box

from taox.ui.console import console, format_tao, format_address, print_success, print_error
from taox.ui.theme import TaoxColors
from taox.data.sdk import BittensorSDK
from taox.data.taostats import TaostatsClient, Validator
from taox.commands.executor import (
    BtcliExecutor,
    build_stake_add_command,
    build_stake_remove_command,
)
from taox.security.confirm import confirm_transaction, show_transaction_preview
from taox.config.settings import get_settings


async def show_validators(
    taostats: TaostatsClient,
    netuid: Optional[int] = None,
    limit: int = 10,
) -> list[Validator]:
    """Show top validators for a subnet.

    Args:
        taostats: TaostatsClient instance
        netuid: Subnet ID (None for all)
        limit: Maximum validators to show

    Returns:
        List of Validator objects
    """
    with console.status("[bold green]Fetching validators..."):
        validators = await taostats.get_validators(netuid=netuid, limit=limit)

    if not validators:
        console.print("[muted]No validators found.[/muted]")
        return []

    title = f"Top Validators"
    if netuid is not None:
        title += f" (Subnet {netuid})"

    table = Table(
        title=f"[primary]{title}[/primary]",
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
    )
    table.add_column("Rank", justify="right", style="muted")
    table.add_column("Name", style="validator")
    table.add_column("Stake", justify="right", style="tao")
    table.add_column("Take", justify="right", style="warning")
    table.add_column("Hotkey", style="address")

    for i, v in enumerate(validators, 1):
        name = v.name or "[muted]Unknown[/muted]"
        table.add_row(
            str(i),
            name,
            f"{v.stake:,.0f} τ",
            f"{v.take * 100:.1f}%",
            format_address(v.hotkey),
        )

    console.print(table)
    return validators


async def stake_tao(
    executor: BtcliExecutor,
    sdk: BittensorSDK,
    taostats: TaostatsClient,
    amount: float,
    validator_name: Optional[str] = None,
    validator_ss58: Optional[str] = None,
    netuid: int = 1,
    wallet_name: Optional[str] = None,
    safe_staking: bool = True,
    skip_confirm: bool = False,
    dry_run: bool = False,
) -> bool:
    """Stake TAO to a validator.

    Args:
        executor: BtcliExecutor instance
        sdk: BittensorSDK instance
        taostats: TaostatsClient instance
        amount: Amount to stake
        validator_name: Validator name to search for
        validator_ss58: Validator hotkey address (takes precedence)
        netuid: Subnet ID
        wallet_name: Wallet name
        safe_staking: Enable MEV protection
        skip_confirm: Skip confirmation prompt
        dry_run: Show command without executing

    Returns:
        True if successful
    """
    settings = get_settings()
    wallet_name = wallet_name or settings.bittensor.default_wallet

    # Resolve validator
    hotkey = validator_ss58
    resolved_name = validator_name

    if not hotkey:
        if validator_name:
            # Search for validator by name
            with console.status(f"[bold green]Searching for validator '{validator_name}'..."):
                validator = await taostats.search_validator(validator_name, netuid=netuid)

            if not validator:
                print_error(f"Validator '{validator_name}' not found on subnet {netuid}")
                return False

            hotkey = validator.hotkey
            resolved_name = validator.name or validator_name
            console.print(f"[success]Found validator: {resolved_name}[/success]")
            console.print(f"[muted]Hotkey: {format_address(hotkey)}[/muted]")
        else:
            # Use top validator
            console.print("[info]No validator specified, fetching top validator...[/info]")
            validators = await taostats.get_validators(netuid=netuid, limit=1)
            if not validators:
                print_error(f"No validators found on subnet {netuid}")
                return False

            hotkey = validators[0].hotkey
            resolved_name = validators[0].name or "Top Validator"
            console.print(f"[success]Selected top validator: {resolved_name}[/success]")

    # Build command
    cmd_info = build_stake_add_command(
        amount=amount,
        hotkey=hotkey,
        netuid=netuid,
        wallet_name=wallet_name,
        safe_staking=safe_staking,
    )

    # Show preview
    show_transaction_preview(
        command=executor.get_command_string(**cmd_info),
        description=f"Stake {amount} TAO to {resolved_name} on subnet {netuid}",
        dry_run=dry_run,
    )

    if dry_run:
        return True

    # Confirm
    if not confirm_transaction(
        action="Stake TAO",
        amount=amount,
        to_address=hotkey,
        validator_name=resolved_name,
        netuid=netuid,
        extra_info={"MEV Protection": "Enabled" if safe_staking else "Disabled"},
        skip_confirm=skip_confirm,
    ):
        console.print("[muted]Stake cancelled.[/muted]")
        return False

    # Execute
    with console.status("[bold green]Executing stake..."):
        result = executor.run(**cmd_info)

    if result.success:
        print_success(f"Staked {amount} TAO to {resolved_name} on subnet {netuid}")
        if result.stdout:
            console.print(f"[muted]{result.stdout}[/muted]")
        return True
    else:
        print_error(f"Stake failed: {result.stderr}")
        return False


async def unstake_tao(
    executor: BtcliExecutor,
    sdk: BittensorSDK,
    amount: float,
    hotkey: str,
    netuid: int,
    wallet_name: Optional[str] = None,
    skip_confirm: bool = False,
    dry_run: bool = False,
) -> bool:
    """Unstake TAO from a validator.

    Args:
        executor: BtcliExecutor instance
        sdk: BittensorSDK instance
        amount: Amount to unstake
        hotkey: Validator hotkey address
        netuid: Subnet ID
        wallet_name: Wallet name
        skip_confirm: Skip confirmation prompt
        dry_run: Show command without executing

    Returns:
        True if successful
    """
    settings = get_settings()
    wallet_name = wallet_name or settings.bittensor.default_wallet

    # Build command
    cmd_info = build_stake_remove_command(
        amount=amount,
        hotkey=hotkey,
        netuid=netuid,
        wallet_name=wallet_name,
    )

    # Show preview
    show_transaction_preview(
        command=executor.get_command_string(**cmd_info),
        description=f"Unstake {amount} TAO from subnet {netuid}",
        dry_run=dry_run,
    )

    if dry_run:
        return True

    # Confirm
    if not confirm_transaction(
        action="Unstake TAO",
        amount=amount,
        from_address=hotkey,
        netuid=netuid,
        skip_confirm=skip_confirm,
    ):
        console.print("[muted]Unstake cancelled.[/muted]")
        return False

    # Execute
    with console.status("[bold green]Executing unstake..."):
        result = executor.run(**cmd_info)

    if result.success:
        print_success(f"Unstaked {amount} TAO from subnet {netuid}")
        if result.stdout:
            console.print(f"[muted]{result.stdout}[/muted]")
        return True
    else:
        print_error(f"Unstake failed: {result.stderr}")
        return False


async def show_stake_positions(
    taostats: TaostatsClient,
    coldkey: str,
) -> dict:
    """Show stake positions for a coldkey.

    Args:
        taostats: TaostatsClient instance
        coldkey: Coldkey SS58 address

    Returns:
        Stake balance data
    """
    with console.status("[bold green]Fetching stake positions..."):
        data = await taostats.get_stake_balance(coldkey)

    if not data.get("positions"):
        console.print("[muted]No stake positions found.[/muted]")
        return data

    table = Table(
        title="[primary]Stake Positions[/primary]",
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
    )
    table.add_column("Subnet", style="subnet")
    table.add_column("Hotkey", style="address")
    table.add_column("Stake", justify="right", style="tao")

    total = 0.0
    for pos in data.get("positions", []):
        stake = pos.get("stake", 0)
        total += stake
        table.add_row(
            f"SN{pos.get('netuid', '?')}",
            format_address(pos.get("hotkey", "")),
            format_tao(stake, symbol=False),
        )

    console.print(table)
    console.print(f"\n[bold]Total Staked:[/bold] {format_tao(total)}")

    return data
