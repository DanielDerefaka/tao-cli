"""Child hotkey management operations for taox."""

from typing import Optional

from rich import box
from rich.panel import Panel

from taox.commands.executor import BtcliExecutor, CommandResult
from taox.config.settings import get_settings
from taox.data.sdk import BittensorSDK
from taox.security.confirm import confirm_transaction, show_transaction_preview
from taox.ui.console import console, format_address, print_error, print_success
from taox.ui.theme import Symbols


def build_child_get_command(
    hotkey: str,
    netuid: int,
    wallet_name: Optional[str] = None,
) -> dict:
    """Build arguments for child get command."""
    args = {
        "hotkey": hotkey,
        "netuid": netuid,
    }
    if wallet_name:
        args["wallet-name"] = wallet_name

    return {
        "group": "stake",
        "subcommand": "child",
        "args": args,
        "flags": ["get"],
    }


def build_child_set_command(
    hotkey: str,
    child_hotkey: str,
    netuid: int,
    proportion: float,
    wallet_name: Optional[str] = None,
) -> dict:
    """Build arguments for child set command.

    Args:
        hotkey: Parent hotkey
        child_hotkey: Child hotkey to set
        netuid: Subnet ID
        proportion: Proportion of stake to delegate (0.0 - 1.0)
        wallet_name: Wallet name
    """
    args = {
        "hotkey": hotkey,
        "child": child_hotkey,
        "netuid": netuid,
        "proportion": proportion,
    }
    if wallet_name:
        args["wallet-name"] = wallet_name

    return {
        "group": "stake",
        "subcommand": "child",
        "args": args,
        "flags": ["set"],
    }


def build_child_revoke_command(
    hotkey: str,
    child_hotkey: str,
    netuid: int,
    wallet_name: Optional[str] = None,
) -> dict:
    """Build arguments for child revoke command."""
    args = {
        "hotkey": hotkey,
        "child": child_hotkey,
        "netuid": netuid,
    }
    if wallet_name:
        args["wallet-name"] = wallet_name

    return {
        "group": "stake",
        "subcommand": "child",
        "args": args,
        "flags": ["revoke"],
    }


def build_child_take_command(
    hotkey: str,
    netuid: int,
    take: float,
    wallet_name: Optional[str] = None,
) -> dict:
    """Build arguments for child take command.

    Args:
        hotkey: Hotkey to set take for
        netuid: Subnet ID
        take: Take rate (0.0 - 0.18, i.e., 0% - 18%)
        wallet_name: Wallet name
    """
    args = {
        "hotkey": hotkey,
        "netuid": netuid,
        "take": take,
    }
    if wallet_name:
        args["wallet-name"] = wallet_name

    return {
        "group": "stake",
        "subcommand": "child",
        "args": args,
        "flags": ["take"],
    }


async def get_child_hotkeys(
    executor: BtcliExecutor,
    sdk: BittensorSDK,
    hotkey: Optional[str] = None,
    netuid: Optional[int] = None,
    wallet_name: Optional[str] = None,
) -> CommandResult:
    """Get child hotkey information.

    Args:
        executor: BtcliExecutor instance
        sdk: BittensorSDK instance
        hotkey: Hotkey to check (uses wallet's hotkey if not specified)
        netuid: Subnet ID (required)
        wallet_name: Wallet name

    Returns:
        CommandResult with child hotkey information
    """
    settings = get_settings()
    wallet_name = wallet_name or settings.bittensor.default_wallet

    # Resolve hotkey if not provided
    if not hotkey:
        wallet = sdk.get_wallet(name=wallet_name)
        if wallet and wallet.hotkey:
            hotkey = wallet.hotkey.ss58_address
        else:
            print_error("No hotkey specified and no wallet hotkey found")
            return CommandResult(
                success=False,
                stdout="",
                stderr="No hotkey available",
                return_code=-1,
                command=[],
            )

    if netuid is None:
        print_error("Subnet ID (--netuid) is required")
        return CommandResult(
            success=False,
            stdout="",
            stderr="Subnet ID required",
            return_code=-1,
            command=[],
        )

    cmd_info = build_child_get_command(
        hotkey=hotkey,
        netuid=netuid,
        wallet_name=wallet_name,
    )

    show_transaction_preview(
        command=executor.get_command_string(**cmd_info),
        description=f"Get child hotkeys for {format_address(hotkey)} on subnet {netuid}",
        dry_run=True,
    )

    with console.status("[bold green]Fetching child hotkey information..."):
        result = executor.run(**cmd_info)

    if result.success:
        console.print("\n[success]Child hotkey information:[/success]")
        if result.stdout:
            console.print(result.stdout)
        else:
            console.print("[muted]No child hotkeys configured[/muted]")
    else:
        print_error(f"Failed to get child hotkeys: {result.stderr}")

    return result


async def set_child_hotkey(
    executor: BtcliExecutor,
    sdk: BittensorSDK,
    child_hotkey: str,
    netuid: int,
    proportion: float = 1.0,
    hotkey: Optional[str] = None,
    wallet_name: Optional[str] = None,
    skip_confirm: bool = False,
    dry_run: bool = False,
) -> bool:
    """Set a child hotkey to receive delegated stake.

    Args:
        executor: BtcliExecutor instance
        sdk: BittensorSDK instance
        child_hotkey: Child hotkey SS58 address
        netuid: Subnet ID
        proportion: Proportion of stake to delegate (0.0 - 1.0)
        hotkey: Parent hotkey (uses wallet's hotkey if not specified)
        wallet_name: Wallet name
        skip_confirm: Skip confirmation prompt
        dry_run: Show command without executing

    Returns:
        True if successful
    """
    settings = get_settings()
    wallet_name = wallet_name or settings.bittensor.default_wallet

    # Validate proportion
    if proportion < 0 or proportion > 1:
        print_error("Proportion must be between 0.0 and 1.0")
        return False

    # Resolve hotkey if not provided
    if not hotkey:
        wallet = sdk.get_wallet(name=wallet_name)
        if wallet and wallet.hotkey:
            hotkey = wallet.hotkey.ss58_address
        else:
            print_error("No hotkey specified and no wallet hotkey found")
            return False

    cmd_info = build_child_set_command(
        hotkey=hotkey,
        child_hotkey=child_hotkey,
        netuid=netuid,
        proportion=proportion,
        wallet_name=wallet_name,
    )

    show_transaction_preview(
        command=executor.get_command_string(**cmd_info),
        description=f"Set child hotkey with {proportion * 100:.0f}% stake delegation",
        dry_run=dry_run,
    )

    if dry_run:
        return True

    # Confirm
    if not confirm_transaction(
        action="Set Child Hotkey",
        to_address=child_hotkey,
        netuid=netuid,
        extra_info={
            "Parent Hotkey": format_address(hotkey),
            "Proportion": f"{proportion * 100:.0f}%",
        },
        skip_confirm=skip_confirm,
    ):
        console.print("[muted]Operation cancelled.[/muted]")
        return False

    with console.status("[bold green]Setting child hotkey..."):
        result = executor.run(**cmd_info)

    if result.success:
        print_success(f"Set child hotkey {format_address(child_hotkey)} on subnet {netuid}")
        if result.stdout:
            console.print(f"[muted]{result.stdout}[/muted]")
        return True
    else:
        print_error(f"Failed to set child hotkey: {result.stderr}")
        return False


async def revoke_child_hotkey(
    executor: BtcliExecutor,
    sdk: BittensorSDK,
    child_hotkey: str,
    netuid: int,
    hotkey: Optional[str] = None,
    wallet_name: Optional[str] = None,
    skip_confirm: bool = False,
    dry_run: bool = False,
) -> bool:
    """Revoke a child hotkey's stake delegation.

    Args:
        executor: BtcliExecutor instance
        sdk: BittensorSDK instance
        child_hotkey: Child hotkey SS58 address to revoke
        netuid: Subnet ID
        hotkey: Parent hotkey (uses wallet's hotkey if not specified)
        wallet_name: Wallet name
        skip_confirm: Skip confirmation prompt
        dry_run: Show command without executing

    Returns:
        True if successful
    """
    settings = get_settings()
    wallet_name = wallet_name or settings.bittensor.default_wallet

    # Resolve hotkey if not provided
    if not hotkey:
        wallet = sdk.get_wallet(name=wallet_name)
        if wallet and wallet.hotkey:
            hotkey = wallet.hotkey.ss58_address
        else:
            print_error("No hotkey specified and no wallet hotkey found")
            return False

    cmd_info = build_child_revoke_command(
        hotkey=hotkey,
        child_hotkey=child_hotkey,
        netuid=netuid,
        wallet_name=wallet_name,
    )

    show_transaction_preview(
        command=executor.get_command_string(**cmd_info),
        description=f"Revoke child hotkey {format_address(child_hotkey)}",
        dry_run=dry_run,
    )

    if dry_run:
        return True

    # Confirm
    if not confirm_transaction(
        action="Revoke Child Hotkey",
        from_address=child_hotkey,
        netuid=netuid,
        extra_info={
            "Parent Hotkey": format_address(hotkey),
        },
        skip_confirm=skip_confirm,
    ):
        console.print("[muted]Operation cancelled.[/muted]")
        return False

    with console.status("[bold green]Revoking child hotkey..."):
        result = executor.run(**cmd_info)

    if result.success:
        print_success(f"Revoked child hotkey {format_address(child_hotkey)} on subnet {netuid}")
        if result.stdout:
            console.print(f"[muted]{result.stdout}[/muted]")
        return True
    else:
        print_error(f"Failed to revoke child hotkey: {result.stderr}")
        return False


async def set_child_take(
    executor: BtcliExecutor,
    sdk: BittensorSDK,
    netuid: int,
    take: float,
    hotkey: Optional[str] = None,
    wallet_name: Optional[str] = None,
    skip_confirm: bool = False,
    dry_run: bool = False,
) -> bool:
    """Set the take rate for child hotkey delegations.

    Args:
        executor: BtcliExecutor instance
        sdk: BittensorSDK instance
        netuid: Subnet ID
        take: Take rate (0.0 - 0.18, i.e., 0% - 18%)
        hotkey: Hotkey to set take for (uses wallet's hotkey if not specified)
        wallet_name: Wallet name
        skip_confirm: Skip confirmation prompt
        dry_run: Show command without executing

    Returns:
        True if successful
    """
    settings = get_settings()
    wallet_name = wallet_name or settings.bittensor.default_wallet

    # Validate take rate
    if take < 0 or take > 0.18:
        print_error("Take rate must be between 0.0 and 0.18 (0% - 18%)")
        return False

    # Resolve hotkey if not provided
    if not hotkey:
        wallet = sdk.get_wallet(name=wallet_name)
        if wallet and wallet.hotkey:
            hotkey = wallet.hotkey.ss58_address
        else:
            print_error("No hotkey specified and no wallet hotkey found")
            return False

    cmd_info = build_child_take_command(
        hotkey=hotkey,
        netuid=netuid,
        take=take,
        wallet_name=wallet_name,
    )

    show_transaction_preview(
        command=executor.get_command_string(**cmd_info),
        description=f"Set child take rate to {take * 100:.1f}%",
        dry_run=dry_run,
    )

    if dry_run:
        return True

    # Confirm
    if not confirm_transaction(
        action="Set Child Take Rate",
        netuid=netuid,
        extra_info={
            "Hotkey": format_address(hotkey),
            "Take Rate": f"{take * 100:.1f}%",
        },
        skip_confirm=skip_confirm,
    ):
        console.print("[muted]Operation cancelled.[/muted]")
        return False

    with console.status("[bold green]Setting child take rate..."):
        result = executor.run(**cmd_info)

    if result.success:
        print_success(f"Set child take rate to {take * 100:.1f}% on subnet {netuid}")
        if result.stdout:
            console.print(f"[muted]{result.stdout}[/muted]")
        return True
    else:
        print_error(f"Failed to set child take rate: {result.stderr}")
        return False


def child_wizard(
    executor: BtcliExecutor,
    sdk: BittensorSDK,
) -> bool:
    """Interactive wizard for child hotkey management.

    Args:
        executor: BtcliExecutor instance
        sdk: BittensorSDK instance

    Returns:
        True if operation was successful
    """
    import asyncio

    from InquirerPy import inquirer
    from InquirerPy.base.control import Choice

    settings = get_settings()

    console.print(
        Panel(
            "[bold]Child Hotkey Management[/bold]\n\n"
            "Manage child hotkeys for stake delegation. Child hotkeys can receive\n"
            "a portion of your stake's emissions on a subnet.",
            title="[primary]Child Hotkey Wizard[/primary]",
            box=box.ROUNDED,
        )
    )
    console.print()

    # Step 1: Select action
    action = inquirer.select(
        message="What would you like to do?",
        choices=[
            Choice(value="get", name="View child hotkeys"),
            Choice(value="set", name="Set a child hotkey"),
            Choice(value="revoke", name="Revoke a child hotkey"),
            Choice(value="take", name="Set child take rate"),
        ],
        pointer=f"{Symbols.ARROW} ",
    ).execute()

    # Step 2: Select wallet
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
    if not wallet or not wallet.hotkey:
        print_error(f"Wallet {wallet_name} has no hotkey")
        return False

    hotkey = wallet.hotkey.ss58_address
    console.print(f"[success]Using hotkey: {format_address(hotkey)}[/success]\n")

    # Step 3: Enter subnet ID
    netuid = int(
        inquirer.number(
            message="Enter subnet ID:",
            min_allowed=1,
            default=1,
        ).execute()
    )

    # Execute based on action
    if action == "get":
        asyncio.run(
            get_child_hotkeys(
                executor=executor,
                sdk=sdk,
                hotkey=hotkey,
                netuid=netuid,
                wallet_name=wallet_name,
            )
        )
        return True

    elif action == "set":
        child_hotkey = inquirer.text(
            message="Enter child hotkey SS58 address:",
        ).execute()

        if not child_hotkey or len(child_hotkey) < 40:
            print_error("Invalid hotkey address")
            return False

        proportion = (
            float(
                inquirer.number(
                    message="Enter stake proportion (0-100%):",
                    float_allowed=True,
                    min_allowed=0,
                    max_allowed=100,
                    default=100,
                ).execute()
            )
            / 100
        )

        return asyncio.run(
            set_child_hotkey(
                executor=executor,
                sdk=sdk,
                child_hotkey=child_hotkey,
                netuid=netuid,
                proportion=proportion,
                hotkey=hotkey,
                wallet_name=wallet_name,
                dry_run=settings.demo_mode,
            )
        )

    elif action == "revoke":
        child_hotkey = inquirer.text(
            message="Enter child hotkey SS58 address to revoke:",
        ).execute()

        if not child_hotkey or len(child_hotkey) < 40:
            print_error("Invalid hotkey address")
            return False

        return asyncio.run(
            revoke_child_hotkey(
                executor=executor,
                sdk=sdk,
                child_hotkey=child_hotkey,
                netuid=netuid,
                hotkey=hotkey,
                wallet_name=wallet_name,
                dry_run=settings.demo_mode,
            )
        )

    elif action == "take":
        take = (
            float(
                inquirer.number(
                    message="Enter take rate (0-18%):",
                    float_allowed=True,
                    min_allowed=0,
                    max_allowed=18,
                    default=9,
                ).execute()
            )
            / 100
        )

        return asyncio.run(
            set_child_take(
                executor=executor,
                sdk=sdk,
                netuid=netuid,
                take=take,
                hotkey=hotkey,
                wallet_name=wallet_name,
                dry_run=settings.demo_mode,
            )
        )

    return False
