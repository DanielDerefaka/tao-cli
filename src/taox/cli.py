"""Main CLI entry point for taox."""

import warnings

# Suppress LibreSSL warning on macOS (harmless compatibility notice)
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import asyncio
import sys
from typing import Optional

import typer
from rich import box
from rich.panel import Panel

from taox import __app_name__, __version__
from taox.chat.context import ConversationContext
from taox.chat.intents import IntentType
from taox.chat.llm import LLMClient
from taox.chat.state_machine import (
    ConversationEngine,
    ConversationState,
    ResponseAction,
)
from taox.chat.state_machine import (
    IntentType as SMIntentType,
)
from taox.commands import child as child_cmds
from taox.commands import register as register_cmds
from taox.commands import stake as stake_cmds
from taox.commands import subnet as subnet_cmds
from taox.commands import wallet as wallet_cmds
from taox.commands.executor import BtcliExecutor
from taox.config.settings import create_default_config, get_settings, reset_settings_cache
from taox.data.sdk import BittensorSDK
from taox.data.taostats import TaostatsClient
from taox.security.credentials import CredentialManager, setup_secure_logging
from taox.ui.console import console, print_error, print_success, print_welcome
from taox.ui.onboarding import (
    detect_wallets,
    get_wallet_name,
    is_multi_wallet_mode,
    is_onboarding_needed,
    run_onboarding,
    show_commands_overview,
    show_welcome_banner,
)
from taox.ui.prompts import confirm, input_amount, input_netuid
from taox.ui.theme import Symbols

# Create Typer app
app = typer.Typer(
    name=__app_name__,
    help="AI-powered conversational CLI for Bittensor",
    rich_markup_mode="rich",
    no_args_is_help=False,  # We handle no-args with welcome screen
    invoke_without_command=True,
)


def version_callback(value: bool):
    """Print version and exit."""
    if value:
        console.print(f"[primary]{__app_name__}[/primary] version [tao]{__version__}[/tao]")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Run in demo mode (no real API calls or transactions)",
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

    # If no subcommand, show welcome or onboarding
    if ctx.invoked_subcommand is None:
        if is_onboarding_needed():
            run_onboarding()
        else:
            _show_welcome_screen()


def _show_welcome_screen():
    """Show welcome screen for returning users."""
    show_welcome_banner()

    # Show current wallet info
    settings = get_settings()
    wallets = detect_wallets()

    # Check for multi-wallet mode
    if is_multi_wallet_mode():
        wallet_names = [w.name for w in wallets]
        console.print(f"[primary]Wallets:[/primary] {', '.join(wallet_names)}")
        console.print("[muted]Multi-wallet mode: use --wallet <name> or you'll be prompted[/muted]")
    else:
        wallet_name = settings.bittensor.default_wallet
        hotkey_name = settings.bittensor.default_hotkey

        # Find the wallet
        current_wallet = None
        for w in wallets:
            if w.name == wallet_name:
                current_wallet = w
                break

        if current_wallet:
            address = current_wallet.coldkey_ss58 or "Unknown"
            if len(address) > 24:
                address = f"{address[:12]}...{address[-8:]}"
            console.print(f"[primary]Wallet:[/primary] {wallet_name} ({hotkey_name})")
            console.print(f"[primary]Address:[/primary] [address]{address}[/address]")
        elif settings.demo_mode:
            console.print("[warning]Running in demo mode[/warning]")
        else:
            console.print(f"[muted]Wallet: {wallet_name} (not found)[/muted]")

    # Show commands
    show_commands_overview()


@app.command()
def welcome():
    """Show welcome screen and wallet setup.

    Run this to reconfigure your wallet or see the welcome screen again.

    [green]Example:[/green]
        taox welcome
    """
    run_onboarding()


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
    """Main chat loop with conversational state machine."""
    settings = get_settings()

    # Initialize clients
    llm = LLMClient()
    taostats = TaostatsClient()
    sdk = BittensorSDK()
    executor = BtcliExecutor()
    context = ConversationContext()

    # Initialize conversation engine
    engine = ConversationEngine()
    context.set_engine(engine)

    # Initialize context with wallet/network from settings
    context.set_wallet(settings.bittensor.default_wallet, settings.bittensor.default_hotkey)
    context.set_network(settings.bittensor.network)

    # Show welcome
    print_welcome()

    if settings.demo_mode:
        console.print(
            "[warning]Running in demo mode - no real transactions will be executed[/warning]\n"
        )

    if not llm.is_available:
        console.print("[muted]LLM not available - using pattern matching for commands[/muted]")
        console.print("[muted]Run 'taox setup' to configure API keys for full AI support[/muted]\n")

    console.print("[muted]Type 'help' for available commands, 'quit' to exit[/muted]\n")

    # Process initial message if provided
    if initial_message:
        await _process_message_v2(initial_message, llm, taostats, sdk, executor, context, engine)

    # Main loop
    while True:
        try:
            # Build prompt based on state
            if engine.state == ConversationState.SLOT_FILLING:
                prompt_text = "[prompt]>[/prompt] "
            elif engine.state == ConversationState.CONFIRMING:
                prompt_text = "[prompt](yes/no)>[/prompt] "
            else:
                prompt_text = "[prompt]You:[/prompt] "

            # Get input
            user_input = console.input(prompt_text).strip()

            if not user_input:
                continue

            # Check for quit (only in IDLE state)
            if (
                user_input.lower() in ("quit", "exit", "q")
                and engine.state == ConversationState.IDLE
            ):
                console.print("[muted]Goodbye![/muted]")
                break

            # Check for clear
            if user_input.lower() == "clear":
                context.clear()
                console.clear()
                print_welcome()
                continue

            # Process message through state machine
            await _process_message_v2(user_input, llm, taostats, sdk, executor, context, engine)

        except KeyboardInterrupt:
            if engine.state != ConversationState.IDLE:
                engine._reset()
                console.print("\n[muted]Cancelled. What else can I help with?[/muted]")
            else:
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
    assistant_response = "Done."  # Default response for commands

    # Parse intent
    intent = llm.parse_intent(user_input, context)
    intent = context.resolve_follow_up(intent)

    # Add to history
    context.add_user_message(user_input, intent)

    console.print()

    try:
        # Handle based on intent type
        if intent.type == IntentType.BALANCE:
            await wallet_cmds.show_balance(sdk, wallet_name=intent.wallet_name)
            assistant_response = "Displayed balance."

        elif intent.type == IntentType.PORTFOLIO:
            await stake_cmds.show_portfolio(taostats, sdk, wallet_name=intent.wallet_name)
            assistant_response = "Displayed portfolio."

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
            assistant_response = (
                f"Processed stake of {intent.amount} TAO on subnet {intent.netuid}."
            )

        elif intent.type == IntentType.UNSTAKE:
            if intent.amount is None:
                intent.amount = input_amount("How much TAO to unstake")

            if intent.netuid is None:
                intent.netuid = input_netuid("From which subnet", default=1)

            # Need hotkey - in a real impl would show current positions
            console.print("[warning]Unstake requires specifying the validator hotkey[/warning]")
            console.print("[muted]Use: 'unstake X TAO from <hotkey> on subnet Y'[/muted]")
            assistant_response = "Unstake requires specifying the validator hotkey."

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
            assistant_response = f"Processed transfer of {intent.amount} TAO."

        elif intent.type == IntentType.VALIDATORS:
            await stake_cmds.show_validators(taostats, netuid=intent.netuid)
            assistant_response = "Displayed validators."

        elif intent.type == IntentType.SUBNETS:
            await subnet_cmds.list_subnets(taostats)
            assistant_response = "Displayed subnets."

        elif intent.type == IntentType.METAGRAPH:
            if intent.netuid is None:
                intent.netuid = input_netuid("Which subnet", default=1)
            await subnet_cmds.show_metagraph(sdk, executor, intent.netuid)
            assistant_response = f"Displayed metagraph for subnet {intent.netuid}."

        elif intent.type == IntentType.HELP:
            _show_help()
            assistant_response = "Displayed help information."

        elif intent.type == IntentType.GREETING:
            # Simple greeting response
            wallet = context.current_wallet or "your wallet"
            console.print(
                f"[info]Hi! I'm ready to help with {wallet} on {context.current_network}.[/info]"
            )
            assistant_response = (
                f"Greeted user. Wallet: {wallet}, Network: {context.current_network}"
            )

        elif intent.type == IntentType.CONFIRM:
            # User said yes/ok but there's nothing pending - just acknowledge
            console.print("[muted]Ready for your next command.[/muted]")
            assistant_response = "Acknowledged. Waiting for next command."

        elif intent.type == IntentType.INFO or intent.type == IntentType.UNKNOWN:
            # Use LLM for general responses or get mock response
            assistant_response = llm.chat(user_input, context)
            console.print(f"[info]{assistant_response}[/info]")

        else:
            console.print(f"[muted]Intent: {intent}[/muted]")
            assistant_response = f"Processed intent: {intent.type.value}"

    except Exception as e:
        # Log error and set response
        print_error(f"Error processing command: {e}")
        assistant_response = f"Error: {e}"

    # Always add assistant response to maintain message alternation
    context.add_assistant_message(assistant_response)
    console.print()


async def _process_message_v2(
    user_input: str,
    llm: LLMClient,
    taostats: TaostatsClient,
    sdk: BittensorSDK,
    executor: BtcliExecutor,
    context: ConversationContext,
    engine: ConversationEngine,
):
    """Process a user message through the conversation state machine.

    This function implements conversational slot-filling and confirmation.
    """
    settings = get_settings()

    # Process through state machine
    response = engine.process_input(user_input)

    console.print()

    # Handle different response actions
    if response.action == ResponseAction.DISPLAY:
        # Just display the message
        console.print(f"[info]{response.message}[/info]")
        context.add_user_message(user_input)
        context.add_assistant_message(response.message)

    elif response.action == ResponseAction.ASK:
        # Slot-filling: display question
        console.print(f"[info]{response.message}[/info]")
        context.add_user_message(user_input)
        context.add_assistant_message(response.message)

    elif response.action == ResponseAction.CONFIRM:
        # Show confirmation prompt - enhance for REGISTER with subnet info
        intent = response.intent
        if intent and intent.type == SMIntentType.REGISTER and intent.slots.netuid:
            confirm_msg = await _build_register_confirmation(
                taostats, intent.slots.netuid, intent.slots.wallet
            )
            console.print(confirm_msg)
            context.add_user_message(user_input)
            context.add_assistant_message(confirm_msg)
        else:
            console.print(f"[info]{response.message}[/info]")
            context.add_user_message(user_input)
            context.add_assistant_message(response.message)

    elif response.action == ResponseAction.EXECUTE:
        # Execute the intent
        context.add_user_message(user_input)
        intent = response.intent

        if not intent:
            console.print("[error]No intent to execute[/error]")
            context.add_assistant_message("Error: No intent to execute")
            return

        try:
            assistant_response = await _execute_intent(
                intent, llm, taostats, sdk, executor, context, settings
            )
            context.add_assistant_message(assistant_response)

            # Show follow-up suggestions
            suggestions = engine.get_follow_up_suggestions()
            if suggestions:
                console.print()
                console.print("[muted]Suggestions:[/muted]")
                for i, suggestion in enumerate(suggestions[:3], 1):
                    console.print(f"[muted]  {i}. {suggestion}[/muted]")

        except Exception as e:
            print_error(f"Error: {e}")
            context.add_assistant_message(f"Error: {e}")
            engine._reset()

    console.print()


async def _execute_intent(
    intent,  # ParsedIntent from state machine
    llm: LLMClient,
    taostats: TaostatsClient,
    sdk: BittensorSDK,
    executor: BtcliExecutor,
    context: ConversationContext,
    settings,
) -> str:
    """Execute a parsed intent and return the assistant response."""
    slots = intent.slots

    if intent.type == SMIntentType.BALANCE:
        await wallet_cmds.show_balance(sdk, wallet_name=slots.wallet)
        return "Displayed balance."

    elif intent.type == SMIntentType.PORTFOLIO:
        await stake_cmds.show_portfolio(taostats, sdk, wallet_name=slots.wallet)
        return "Displayed portfolio."

    elif intent.type == SMIntentType.STAKE:
        amount = slots.amount or 0
        await stake_cmds.stake_tao(
            executor=executor,
            sdk=sdk,
            taostats=taostats,
            amount=amount,
            validator_name=slots.validator_name,
            validator_ss58=slots.validator_ss58,
            netuid=slots.netuid or 1,
            wallet_name=slots.wallet,
            dry_run=settings.demo_mode,
        )
        return f"Processed stake of {amount} τ on subnet {slots.netuid}."

    elif intent.type == SMIntentType.UNSTAKE:
        amount = slots.amount or 0
        # Note: unstake requires more implementation work
        console.print(
            f"[info]Would unstake {amount} τ from {slots.validator_name or slots.validator_ss58} on subnet {slots.netuid}[/info]"
        )
        console.print("[warning]Full unstake implementation pending[/warning]")
        return f"Unstake request for {amount} τ processed."

    elif intent.type == SMIntentType.TRANSFER:
        await wallet_cmds.transfer_tao(
            executor=executor,
            sdk=sdk,
            amount=slots.amount or 0,
            destination=slots.destination or "",
            wallet_name=slots.wallet,
            dry_run=settings.demo_mode,
        )
        return f"Processed transfer of {slots.amount} τ."

    elif intent.type == SMIntentType.VALIDATORS:
        await stake_cmds.show_validators(taostats, netuid=slots.netuid)
        return "Displayed validators."

    elif intent.type == SMIntentType.SUBNETS:
        await subnet_cmds.list_subnets(taostats)
        return "Displayed subnets."

    elif intent.type == SMIntentType.METAGRAPH:
        await subnet_cmds.show_metagraph(sdk, executor, slots.netuid or 1)
        return f"Displayed metagraph for subnet {slots.netuid}."

    elif intent.type == SMIntentType.REGISTER:
        netuid = slots.netuid or 1
        success = await register_cmds.register_burned(
            executor=executor,
            sdk=sdk,
            taostats=taostats,
            netuid=netuid,
            wallet_name=slots.wallet,
            hotkey_name=slots.hotkey,
            dry_run=settings.demo_mode,
        )
        if success:
            return f"Registered on subnet {netuid}."
        else:
            return f"Registration on subnet {netuid} cancelled or failed."

    elif intent.type == SMIntentType.HELP:
        _show_help()
        return "Displayed help."

    elif intent.type == SMIntentType.GREETING:
        wallet = context.current_wallet or "your wallet"
        console.print(
            f"[info]Hi! I'm ready to help with {wallet} on {context.current_network}.[/info]"
        )
        return "Greeted user."

    else:
        console.print(f"[muted]Intent: {intent}[/muted]")
        return f"Processed intent: {intent.type.value}"


async def _build_register_confirmation(
    taostats: TaostatsClient,
    netuid: int,
    wallet_name: Optional[str] = None,
) -> str:
    """Build a rich confirmation message for registration with subnet details."""
    try:
        subnet = await taostats.get_subnet(netuid)
        price_info = await taostats.get_price()

        if subnet:
            subnet_name = subnet.name or "Unknown"
            burn_cost = subnet.burn_cost
            usd_cost = burn_cost * price_info.usd

            msg = f"[info]Got it! You want to register on [bold]SN{netuid} - {subnet_name}[/bold].[/info]\n\n"
            msg += f"[warning]Registration cost: [tao]{burn_cost:.4f} τ[/tao] (≈${usd_cost:.2f})[/warning]\n\n"
            msg += "[info]Proceed with registration? (yes/no)[/info]"
            return msg
        else:
            return f"[info]Register on subnet {netuid}? (yes/no)[/info]"
    except Exception:
        return f"[info]Register on subnet {netuid}? (yes/no)[/info]"


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
        console.print(
            f"[success]Current key: {existing_chutes[:8]}...{existing_chutes[-4:]}[/success]"
        )
        if not confirm("Update Chutes API key?"):
            console.print("[muted]Keeping existing key[/muted]\n")
        else:
            chutes_key = typer.prompt("Enter Chutes API key", hide_input=True)
            if chutes_key:
                CredentialManager.set_chutes_key(chutes_key)
                print_success("Chutes API key saved")
    else:
        chutes_key = typer.prompt(
            "Enter Chutes API key (or press Enter to skip)", default="", hide_input=True
        )
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
        console.print(
            f"[success]Current key: {existing_taostats[:8]}...{existing_taostats[-4:]}[/success]"
        )
        if not confirm("Update Taostats API key?"):
            console.print("[muted]Keeping existing key[/muted]\n")
        else:
            taostats_key = typer.prompt("Enter Taostats API key", hide_input=True)
            if taostats_key:
                CredentialManager.set_taostats_key(taostats_key)
                print_success("Taostats API key saved")
    else:
        taostats_key = typer.prompt(
            "Enter Taostats API key (or press Enter to skip)", default="", hide_input=True
        )
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
    # Get wallet name (prompts if multi-wallet mode and not specified)
    if not address:
        wallet_name = get_wallet_name(wallet_name)
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
def portfolio(
    wallet_name: Optional[str] = typer.Option(None, "--wallet", "-w", help="Wallet name"),
):
    """Show portfolio with balances and stake positions.

    Displays free balance, staked amounts, USD values, and position breakdown.

    [green]Examples:[/green]
        taox portfolio
        taox portfolio --wallet my_wallet
    """
    wallet_name = get_wallet_name(wallet_name)
    taostats = TaostatsClient()
    sdk = BittensorSDK()
    asyncio.run(stake_cmds.show_portfolio(taostats, sdk, wallet_name=wallet_name))


@app.command()
def price():
    """Show current TAO price.

    [green]Example:[/green]
        taox price
    """

    async def _show_price():
        taostats = TaostatsClient()
        with console.status("[bold green]Fetching TAO price..."):
            price_info = await taostats.get_price()

        change_color = "success" if price_info.change_24h >= 0 else "error"
        change_symbol = "+" if price_info.change_24h >= 0 else ""

        console.print()
        console.print(f"[bold]TAO Price:[/bold] [tao]${price_info.usd:,.2f}[/tao]")
        console.print(
            f"[bold]24h Change:[/bold] [{change_color}]{change_symbol}{price_info.change_24h:.2f}%[/{change_color}]"
        )
        console.print()

    asyncio.run(_show_price())


@app.command()
def stake(
    wizard: bool = typer.Option(False, "--wizard", "-w", help="Launch interactive stake wizard"),
    amount: Optional[float] = typer.Option(None, "--amount", "-a", help="Amount to stake"),
    validator: Optional[str] = typer.Option(
        None, "--validator", "-v", help="Validator name or hotkey"
    ),
    netuid: Optional[int] = typer.Option(None, "--netuid", "-n", help="Subnet ID"),
    wallet_name: Optional[str] = typer.Option(None, "--wallet", help="Wallet name"),
):
    """Stake TAO to a validator.

    Use --wizard for guided interactive mode, or provide options directly.

    [green]Examples:[/green]
        taox stake --wizard
        taox stake --amount 10 --validator taostats --netuid 1
        taox stake -a 50 -v "OpenTensor" -n 18
    """
    taostats = TaostatsClient()
    sdk = BittensorSDK()
    executor = BtcliExecutor()

    if wizard or (amount is None and validator is None):
        stake_cmds.stake_wizard(executor, sdk, taostats)
    else:
        if amount is None:
            print_error("Amount is required. Use --amount or --wizard for guided mode.")
            return
        if netuid is None:
            netuid = 1
            console.print(f"[muted]Using default subnet: {netuid}[/muted]")

        asyncio.run(
            stake_cmds.stake_tao(
                executor=executor,
                sdk=sdk,
                taostats=taostats,
                amount=amount,
                validator_name=validator,
                netuid=netuid,
                wallet_name=wallet_name,
            )
        )


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


@app.command()
def dashboard(
    wallet_name: Optional[str] = typer.Option(None, "--wallet", "-w", help="Wallet name"),
    refresh: int = typer.Option(30, "--refresh", "-r", help="Auto-refresh interval in seconds"),
):
    """Launch the full TUI dashboard.

    Real-time portfolio overview with price, balance, positions, and validators.

    [green]Examples:[/green]
        taox dashboard
        taox dashboard --wallet my_wallet
        taox dashboard --refresh 60
    """
    wallet_name = get_wallet_name(wallet_name)
    from taox.ui.dashboard import run_dashboard

    run_dashboard(wallet_name=wallet_name, refresh_interval=refresh)


@app.command()
def child(
    wizard: bool = typer.Option(False, "--wizard", "-w", help="Launch interactive wizard"),
    action: Optional[str] = typer.Option(
        None, "--action", "-a", help="Action: get, set, revoke, take"
    ),
    child_hotkey: Optional[str] = typer.Option(
        None, "--child", "-c", help="Child hotkey SS58 address"
    ),
    netuid: Optional[int] = typer.Option(None, "--netuid", "-n", help="Subnet ID"),
    proportion: float = typer.Option(1.0, "--proportion", "-p", help="Stake proportion (0-1)"),
    take: float = typer.Option(0.09, "--take", "-t", help="Take rate (0-0.18)"),
    wallet_name: Optional[str] = typer.Option(None, "--wallet", help="Wallet name"),
):
    """Manage child hotkeys for stake delegation.

    Use --wizard for guided interactive mode, or provide options directly.

    [green]Examples:[/green]
        taox child --wizard
        taox child --action get --netuid 1
        taox child --action set --child 5xxx... --netuid 1 --proportion 0.5
        taox child --action take --netuid 1 --take 0.09
    """
    sdk = BittensorSDK()
    executor = BtcliExecutor()

    if wizard or action is None:
        child_cmds.child_wizard(executor, sdk)
    elif action == "get":
        if netuid is None:
            print_error("Subnet ID (--netuid) is required")
            return
        asyncio.run(
            child_cmds.get_child_hotkeys(
                executor=executor,
                sdk=sdk,
                netuid=netuid,
                wallet_name=wallet_name,
            )
        )
    elif action == "set":
        if child_hotkey is None or netuid is None:
            print_error("Child hotkey (--child) and subnet ID (--netuid) are required")
            return
        asyncio.run(
            child_cmds.set_child_hotkey(
                executor=executor,
                sdk=sdk,
                child_hotkey=child_hotkey,
                netuid=netuid,
                proportion=proportion,
                wallet_name=wallet_name,
            )
        )
    elif action == "revoke":
        if child_hotkey is None or netuid is None:
            print_error("Child hotkey (--child) and subnet ID (--netuid) are required")
            return
        asyncio.run(
            child_cmds.revoke_child_hotkey(
                executor=executor,
                sdk=sdk,
                child_hotkey=child_hotkey,
                netuid=netuid,
                wallet_name=wallet_name,
            )
        )
    elif action == "take":
        if netuid is None:
            print_error("Subnet ID (--netuid) is required")
            return
        asyncio.run(
            child_cmds.set_child_take(
                executor=executor,
                sdk=sdk,
                netuid=netuid,
                take=take,
                wallet_name=wallet_name,
            )
        )
    else:
        print_error(f"Unknown action: {action}. Use: get, set, revoke, take")


@app.command()
def register(
    wizard: bool = typer.Option(False, "--wizard", "-w", help="Launch interactive wizard"),
    netuid: Optional[int] = typer.Option(None, "--netuid", "-n", help="Subnet ID"),
    method: str = typer.Option("burn", "--method", "-m", help="Registration method: burn or pow"),
    wallet_name: Optional[str] = typer.Option(None, "--wallet", help="Wallet name"),
    hotkey_name: Optional[str] = typer.Option(None, "--hotkey", help="Hotkey name"),
    num_processes: int = typer.Option(4, "--processes", "-p", help="CPU processes for PoW"),
):
    """Register on a subnet.

    Use --wizard for guided interactive mode, or provide options directly.

    [green]Examples:[/green]
        taox register --wizard
        taox register --netuid 1 --method burn
        taox register --netuid 3 --method pow --processes 8
    """
    taostats = TaostatsClient()
    sdk = BittensorSDK()
    executor = BtcliExecutor()

    if wizard or netuid is None:
        register_cmds.register_wizard(executor, sdk, taostats)
    elif method == "burn":
        asyncio.run(
            register_cmds.register_burned(
                executor=executor,
                sdk=sdk,
                taostats=taostats,
                netuid=netuid,
                wallet_name=wallet_name,
                hotkey_name=hotkey_name,
            )
        )
    elif method == "pow":
        asyncio.run(
            register_cmds.register_pow(
                executor=executor,
                sdk=sdk,
                netuid=netuid,
                wallet_name=wallet_name,
                hotkey_name=hotkey_name,
                num_processes=num_processes,
            )
        )
    else:
        print_error(f"Unknown method: {method}. Use: burn or pow")


@app.command()
def history(
    limit: int = typer.Option(20, "--limit", "-l", help="Number of transactions to show"),
    tx_type: Optional[str] = typer.Option(
        None, "--type", "-t", help="Filter by type: stake, unstake, transfer, register"
    ),
    status: Optional[str] = typer.Option(
        None, "--status", "-s", help="Filter by status: success, failed, pending"
    ),
    export: Optional[str] = typer.Option(
        None, "--export", "-e", help="Export to file (json or csv)"
    ),
):
    """View transaction history.

    Shows recent transactions with optional filtering and export.

    [green]Examples:[/green]
        taox history
        taox history --limit 50
        taox history --type stake --status success
        taox history --export transactions.csv
        taox history --export transactions.json
    """
    from pathlib import Path

    from taox.data.history import (
        TransactionHistory,
        TransactionStatus,
        TransactionType,
        show_history,
    )

    # Parse filters
    tx_type_filter = None
    if tx_type:
        try:
            tx_type_filter = TransactionType(tx_type.lower())
        except ValueError:
            print_error(f"Invalid type: {tx_type}. Use: stake, unstake, transfer, register")
            return

    status_filter = None
    if status:
        try:
            status_filter = TransactionStatus(status.lower())
        except ValueError:
            print_error(f"Invalid status: {status}. Use: success, failed, pending, cancelled")
            return

    # Export if requested
    if export:
        export_path = Path(export)
        history_manager = TransactionHistory()

        if export.endswith(".json"):
            count = history_manager.export_json(
                export_path, tx_type=tx_type_filter, status=status_filter, limit=limit
            )
            print_success(f"Exported {count} transactions to {export_path}")
        elif export.endswith(".csv"):
            count = history_manager.export_csv(
                export_path, tx_type=tx_type_filter, status=status_filter, limit=limit
            )
            print_success(f"Exported {count} transactions to {export_path}")
        else:
            print_error("Export file must end with .json or .csv")
        return

    # Show history table
    show_history(limit=limit, tx_type=tx_type_filter, status=status_filter)


@app.command()
def doctor(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed dependency versions"
    ),
):
    """Check environment and diagnose issues.

    Verifies that taox is properly configured with all dependencies.

    [green]Examples:[/green]
        taox doctor
        taox doctor --verbose
    """
    import shutil
    import subprocess
    from pathlib import Path

    console.print()
    console.print(
        Panel(
            "[primary]taox[/primary] Environment Check",
            box=box.ROUNDED,
            border_style="primary",
        )
    )
    console.print()

    checks = []
    warnings = []
    errors = []

    # 1. Check Python version

    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(f"{Symbols.CHECK} Python version: {py_version}")

    # 2. Check taox version
    checks.append(f"{Symbols.CHECK} taox version: {__version__}")

    # 3. Check btcli installation
    btcli_path = shutil.which("btcli")
    if btcli_path:
        try:
            result = subprocess.run(
                ["btcli", "--version"], capture_output=True, text=True, timeout=10
            )
            btcli_version = result.stdout.strip() or result.stderr.strip()
            checks.append(
                f"{Symbols.CHECK} btcli installed: {btcli_version.split()[-1] if btcli_version else 'unknown version'}"
            )
        except Exception:
            checks.append(f"{Symbols.CHECK} btcli installed: {btcli_path}")
    else:
        errors.append(f"{Symbols.ERROR} btcli not found - install with: pip install bittensor-cli")

    # 4. Check wallet directory and default wallet/hotkey
    settings = get_settings()
    wallet_path = Path.home() / ".bittensor" / "wallets"
    if wallet_path.exists():
        wallets = list(wallet_path.iterdir())
        wallet_dirs = [w for w in wallets if w.is_dir()]
        wallet_count = len(wallet_dirs)
        if wallet_count > 0:
            checks.append(f"{Symbols.CHECK} Wallet directory: {wallet_count} wallet(s) found")

            # Check default wallet exists
            default_wallet = settings.bittensor.default_wallet
            default_wallet_path = wallet_path / default_wallet
            if default_wallet_path.exists():
                checks.append(f"{Symbols.CHECK} Default wallet '{default_wallet}': exists")

                # Check default hotkey exists
                default_hotkey = settings.bittensor.default_hotkey
                hotkey_path = default_wallet_path / "hotkeys" / default_hotkey
                if hotkey_path.exists():
                    checks.append(f"{Symbols.CHECK} Default hotkey '{default_hotkey}': exists")
                else:
                    warnings.append(
                        f"{Symbols.WARN} Default hotkey '{default_hotkey}' not found in wallet '{default_wallet}'"
                    )
            else:
                warnings.append(f"{Symbols.WARN} Default wallet '{default_wallet}' not found")
        else:
            warnings.append(f"{Symbols.WARN} Wallet directory exists but no wallets found")
    else:
        warnings.append(f"{Symbols.WARN} Wallet directory not found: {wallet_path}")

    # 5. Check config directory
    config_path = Path.home() / ".taox"
    if config_path.exists():
        checks.append(f"{Symbols.CHECK} Config directory: {config_path}")
    else:
        warnings.append(f"{Symbols.WARN} Config directory not found (will be created on first run)")

    # 6. Check API keys
    chutes_key = CredentialManager.get_chutes_key()
    if chutes_key:
        checks.append(f"{Symbols.CHECK} Chutes API key: configured")
    else:
        warnings.append(f"{Symbols.WARN} Chutes API key: not configured (run 'taox setup')")

    taostats_key = CredentialManager.get_taostats_key()
    if taostats_key:
        checks.append(f"{Symbols.CHECK} Taostats API key: configured")
    else:
        warnings.append(f"{Symbols.WARN} Taostats API key: not configured (run 'taox setup')")

    # 7. Check demo mode
    if settings.demo_mode:
        warnings.append(f"{Symbols.WARN} Demo mode: enabled (no real transactions)")
    else:
        checks.append(f"{Symbols.CHECK} Demo mode: disabled")

    # 8. Check RPC endpoint reachability (finney)
    console.print("[muted]Checking network connectivity...[/muted]", end="\r")
    try:
        import httpx

        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                "https://entrypoint-finney.opentensor.ai:443",
                json={"jsonrpc": "2.0", "method": "system_health", "params": [], "id": 1},
                headers={"Content-Type": "application/json"},
            )
            if response.status_code == 200:
                checks.append(f"{Symbols.CHECK} Finney RPC endpoint: reachable")
            else:
                warnings.append(
                    f"{Symbols.WARN} Finney RPC endpoint: returned {response.status_code}"
                )
    except Exception as e:
        warnings.append(f"{Symbols.WARN} Finney RPC endpoint: unreachable ({type(e).__name__})")
    console.print(" " * 40, end="\r")  # Clear the status line

    # 9. Check rate limit status (backoff manager)
    try:
        from taox.data.cache import backoff_manager

        active_backoffs = []
        for key in list(backoff_manager._failures.keys()):
            if not backoff_manager.should_retry(key):
                retry_after = backoff_manager.get_retry_after(key)
                if retry_after:
                    active_backoffs.append(f"{key}: {retry_after:.0f}s")

        if active_backoffs:
            warnings.append(f"{Symbols.WARN} Rate limited: {', '.join(active_backoffs)}")
        else:
            checks.append(f"{Symbols.CHECK} Rate limits: none active")
    except Exception:
        pass  # Backoff check is optional

    # 10. Check optional bittensor SDK
    try:
        import bittensor

        bt_version = getattr(bittensor, "__version__", "unknown")
        checks.append(f"{Symbols.CHECK} Bittensor SDK: {bt_version}")
    except ImportError:
        warnings.append(
            f"{Symbols.WARN} Bittensor SDK: not installed (optional, install with: pip install bittensor)"
        )

    # Display results
    console.print("[bold]Checks:[/bold]")
    for check in checks:
        console.print(f"  {check}")

    if warnings:
        console.print()
        console.print("[bold yellow]Warnings:[/bold yellow]")
        for warning in warnings:
            console.print(f"  {warning}")

    if errors:
        console.print()
        console.print("[bold red]Errors:[/bold red]")
        for error in errors:
            console.print(f"  {error}")

    # Verbose: Show key dependency versions
    if verbose:
        console.print()
        console.print("[bold]Dependency Versions:[/bold]")
        deps = [
            ("typer", "typer"),
            ("rich", "rich"),
            ("httpx", "httpx"),
            ("pydantic", "pydantic"),
            ("openai", "openai"),
            ("keyring", "keyring"),
            ("pexpect", "pexpect"),
            ("cachetools", "cachetools"),
        ]
        for name, module in deps:
            try:
                mod = __import__(module)
                version = getattr(mod, "__version__", "unknown")
                console.print(f"  {Symbols.CHECK} {name}: {version}")
            except ImportError:
                console.print(f"  {Symbols.ERROR} {name}: not installed")

    # Summary
    console.print()
    if errors:
        console.print(f"[red]Found {len(errors)} error(s) that must be fixed.[/red]")
        raise typer.Exit(1)
    elif warnings:
        console.print(
            f"[yellow]Found {len(warnings)} warning(s). taox will work but some features may be limited.[/yellow]"
        )
    else:
        console.print("[green]All checks passed! taox is ready to use.[/green]")

    console.print()
    console.print("[muted]Run 'taox setup' to configure API keys[/muted]")
    console.print("[muted]Run 'taox --demo chat' to try demo mode[/muted]")


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
