"""Main CLI entry point for taox."""

import asyncio
import sys
from typing import Optional

import typer
from rich.panel import Panel
from rich import box

from taox import __version__, __app_name__
from taox.ui.console import console, print_welcome, print_error, print_success, print_info
from taox.ui.theme import TaoxColors, Symbols
from taox.ui.prompts import select_action, input_amount, input_netuid, confirm
from taox.config.settings import get_settings, create_default_config, reset_settings_cache
from taox.security.credentials import CredentialManager, setup_secure_logging
from taox.chat.llm import LLMClient
from taox.chat.context import ConversationContext
from taox.chat.intents import IntentType, parse_intent
from taox.data.taostats import TaostatsClient
from taox.data.sdk import BittensorSDK
from taox.commands.executor import BtcliExecutor
from taox.commands import wallet as wallet_cmds
from taox.commands import stake as stake_cmds
from taox.commands import subnet as subnet_cmds


# Create Typer app
app = typer.Typer(
    name=__app_name__,
    help="AI-powered conversational CLI for Bittensor",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


def version_callback(value: bool):
    """Print version and exit."""
    if value:
        console.print(f"[primary]{__app_name__}[/primary] version [tao]{__version__}[/tao]")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True,
        help="Show version and exit",
    ),
    demo: bool = typer.Option(
        False, "--demo", help="Run in demo mode (no real API calls or transactions)",
    ),
):
    """taox - AI-powered CLI for Bittensor."""
    # Create default config if needed
    create_default_config()

    # Set demo mode if requested
    if demo:
        import os
        os.environ["TAOX_DEMO_MODE"] = "true"
        reset_settings_cache()

    # Setup secure logging
    setup_secure_logging()


@app.command()
def chat(
    message: Optional[str] = typer.Argument(None, help="Initial message (optional)"),
):
    """Start interactive chat mode.

    Have a conversation with taox to manage your Bittensor operations.

    [green]Examples:[/green]
        taox chat
        taox chat "what is my balance?"
        taox chat "stake 10 TAO to taostats on subnet 1"
    """
    asyncio.run(_chat_loop(message))


async def _chat_loop(initial_message: Optional[str] = None):
    """Main chat loop."""
    settings = get_settings()

    # Initialize clients
    llm = LLMClient()
    taostats = TaostatsClient()
    sdk = BittensorSDK()
    executor = BtcliExecutor()
    context = ConversationContext()

    # Show welcome
    print_welcome()

    if settings.demo_mode:
        console.print("[warning]Running in demo mode - no real transactions will be executed[/warning]\n")

    if not llm.is_available:
        console.print("[muted]LLM not available - using pattern matching for commands[/muted]")
        console.print("[muted]Run 'taox setup' to configure API keys for full AI support[/muted]\n")

    console.print("[muted]Type 'help' for available commands, 'quit' to exit[/muted]\n")

    # Process initial message if provided
    if initial_message:
        await _process_message(initial_message, llm, taostats, sdk, executor, context)

    # Main loop
    while True:
        try:
            # Get input
            user_input = console.input("[prompt]You:[/prompt] ").strip()

            if not user_input:
                continue

            # Check for quit
            if user_input.lower() in ("quit", "exit", "q"):
                console.print("[muted]Goodbye![/muted]")
                break

            # Check for clear
            if user_input.lower() == "clear":
                context.clear()
                console.clear()
                print_welcome()
                continue

            # Process message
            await _process_message(user_input, llm, taostats, sdk, executor, context)

        except KeyboardInterrupt:
            console.print("\n[muted]Use 'quit' to exit[/muted]")
        except EOFError:
            break

    # Cleanup
    await taostats.close()


async def _process_message(
    user_input: str,
    llm: LLMClient,
    taostats: TaostatsClient,
    sdk: BittensorSDK,
    executor: BtcliExecutor,
    context: ConversationContext,
):
    """Process a single user message."""
    settings = get_settings()

    # Parse intent
    intent = llm.parse_intent(user_input, context)
    intent = context.resolve_follow_up(intent)

    # Add to history
    context.add_user_message(user_input, intent)

    console.print()

    # Handle based on intent type
    if intent.type == IntentType.BALANCE:
        await wallet_cmds.show_balance(sdk, wallet_name=intent.wallet_name)

    elif intent.type == IntentType.PORTFOLIO:
        wallet = sdk.get_wallet(name=intent.wallet_name)
        if wallet:
            await stake_cmds.show_stake_positions(taostats, wallet.coldkey.ss58_address)
        else:
            # Demo mode fallback
            await stake_cmds.show_stake_positions(taostats, "5Demo...")

    elif intent.type == IntentType.STAKE:
        if intent.amount is None and not intent.amount_all:
            intent.amount = input_amount("How much TAO to stake")

        if intent.netuid is None:
            intent.netuid = input_netuid("Which subnet", default=1)

        await stake_cmds.stake_tao(
            executor=executor,
            sdk=sdk,
            taostats=taostats,
            amount=intent.amount or 0,
            validator_name=intent.validator_name,
            validator_ss58=intent.validator_ss58,
            netuid=intent.netuid,
            wallet_name=intent.wallet_name,
            dry_run=settings.demo_mode,
        )

    elif intent.type == IntentType.UNSTAKE:
        if intent.amount is None:
            intent.amount = input_amount("How much TAO to unstake")

        if intent.netuid is None:
            intent.netuid = input_netuid("From which subnet", default=1)

        # Need hotkey - in a real impl would show current positions
        console.print("[warning]Unstake requires specifying the validator hotkey[/warning]")
        console.print("[muted]Use: 'unstake X TAO from <hotkey> on subnet Y'[/muted]")

    elif intent.type == IntentType.TRANSFER:
        if intent.amount is None:
            intent.amount = input_amount("How much TAO to transfer")

        if intent.destination is None:
            from taox.ui.prompts import input_address
            intent.destination = input_address("Destination address")

        await wallet_cmds.transfer_tao(
            executor=executor,
            sdk=sdk,
            amount=intent.amount,
            destination=intent.destination,
            wallet_name=intent.wallet_name,
            dry_run=settings.demo_mode,
        )

    elif intent.type == IntentType.VALIDATORS:
        await stake_cmds.show_validators(taostats, netuid=intent.netuid)

    elif intent.type == IntentType.SUBNETS:
        await subnet_cmds.list_subnets(taostats)

    elif intent.type == IntentType.METAGRAPH:
        if intent.netuid is None:
            intent.netuid = input_netuid("Which subnet", default=1)
        await subnet_cmds.show_metagraph(sdk, executor, intent.netuid)

    elif intent.type == IntentType.HELP:
        _show_help()

    elif intent.type == IntentType.INFO or intent.type == IntentType.UNKNOWN:
        # Use LLM for general responses or get mock response
        response = llm.chat(user_input, context)
        console.print(f"[info]{response}[/info]")

    else:
        console.print(f"[muted]Intent: {intent}[/muted]")

    # Add assistant response placeholder to context
    context.add_assistant_message("(response)")
    console.print()


def _show_help():
    """Display help information."""
    help_text = """
[primary]Available Commands:[/primary]

[bold]Balance & Portfolio:[/bold]
  • "what is my balance?" - Check your TAO balance
  • "show my portfolio" - View all stake positions
  • "show my stakes" - Same as portfolio

[bold]Staking:[/bold]
  • "stake 10 TAO to taostats on subnet 1" - Stake to a validator
  • "stake 50 TAO to the top validator" - Stake to highest-ranked
  • "unstake 5 TAO from subnet 1" - Remove stake

[bold]Transfers:[/bold]
  • "send 10 TAO to 5xxx..." - Transfer to an address
  • "transfer 5 TAO to 5xxx..." - Same as send

[bold]Network Info:[/bold]
  • "show validators on subnet 1" - List top validators
  • "list subnets" - Show all subnets
  • "show metagraph for subnet 18" - View subnet metagraph

[bold]Other:[/bold]
  • "help" - Show this help
  • "clear" - Clear conversation
  • "quit" - Exit taox
"""
    console.print(Panel(help_text, title="[primary]taox Help[/primary]", box=box.ROUNDED))


@app.command()
def setup():
    """Configure taox API keys and settings.

    Securely stores API keys in your system keyring.
    """
    console.print("[primary]taox Setup[/primary]\n")

    # Chutes API key
    console.print("[bold]1. Chutes AI API Key[/bold]")
    console.print("[muted]Get your key at: https://chutes.ai[/muted]")

    existing_chutes = CredentialManager.get_chutes_key()
    if existing_chutes:
        console.print(f"[success]Current key: {existing_chutes[:8]}...{existing_chutes[-4:]}[/success]")
        if not confirm("Update Chutes API key?"):
            console.print("[muted]Keeping existing key[/muted]\n")
        else:
            chutes_key = typer.prompt("Enter Chutes API key", hide_input=True)
            if chutes_key:
                CredentialManager.set_chutes_key(chutes_key)
                print_success("Chutes API key saved")
    else:
        chutes_key = typer.prompt("Enter Chutes API key (or press Enter to skip)", default="", hide_input=True)
        if chutes_key:
            CredentialManager.set_chutes_key(chutes_key)
            print_success("Chutes API key saved")
        else:
            console.print("[muted]Skipped - will use pattern matching mode[/muted]\n")

    # Taostats API key
    console.print("\n[bold]2. Taostats API Key[/bold]")
    console.print("[muted]Get your key at: https://dash.taostats.io[/muted]")

    existing_taostats = CredentialManager.get_taostats_key()
    if existing_taostats:
        console.print(f"[success]Current key: {existing_taostats[:8]}...{existing_taostats[-4:]}[/success]")
        if not confirm("Update Taostats API key?"):
            console.print("[muted]Keeping existing key[/muted]\n")
        else:
            taostats_key = typer.prompt("Enter Taostats API key", hide_input=True)
            if taostats_key:
                CredentialManager.set_taostats_key(taostats_key)
                print_success("Taostats API key saved")
    else:
        taostats_key = typer.prompt("Enter Taostats API key (or press Enter to skip)", default="", hide_input=True)
        if taostats_key:
            CredentialManager.set_taostats_key(taostats_key)
            print_success("Taostats API key saved")
        else:
            console.print("[muted]Skipped - will use mock data[/muted]\n")

    print_success("\nSetup complete!")
    console.print("[muted]Run 'taox chat' to start chatting[/muted]")


@app.command()
def balance(
    wallet_name: Optional[str] = typer.Option(None, "--wallet", "-w", help="Wallet name"),
    address: Optional[str] = typer.Option(None, "--address", "-a", help="SS58 address"),
):
    """Check TAO balance.

    [green]Examples:[/green]
        taox balance
        taox balance --wallet my_wallet
        taox balance --address 5xxx...
    """
    sdk = BittensorSDK()
    asyncio.run(wallet_cmds.show_balance(sdk, wallet_name=wallet_name, address=address))


@app.command()
def wallets():
    """List all wallets.

    [green]Example:[/green]
        taox wallets
    """
    sdk = BittensorSDK()
    asyncio.run(wallet_cmds.list_wallets(sdk))


@app.command()
def validators(
    netuid: Optional[int] = typer.Option(None, "--netuid", "-n", help="Subnet ID"),
    limit: int = typer.Option(10, "--limit", "-l", help="Number of validators to show"),
):
    """Show top validators.

    [green]Examples:[/green]
        taox validators
        taox validators --netuid 1
        taox validators -n 18 -l 20
    """
    taostats = TaostatsClient()
    asyncio.run(stake_cmds.show_validators(taostats, netuid=netuid, limit=limit))


@app.command()
def subnets():
    """List all subnets.

    [green]Example:[/green]
        taox subnets
    """
    taostats = TaostatsClient()
    asyncio.run(subnet_cmds.list_subnets(taostats))


@app.command()
def metagraph(
    netuid: int = typer.Argument(..., help="Subnet ID"),
    limit: int = typer.Option(20, "--limit", "-l", help="Number of neurons to show"),
):
    """Show metagraph for a subnet.

    [green]Examples:[/green]
        taox metagraph 1
        taox metagraph 18 --limit 50
    """
    sdk = BittensorSDK()
    executor = BtcliExecutor()
    asyncio.run(subnet_cmds.show_metagraph(sdk, executor, netuid, limit=limit))


@app.command(name="--")
def passthrough(
    args: list[str] = typer.Argument(None, help="btcli arguments"),
):
    """Pass commands directly to btcli.

    [green]Examples:[/green]
        taox -- wallet list
        taox -- stake add --amount 10 --netuid 1
    """
    import subprocess

    if not args:
        console.print("[muted]Usage: taox -- <btcli command>[/muted]")
        return

    cmd = ["btcli"] + list(args)
    console.print(f"[muted]Running: {' '.join(cmd)}[/muted]\n")

    try:
        subprocess.run(cmd, shell=False)
    except FileNotFoundError:
        print_error("btcli not found. Install with: pip install bittensor-cli")


def main():
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
