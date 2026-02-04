"""Subnet registration operations for taox."""

from typing import Optional

from rich import box
from rich.panel import Panel

from taox.commands.executor import BtcliExecutor
from taox.config.settings import get_settings
from taox.data.sdk import BittensorSDK
from taox.data.taostats import TaostatsClient
from taox.security.confirm import confirm_transaction, show_transaction_preview
from taox.ui.console import console, format_address, format_tao, print_error, print_success
from taox.ui.theme import Symbols, TaoxColors


def build_register_command(
    netuid: int,
    wallet_name: Optional[str] = None,
    hotkey: Optional[str] = None,
) -> dict:
    """Build arguments for burned register command."""
    args = {
        "netuid": netuid,
    }
    if wallet_name:
        args["wallet-name"] = wallet_name
    if hotkey:
        args["hotkey"] = hotkey

    return {
        "group": "subnets",
        "subcommand": "register",
        "args": args,
        "flags": [],
    }


def build_pow_register_command(
    netuid: int,
    wallet_name: Optional[str] = None,
    hotkey: Optional[str] = None,
    num_processes: int = 4,
    update_interval: int = 50000,
) -> dict:
    """Build arguments for PoW register command."""
    args = {
        "netuid": netuid,
        "num-processes": num_processes,
        "update-interval": update_interval,
    }
    if wallet_name:
        args["wallet-name"] = wallet_name
    if hotkey:
        args["hotkey"] = hotkey

    return {
        "group": "subnets",
        "subcommand": "pow-register",
        "args": args,
        "flags": [],
    }


def build_burn_cost_command(netuid: int) -> dict:
    """Build arguments for burn-cost command."""
    return {
        "group": "subnets",
        "subcommand": "burn-cost",
        "args": {"netuid": netuid},
        "flags": [],
    }


async def get_burn_cost(
    executor: BtcliExecutor,
    taostats: TaostatsClient,
    netuid: int,
) -> Optional[float]:
    """Get the registration burn cost for a subnet.

    Args:
        executor: BtcliExecutor instance
        taostats: TaostatsClient instance
        netuid: Subnet ID

    Returns:
        Burn cost in TAO, or None if failed
    """
    # Try to get from taostats first (faster)
    subnet = await taostats.get_subnet(netuid)
    if subnet and subnet.burn_cost > 0:
        return subnet.burn_cost

    # Fallback to btcli
    cmd_info = build_burn_cost_command(netuid)

    with console.status(f"[bold green]Checking registration cost for subnet {netuid}..."):
        result = executor.run(**cmd_info)

    if result.success and result.stdout:
        # Parse the burn cost from output
        try:
            # Expected format: "Burn cost: X.XX TAO"
            for line in result.stdout.split("\n"):
                if "burn" in line.lower() and "tao" in line.lower():
                    parts = line.split()
                    for _i, part in enumerate(parts):
                        try:
                            cost = float(part.replace(",", ""))
                            return cost
                        except ValueError:
                            continue
        except Exception:
            pass

    return None


async def show_registration_info(
    executor: BtcliExecutor,
    taostats: TaostatsClient,
    netuid: int,
) -> None:
    """Show registration information for a subnet.

    Args:
        executor: BtcliExecutor instance
        taostats: TaostatsClient instance
        netuid: Subnet ID
    """
    with console.status(f"[bold green]Fetching subnet {netuid} info..."):
        subnet = await taostats.get_subnet(netuid)
        price_info = await taostats.get_price()

    if not subnet:
        print_error(f"Subnet {netuid} not found")
        return

    burn_cost = subnet.burn_cost
    usd_cost = burn_cost * price_info.usd

    content = f"""[bold]Subnet:[/bold] SN{netuid} - {subnet.name or 'Unknown'}

[bold]Registration Cost:[/bold]
  Burn: [tao]{format_tao(burn_cost)}[/tao] [dim](≈${usd_cost:,.2f})[/dim]

[bold]Subnet Info:[/bold]
  Emission: [green]{subnet.emission * 100:.2f}%[/green]
  Tempo: {subnet.tempo} blocks
  Validators: {subnet.validators}
  Total Stake: {format_tao(subnet.total_stake)}"""

    console.print(
        Panel(
            content,
            title=f"[primary]{Symbols.INFO} Registration Info[/primary]",
            border_style=TaoxColors.PRIMARY,
            box=box.ROUNDED,
        )
    )


async def register_burned(
    executor: BtcliExecutor,
    sdk: BittensorSDK,
    taostats: TaostatsClient,
    netuid: int,
    wallet_name: Optional[str] = None,
    hotkey_name: Optional[str] = None,
    skip_confirm: bool = False,
    dry_run: bool = False,
) -> bool:
    """Register on a subnet using burned registration.

    Args:
        executor: BtcliExecutor instance
        sdk: BittensorSDK instance
        taostats: TaostatsClient instance
        netuid: Subnet ID
        wallet_name: Wallet name
        hotkey_name: Hotkey name
        skip_confirm: Skip confirmation prompt
        dry_run: Show command without executing

    Returns:
        True if successful
    """
    settings = get_settings()
    wallet_name = wallet_name or settings.bittensor.default_wallet
    hotkey_name = hotkey_name or settings.bittensor.default_hotkey

    # Get subnet info and burn cost
    with console.status(f"[bold green]Checking registration cost for subnet {netuid}..."):
        subnet = await taostats.get_subnet(netuid)
        price_info = await taostats.get_price()

    if not subnet:
        print_error(f"Subnet {netuid} not found")
        return False

    burn_cost = subnet.burn_cost
    usd_cost = burn_cost * price_info.usd

    # Check wallet balance
    wallet = sdk.get_wallet(name=wallet_name)
    if wallet:
        balance = await sdk.get_balance_async(wallet.coldkey.ss58_address)
        if balance.free < burn_cost:
            print_error(
                f"Insufficient balance. Need {format_tao(burn_cost)}, have {format_tao(balance.free)}"
            )
            return False
    else:
        console.print("[warning]Could not verify balance (demo mode)[/warning]")

    # Show registration info
    console.print(
        Panel(
            f"[bold]Subnet:[/bold] SN{netuid} - {subnet.name or 'Unknown'}\n"
            f"[bold]Burn Cost:[/bold] {format_tao(burn_cost)} [dim](≈${usd_cost:,.2f})[/dim]\n"
            f"[bold]Emission:[/bold] {subnet.emission * 100:.2f}%",
            title=f"[warning]{Symbols.WARN} Registration Cost[/warning]",
            border_style=TaoxColors.WARNING,
            box=box.ROUNDED,
        )
    )

    cmd_info = build_register_command(
        netuid=netuid,
        wallet_name=wallet_name,
        hotkey=hotkey_name,
    )

    show_transaction_preview(
        command=executor.get_command_string(**cmd_info),
        description=f"Register on subnet {netuid} by burning {burn_cost:.4f} TAO",
        dry_run=dry_run,
    )

    if dry_run:
        return True

    # Confirm
    if not confirm_transaction(
        action="Burned Registration",
        amount=burn_cost,
        netuid=netuid,
        extra_info={
            "Subnet": f"{subnet.name or 'Unknown'}",
            "Wallet": wallet_name,
            "Hotkey": hotkey_name or "default",
        },
        skip_confirm=skip_confirm,
    ):
        console.print("[muted]Registration cancelled.[/muted]")
        return False

    # Execute
    with console.status("[bold green]Executing registration..."):
        result = executor.run(**cmd_info)

    if result.success:
        print_success(f"Registered on subnet {netuid}!")
        if result.stdout:
            console.print(f"[muted]{result.stdout}[/muted]")
        return True
    else:
        print_error(f"Registration failed: {result.stderr}")
        return False


async def register_pow(
    executor: BtcliExecutor,
    sdk: BittensorSDK,
    netuid: int,
    wallet_name: Optional[str] = None,
    hotkey_name: Optional[str] = None,
    num_processes: int = 4,
    skip_confirm: bool = False,
) -> bool:
    """Register on a subnet using proof-of-work.

    Args:
        executor: BtcliExecutor instance
        sdk: BittensorSDK instance
        netuid: Subnet ID
        wallet_name: Wallet name
        hotkey_name: Hotkey name
        num_processes: Number of CPU processes to use
        skip_confirm: Skip confirmation prompt

    Returns:
        True if successful
    """
    settings = get_settings()
    wallet_name = wallet_name or settings.bittensor.default_wallet
    hotkey_name = hotkey_name or settings.bittensor.default_hotkey

    console.print(
        Panel(
            "[bold]Proof-of-Work Registration[/bold]\n\n"
            "This will use your CPU to solve a computational puzzle.\n"
            "The process can take anywhere from minutes to hours depending\n"
            "on the subnet's difficulty and your hardware.",
            title=f"[warning]{Symbols.WARN} PoW Registration[/warning]",
            border_style=TaoxColors.WARNING,
            box=box.ROUNDED,
        )
    )

    cmd_info = build_pow_register_command(
        netuid=netuid,
        wallet_name=wallet_name,
        hotkey=hotkey_name,
        num_processes=num_processes,
    )

    show_transaction_preview(
        command=executor.get_command_string(**cmd_info),
        description=f"PoW register on subnet {netuid} using {num_processes} processes",
        dry_run=False,
    )

    # Confirm
    from InquirerPy import inquirer

    if not skip_confirm:
        confirm = inquirer.confirm(
            message=f"Start PoW registration on subnet {netuid}?",
            default=False,
        ).execute()

        if not confirm:
            console.print("[muted]Registration cancelled.[/muted]")
            return False

    # Execute (this can take a long time)
    console.print("[bold green]Starting PoW mining...[/bold green]")
    console.print("[dim]Press Ctrl+C to cancel[/dim]\n")

    result = executor.run(**cmd_info, timeout=3600)  # 1 hour timeout

    if result.success:
        print_success(f"Registered on subnet {netuid} via PoW!")
        if result.stdout:
            console.print(f"[muted]{result.stdout}[/muted]")
        return True
    else:
        print_error(f"PoW registration failed: {result.stderr}")
        return False


def register_wizard(
    executor: BtcliExecutor,
    sdk: BittensorSDK,
    taostats: TaostatsClient,
) -> bool:
    """Interactive wizard for subnet registration.

    Args:
        executor: BtcliExecutor instance
        sdk: BittensorSDK instance
        taostats: TaostatsClient instance

    Returns:
        True if registration was successful
    """
    import asyncio

    from InquirerPy import inquirer
    from InquirerPy.base.control import Choice

    settings = get_settings()

    console.print(
        Panel(
            "[bold]Welcome to the Registration Wizard![/bold]\n\n"
            "This wizard will guide you through registering on a Bittensor subnet.",
            title="[primary]Registration Wizard[/primary]",
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

    balance = asyncio.run(sdk.get_balance_async(wallet.coldkey.ss58_address))
    console.print(f"[success]Selected: {wallet_name}[/success]")
    console.print(f"[muted]Balance: {format_tao(balance.free)}[/muted]\n")

    # Step 2: Select subnet
    console.print("[bold]Step 2: Select Subnet[/bold]")

    with console.status("[bold green]Fetching subnets..."):
        subnets = asyncio.run(taostats.get_subnets())

    subnet_choices = [
        Choice(
            value=s.netuid,
            name=f"SN{s.netuid} - {s.name or 'Unknown'} ({s.emission * 100:.1f}% emission, {format_tao(s.burn_cost)} burn)",
        )
        for s in sorted(subnets, key=lambda x: x.emission, reverse=True)
        if s.netuid > 0
    ]

    netuid = inquirer.select(
        message="Select subnet to register on:",
        choices=subnet_choices,
        pointer=f"{Symbols.ARROW} ",
    ).execute()

    # Show subnet details
    subnet = next((s for s in subnets if s.netuid == netuid), None)
    if subnet:
        console.print(f"[success]Selected: SN{netuid} - {subnet.name or 'Unknown'}[/success]")
        console.print(f"[muted]Burn cost: {format_tao(subnet.burn_cost)}[/muted]\n")

    # Step 3: Select registration method
    console.print("[bold]Step 3: Select Registration Method[/bold]")

    can_afford = balance.free >= (subnet.burn_cost if subnet else 0)

    method_choices = [
        Choice(
            value="burn",
            name=f"Burned registration (costs {format_tao(subnet.burn_cost if subnet else 0)})"
            + (
                " [green](affordable)[/green]"
                if can_afford
                else " [red](insufficient balance)[/red]"
            ),
        ),
        Choice(value="pow", name="Proof-of-Work registration (free but takes time)"),
    ]

    method = inquirer.select(
        message="Select registration method:",
        choices=method_choices,
        pointer=f"{Symbols.ARROW} ",
    ).execute()

    # Step 4: Select hotkey
    console.print("[bold]Step 4: Select Hotkey[/bold]")

    hotkey_name = (
        inquirer.text(
            message="Enter hotkey name (or press Enter for 'default'):",
            default="default",
        ).execute()
        or "default"
    )

    console.print(f"[success]Using hotkey: {hotkey_name}[/success]\n")

    # Execute registration
    console.print("[bold]Step 5: Execute Registration[/bold]")

    if method == "burn":
        if not can_afford and not settings.demo_mode:
            print_error(
                f"Insufficient balance. Need {format_tao(subnet.burn_cost if subnet else 0)}"
            )
            return False

        return asyncio.run(
            register_burned(
                executor=executor,
                sdk=sdk,
                taostats=taostats,
                netuid=netuid,
                wallet_name=wallet_name,
                hotkey_name=hotkey_name,
                dry_run=settings.demo_mode,
            )
        )
    else:
        num_processes = int(
            inquirer.number(
                message="Number of CPU processes to use:",
                default=4,
                min_allowed=1,
                max_allowed=32,
            ).execute()
        )

        return asyncio.run(
            register_pow(
                executor=executor,
                sdk=sdk,
                netuid=netuid,
                wallet_name=wallet_name,
                hotkey_name=hotkey_name,
                num_processes=num_processes,
            )
        )
