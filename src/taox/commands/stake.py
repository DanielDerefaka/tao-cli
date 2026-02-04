"""Staking operations for taox."""

from typing import Optional

from rich import box
from rich.table import Table

from taox.commands.executor import (
    BtcliExecutor,
    build_stake_add_command,
    build_stake_remove_command,
)
from taox.config.settings import get_settings
from taox.data.sdk import BittensorSDK
from taox.data.taostats import TaostatsClient, Validator
from taox.security.confirm import confirm_transaction
from taox.ui.console import (
    console,
    format_address,
    format_alpha,
    format_tao,
    print_error,
    print_success,
)
from taox.ui.theme import TaoxColors


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

    title = "Top Validators"
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

    if dry_run:
        console.print(f"[muted]Would stake {amount} τ to {resolved_name} on SN{netuid}[/muted]")
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

    # Execute with interactive password handling
    console.print("[muted]Executing stake...[/muted]")
    result = executor.run_interactive(**cmd_info)

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

    if dry_run:
        console.print(f"[muted]Would unstake {amount} τ from SN{netuid}[/muted]")
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

    # Execute with interactive password handling
    console.print("[muted]Executing unstake...[/muted]")
    result = executor.run_interactive(**cmd_info)

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
    table.add_column("Alpha", justify="right", style="alpha")

    total = 0.0
    total_alpha = 0.0
    for pos in data.get("positions", []):
        stake = pos.get("stake", 0)
        alpha = pos.get("alpha_balance", 0)
        total += stake
        total_alpha += alpha
        table.add_row(
            f"SN{pos.get('netuid', '?')}",
            format_address(pos.get("hotkey", "")),
            format_tao(stake, symbol=False),
            format_alpha(alpha, symbol=False),
        )

    console.print(table)
    console.print(f"\n[bold]Total Staked:[/bold] {format_tao(total)}")
    if total_alpha > 0:
        console.print(f"[bold]Total Alpha:[/bold] {format_alpha(total_alpha)}")

    return data


async def show_portfolio(
    taostats: TaostatsClient,
    sdk: BittensorSDK,
    wallet_name: Optional[str] = None,
    coldkey: Optional[str] = None,
) -> dict:
    """Show comprehensive portfolio with USD values.

    Args:
        taostats: TaostatsClient instance
        sdk: BittensorSDK instance
        wallet_name: Wallet name (optional)
        coldkey: Coldkey SS58 address (optional, overrides wallet)

    Returns:
        Portfolio data dict
    """
    from rich.panel import Panel

    from taox.ui.theme import Symbols

    settings = get_settings()

    # Resolve coldkey
    if not coldkey:
        if wallet_name:
            wallet = sdk.get_wallet(name=wallet_name)
        else:
            wallet = sdk.get_wallet()
            wallet_name = settings.bittensor.default_wallet

        if wallet:
            coldkey = wallet.coldkey.ss58_address
        else:
            # Demo mode fallback
            coldkey = "5DemoAddress..."
            wallet_name = "demo"

    # Fetch data in parallel
    with console.status("[bold green]Fetching portfolio data..."):
        price_info = await taostats.get_price()
        stake_data = await taostats.get_stake_balance(coldkey)
        balance_info = await sdk.get_balance_async(coldkey)
        subnets = await taostats.get_subnets()
        validators = await taostats.get_validators(limit=100)

    # Build subnet name lookup
    subnet_names = {s.netuid: s.name or f"Subnet {s.netuid}" for s in subnets}

    # Build validator name lookup
    validator_names = {v.hotkey: v.name for v in validators}

    # Calculate totals
    free_balance = balance_info.free
    staked_total = stake_data.get("total_stake", 0)
    positions = stake_data.get("positions", [])

    # Recalculate staked total from positions if needed
    if not staked_total and positions:
        staked_total = sum(p.get("stake", 0) for p in positions)

    total_balance = free_balance + staked_total
    usd_price = price_info.usd
    price_change = price_info.change_24h

    # Price change indicator
    change_color = "success" if price_change >= 0 else "error"
    change_symbol = "+" if price_change >= 0 else ""

    # Header panel
    header = f"""[bold]Wallet:[/bold] {wallet_name or 'N/A'}
[bold]Address:[/bold] {format_address(coldkey, truncate=False)}
[bold]TAO Price:[/bold] [tao]${usd_price:,.2f}[/tao] [{change_color}]({change_symbol}{price_change:.1f}%)[/{change_color}]"""

    console.print(Panel(header, title="[primary]Portfolio Overview[/primary]", box=box.ROUNDED))
    console.print()

    # Balance summary
    balance_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    balance_table.add_column("Label", style="bold")
    balance_table.add_column("TAO", justify="right", style="tao")
    balance_table.add_column("USD", justify="right", style="muted")

    balance_table.add_row(
        f"{Symbols.WALLET} Free Balance",
        f"{free_balance:,.4f} τ",
        f"${free_balance * usd_price:,.2f}",
    )
    balance_table.add_row(
        f"{Symbols.STAKE} Total Staked",
        f"{staked_total:,.4f} τ",
        f"${staked_total * usd_price:,.2f}",
    )
    balance_table.add_row(
        f"{Symbols.STAR} Total Value",
        f"[bold]{total_balance:,.4f} τ[/bold]",
        f"[bold]${total_balance * usd_price:,.2f}[/bold]",
    )

    console.print(balance_table)
    console.print()

    # Stake positions
    if positions:
        pos_table = Table(
            title="[primary]Stake Positions[/primary]",
            box=box.ROUNDED,
            border_style=TaoxColors.BORDER,
        )
        pos_table.add_column("Subnet", style="subnet")
        pos_table.add_column("Validator", style="validator")
        pos_table.add_column("Stake", justify="right", style="tao")
        pos_table.add_column("Alpha", justify="right", style="alpha")
        pos_table.add_column("Value", justify="right", style="muted")
        pos_table.add_column("Share", justify="right", style="info")

        total_alpha = 0.0
        for pos in sorted(positions, key=lambda p: p.get("stake", 0), reverse=True):
            netuid = pos.get("netuid", "?")
            hotkey = pos.get("hotkey", "")
            stake = pos.get("stake", 0)
            alpha_balance = pos.get("alpha_balance", 0)
            total_alpha += alpha_balance

            subnet_names.get(netuid, f"SN{netuid}")
            validator_name = (
                pos.get("hotkey_name") or validator_names.get(hotkey) or format_address(hotkey)
            )
            usd_value = stake * usd_price
            share = (stake / staked_total * 100) if staked_total > 0 else 0

            pos_table.add_row(
                f"SN{netuid}",
                (
                    validator_name[:20] + "..."
                    if len(str(validator_name)) > 20
                    else str(validator_name)
                ),
                f"{stake:,.4f} τ",
                f"{alpha_balance:,.4f} α",
                f"${usd_value:,.2f}",
                f"{share:.1f}%",
            )

        console.print(pos_table)

        # Show alpha summary if there are alpha earnings
        if total_alpha > 0:
            console.print(f"\n[bold]Total Alpha Earned:[/bold] [alpha]{total_alpha:,.4f} α[/alpha]")
    else:
        console.print("[muted]No stake positions found.[/muted]")

    return {
        "wallet_name": wallet_name,
        "coldkey": coldkey,
        "free_balance": free_balance,
        "staked_total": staked_total,
        "total_balance": total_balance,
        "total_alpha": total_alpha if positions else 0.0,
        "usd_price": usd_price,
        "usd_value": total_balance * usd_price,
        "positions": positions,
    }


def stake_wizard(
    executor: BtcliExecutor,
    sdk: BittensorSDK,
    taostats: TaostatsClient,
) -> bool:
    """Interactive stake wizard for guided staking.

    Walks user through:
    1. Selecting a wallet
    2. Choosing a subnet
    3. Picking a validator (with search)
    4. Entering stake amount
    5. Confirming and executing

    Note: This is a synchronous function because InquirerPy prompts
    cannot run inside an async event loop.

    Args:
        executor: BtcliExecutor instance
        sdk: BittensorSDK instance
        taostats: TaostatsClient instance

    Returns:
        True if stake was successful
    """
    import asyncio

    from InquirerPy import inquirer
    from InquirerPy.base.control import Choice
    from rich.panel import Panel

    from taox.ui.theme import Symbols

    settings = get_settings()

    console.print(
        Panel(
            "[bold]Welcome to the Stake Wizard![/bold]\n\n"
            "This wizard will guide you through staking TAO to a validator.",
            title="[primary]Stake Wizard[/primary]",
            box=box.ROUNDED,
        )
    )
    console.print()

    # Step 1: Select wallet
    console.print("[bold]Step 1: Select Wallet[/bold]")
    wallets = sdk.list_wallets()

    if not wallets:
        print_error("No wallets found. Create a wallet first with btcli.")
        return False

    wallet_choices = [
        Choice(value=w.name, name=f"{w.name} ({format_address(w.coldkey_ss58)})") for w in wallets
    ]

    wallet_name = inquirer.select(
        message="Select wallet:",
        choices=wallet_choices,
        pointer=f"{Symbols.ARROW} ",
    ).execute()

    wallet = sdk.get_wallet(name=wallet_name)
    if not wallet:
        print_error(f"Failed to load wallet {wallet_name}")
        return False

    # Get balance (run async in sync context)
    balance = asyncio.run(sdk.get_balance_async(wallet.coldkey.ss58_address))
    console.print(f"[success]Selected: {wallet_name}[/success]")
    console.print(f"[muted]Available balance: {format_tao(balance.free)}[/muted]\n")

    if balance.free < 0.001:
        print_error("Insufficient balance to stake")
        return False

    # Step 2: Select subnet
    console.print("[bold]Step 2: Select Subnet[/bold]")

    with console.status("[bold green]Fetching subnets..."):
        subnets = asyncio.run(taostats.get_subnets())

    subnet_choices = [
        Choice(
            value=s.netuid,
            name=f"SN{s.netuid} - {s.name or 'Unknown'} ({s.emission * 100:.1f}% emission)",
        )
        for s in sorted(subnets, key=lambda x: x.emission, reverse=True)
        if s.netuid > 0  # Exclude root
    ]

    netuid = inquirer.select(
        message="Select subnet:",
        choices=subnet_choices,
        pointer=f"{Symbols.ARROW} ",
    ).execute()

    console.print(f"[success]Selected: Subnet {netuid}[/success]\n")

    # Step 3: Select validator
    console.print("[bold]Step 3: Select Validator[/bold]")

    # Offer search or browse
    search_mode = inquirer.select(
        message="How would you like to find a validator?",
        choices=[
            Choice(value="top", name="Browse top validators"),
            Choice(value="search", name="Search by name"),
        ],
        pointer=f"{Symbols.ARROW} ",
    ).execute()

    if search_mode == "search":
        search_query = inquirer.text(
            message="Enter validator name to search:",
        ).execute()

        with console.status(f"[bold green]Searching for '{search_query}'..."):
            validators = asyncio.run(
                taostats.search_validators(search_query, netuid=netuid, limit=10)
            )

        if not validators:
            console.print("[warning]No validators found. Showing top validators instead.[/warning]")
            validators = asyncio.run(taostats.get_validators(netuid=netuid, limit=10))
    else:
        with console.status("[bold green]Fetching top validators..."):
            validators = asyncio.run(taostats.get_validators(netuid=netuid, limit=10))

    if not validators:
        print_error(f"No validators found on subnet {netuid}")
        return False

    validator_choices = [
        Choice(
            value=v.hotkey,
            name=f"{v.name or 'Unknown'} - {v.stake:,.0f}τ stake, {v.take * 100:.1f}% take",
        )
        for v in validators
    ]

    selected_hotkey = inquirer.select(
        message="Select validator:",
        choices=validator_choices,
        pointer=f"{Symbols.ARROW} ",
    ).execute()

    # Find selected validator details
    selected_validator = next((v for v in validators if v.hotkey == selected_hotkey), None)
    validator_name = selected_validator.name if selected_validator else "Unknown"

    console.print(f"[success]Selected: {validator_name}[/success]")
    console.print(f"[muted]Hotkey: {format_address(selected_hotkey)}[/muted]\n")

    # Step 4: Enter amount
    console.print("[bold]Step 4: Enter Amount[/bold]")
    console.print(f"[muted]Available: {format_tao(balance.free)}[/muted]")

    amount_choice = inquirer.select(
        message="How much would you like to stake?",
        choices=[
            Choice(value="custom", name="Enter custom amount"),
            Choice(value="25", name=f"25% ({balance.free * 0.25:,.4f} τ)"),
            Choice(value="50", name=f"50% ({balance.free * 0.50:,.4f} τ)"),
            Choice(value="75", name=f"75% ({balance.free * 0.75:,.4f} τ)"),
            Choice(value="max", name=f"Maximum ({balance.free - 0.1:,.4f} τ)"),
        ],
        pointer=f"{Symbols.ARROW} ",
    ).execute()

    if amount_choice == "custom":
        amount = float(
            inquirer.number(
                message="Enter amount (TAO):",
                float_allowed=True,
                min_allowed=0.0005,
                max_allowed=float(balance.free - 0.01),
            ).execute()
        )
    elif amount_choice == "max":
        amount = balance.free - 0.1  # Keep some for gas
    else:
        amount = balance.free * (int(amount_choice) / 100)

    console.print(f"[success]Amount: {format_tao(amount)}[/success]\n")

    # Step 5: Confirm and execute
    console.print("[bold]Step 5: Confirm[/bold]")

    # Use safe staking by default
    safe_staking = inquirer.confirm(
        message="Enable MEV protection (recommended)?",
        default=True,
    ).execute()

    # Execute stake (run async in sync context)
    return asyncio.run(
        stake_tao(
            executor=executor,
            sdk=sdk,
            taostats=taostats,
            amount=amount,
            validator_ss58=selected_hotkey,
            netuid=netuid,
            wallet_name=wallet_name,
            safe_staking=safe_staking,
            dry_run=settings.demo_mode,
        )
    )
