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
from taox.ui.theme import Symbols, TaoxColors

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
    legacy: bool = typer.Option(False, "--legacy", help="Use legacy pattern-based mode"),
):
    """Start interactive chat mode.

    Have a conversation with taox to manage your Bittensor operations.

    [green]Examples:[/green]
        taox chat
        taox chat "what is my balance?"
        taox chat "stake 10 TAO to taostats on subnet 1"
    """
    settings = get_settings()

    # Use LLM-first mode unless legacy flag or mode is "off"
    if not legacy and settings.llm.mode == "always":
        asyncio.run(_llm_chat_loop(message))
    else:
        asyncio.run(_chat_loop(message))


async def _llm_chat_loop(initial_message: Optional[str] = None):
    """LLM-first chat loop - the AI is always the brain."""
    from taox.chat.router import Router

    settings = get_settings()

    # Initialize clients
    taostats = TaostatsClient()
    sdk = BittensorSDK()
    executor = BtcliExecutor()

    # Initialize router
    router = Router(taostats=taostats, sdk=sdk, executor=executor)

    # Show welcome
    print_welcome()

    if settings.demo_mode:
        console.print(
            "[warning]Demo mode - no real transactions[/warning]\n"
        )

    if not router.interpreter.is_available:
        console.print("[warning]No Chutes API key - using pattern matching[/warning]")
        console.print("[muted]Run 'taox setup' for full AI support[/muted]\n")
    else:
        console.print("[success]AI mode active[/success] - just talk naturally!\n")

    console.print("[muted]Type 'quit' to exit, 'clear' to reset[/muted]\n")

    # Process initial message if provided
    if initial_message:
        console.print(f"[prompt]You:[/prompt] {initial_message}")
        response = await router.process(initial_message)
        console.print(f"[info]{response}[/info]\n")

    # Main loop
    while True:
        try:
            user_input = console.input("[prompt]You:[/prompt] ").strip()

            if not user_input:
                continue

            # Check for quit
            if user_input.lower() in ("quit", "exit", "q"):
                console.print("[muted]Goodbye![/muted]")
                break

            # Check for clear
            if user_input.lower() == "clear":
                router.clear()
                console.clear()
                print_welcome()
                console.print("[muted]Conversation cleared.[/muted]\n")
                continue

            # Process through router
            console.print()
            response = await router.process(user_input)
            console.print(f"[info]{response}[/info]\n")

        except KeyboardInterrupt:
            router.clear()
            console.print("\n[muted]Cancelled. What else?[/muted]\n")
        except EOFError:
            break

    # Cleanup
    await taostats.close()


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
    delta: Optional[str] = typer.Option(None, "--delta", "-d", help="Show change over time (e.g., 7d, 30d)"),
    history: Optional[str] = typer.Option(None, "--history", "-h", help="Show history (e.g., 7d, 30d)"),
    share: bool = typer.Option(False, "--share", "-s", help="Redact addresses for sharing"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show portfolio with balances and stake positions.

    Displays free balance, staked amounts, USD values, and position breakdown.
    Automatically saves a daily snapshot for historical tracking.

    [green]Examples:[/green]
        taox portfolio
        taox portfolio --wallet my_wallet
        taox portfolio --delta 7d
        taox portfolio --history 30d
        taox portfolio --share
    """
    from taox.data.snapshots import (
        PortfolioSnapshot,
        PositionSnapshot,
        get_snapshot_store,
    )

    wallet_name = get_wallet_name(wallet_name)
    taostats = TaostatsClient()
    sdk = BittensorSDK()

    async def _portfolio_with_snapshots():
        # Get current portfolio
        result = await stake_cmds.show_portfolio(
            taostats, sdk, wallet_name=wallet_name,
            share_mode=share, json_output=json_output,
            suppress_output=(delta is not None or history is not None),
        )

        if not result:
            return

        # Save snapshot
        store = get_snapshot_store()
        positions = [
            PositionSnapshot(
                netuid=p.get("netuid", 0),
                hotkey=p.get("hotkey", ""),
                validator_name=p.get("hotkey_name"),
                stake=p.get("stake", 0),
                alpha_balance=p.get("alpha_balance", 0),
            )
            for p in result.get("positions", [])
        ]

        snapshot = PortfolioSnapshot(
            timestamp=datetime.now().isoformat(),
            coldkey=result.get("coldkey", ""),
            free_balance=result.get("free_balance", 0),
            total_staked=result.get("staked_total", 0),
            total_value=result.get("total_balance", 0),
            tao_price_usd=result.get("usd_price", 0),
            usd_value=result.get("usd_value", 0),
            positions=positions,
        )

        if snapshot.coldkey:
            store.save_snapshot(snapshot)

        # Handle delta view
        if delta:
            days = _parse_days(delta)
            if days:
                delta_result = store.compute_delta(snapshot.coldkey, days, snapshot)
                if delta_result:
                    _display_portfolio_delta(delta_result, share_mode=share, json_output=json_output)
                else:
                    console.print(f"[muted]No historical data available for {days}d comparison.[/muted]")
                    console.print("[muted]Run 'taox portfolio' daily to build history.[/muted]")

        # Handle history view
        elif history:
            days = _parse_days(history)
            if days:
                history_data = store.get_history(snapshot.coldkey, days)
                if history_data:
                    _display_portfolio_history(history_data, days, share_mode=share, json_output=json_output)
                else:
                    console.print(f"[muted]No historical data available for the last {days} days.[/muted]")

    from datetime import datetime
    asyncio.run(_portfolio_with_snapshots())


def _parse_days(time_str: str) -> Optional[int]:
    """Parse time string like '7d' or '30d' to days."""
    time_str = time_str.lower().strip()
    if time_str.endswith("d"):
        try:
            return int(time_str[:-1])
        except ValueError:
            pass
    # Try just the number
    try:
        return int(time_str)
    except ValueError:
        console.print(f"[error]Invalid time format: {time_str}. Use format like '7d' or '30d'.[/error]")
        return None


def _display_portfolio_delta(delta, share_mode: bool = False, json_output: bool = False):
    """Display portfolio delta."""
    import json as json_module

    from rich.panel import Panel
    from rich.table import Table

    from taox.ui.console import redact_address

    if json_output:
        output = {
            "days": delta.days,
            "from": delta.from_timestamp,
            "to": delta.to_timestamp,
            "total_value_change": delta.total_value_change,
            "total_value_change_percent": delta.total_value_change_percent,
            "free_balance_change": delta.free_balance_change,
            "total_staked_change": delta.total_staked_change,
            "usd_value_change": delta.usd_value_change,
            "tao_price_change_percent": delta.tao_price_change_percent,
            "estimated_rewards": delta.estimated_rewards,
            "best_performer": {
                "netuid": delta.best_performer.netuid,
                "validator": delta.best_performer.validator_name,
                "change": delta.best_performer.stake_change,
                "change_percent": delta.best_performer.stake_change_percent,
            } if delta.best_performer else None,
            "worst_performer": {
                "netuid": delta.worst_performer.netuid,
                "validator": delta.worst_performer.validator_name,
                "change": delta.worst_performer.stake_change,
                "change_percent": delta.worst_performer.stake_change_percent,
            } if delta.worst_performer else None,
        }
        print(json_module.dumps(output, indent=2))
        return

    # Rich output
    change_color = "success" if delta.total_value_change >= 0 else "error"
    change_symbol = "+" if delta.total_value_change >= 0 else ""

    console.print()
    console.print(
        Panel(
            f"[bold]Portfolio Change - Last {delta.days} Days[/bold]",
            box=box.ROUNDED,
            border_style="primary",
        )
    )
    console.print()

    # Summary table
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Metric", style="bold")
    table.add_column("Change", justify="right")

    table.add_row(
        "Total Value",
        f"[{change_color}]{change_symbol}{delta.total_value_change:,.4f} τ ({change_symbol}{delta.total_value_change_percent:.1f}%)[/{change_color}]"
    )
    table.add_row(
        "Free Balance",
        f"{'+' if delta.free_balance_change >= 0 else ''}{delta.free_balance_change:,.4f} τ"
    )
    table.add_row(
        "Total Staked",
        f"{'+' if delta.total_staked_change >= 0 else ''}{delta.total_staked_change:,.4f} τ"
    )
    table.add_row(
        "USD Value",
        f"[{change_color}]{change_symbol}${delta.usd_value_change:,.2f}[/{change_color}]"
    )
    table.add_row(
        "TAO Price",
        f"{'+' if delta.tao_price_change_percent >= 0 else ''}{delta.tao_price_change_percent:.1f}%"
    )

    if delta.estimated_rewards > 0:
        table.add_row(
            "Est. Rewards",
            f"[success]+{delta.estimated_rewards:,.4f} τ[/success]"
        )

    console.print(table)
    console.print()

    # Best/worst performers
    if delta.best_performer:
        bp = delta.best_performer
        name = bp.validator_name or (redact_address(bp.hotkey) if share_mode else bp.hotkey[:12] + "...")
        console.print(f"[success]Best performer:[/success] SN{bp.netuid} ({name}): +{bp.stake_change:,.4f} τ ({bp.stake_change_percent:+.1f}%)")

    if delta.worst_performer and delta.worst_performer.stake_change < 0:
        wp = delta.worst_performer
        name = wp.validator_name or (redact_address(wp.hotkey) if share_mode else wp.hotkey[:12] + "...")
        console.print(f"[error]Worst performer:[/error] SN{wp.netuid} ({name}): {wp.stake_change:,.4f} τ ({wp.stake_change_percent:+.1f}%)")

    console.print()


def _display_portfolio_history(history: list, days: int, share_mode: bool = False, json_output: bool = False):
    """Display portfolio history."""
    import json as json_module

    from rich.table import Table

    if json_output:
        print(json_module.dumps(history, indent=2))
        return

    console.print()
    console.print(f"[bold]Portfolio History - Last {days} Days[/bold]")
    console.print()

    table = Table(box=box.ROUNDED, border_style=TaoxColors.BORDER)
    table.add_column("Date", style="muted")
    table.add_column("Total TAO", justify="right", style="tao")
    table.add_column("Free", justify="right")
    table.add_column("Staked", justify="right")
    table.add_column("Price", justify="right", style="info")
    table.add_column("USD Value", justify="right", style="muted")

    for entry in history:
        table.add_row(
            entry["date"],
            f"{entry['total_tao']:,.4f} τ",
            f"{entry['free_balance']:,.4f} τ",
            f"{entry['total_staked']:,.4f} τ",
            f"${entry['tao_price']:,.2f}",
            f"${entry['usd_value']:,.2f}",
        )

    console.print(table)
    console.print()


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
def recommend(
    amount: float = typer.Argument(..., help="Amount of TAO to stake"),
    netuid: int = typer.Option(1, "--netuid", "-n", help="Subnet ID"),
    top: int = typer.Option(5, "--top", "-t", help="Number of top validators to show"),
    diversify: int = typer.Option(1, "--diversify", "-d", help="Number of validators to split across (0=auto)"),
    risk: str = typer.Option("med", "--risk", "-r", help="Risk level: low, med, high"),
    share: bool = typer.Option(False, "--share", "-s", help="Redact addresses for sharing"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Get smart staking recommendations.

    Analyzes validators and provides explainable recommendations with
    diversification advice.

    [green]Examples:[/green]
        taox recommend 100
        taox recommend 100 --netuid 1
        taox recommend 500 --diversify 3 --risk low
        taox recommend 100 --json
        taox recommend 100 --share
    """
    from taox.commands.recommend import stake_recommend

    taostats = TaostatsClient()
    asyncio.run(
        stake_recommend(
            taostats=taostats,
            amount=amount,
            netuid=netuid,
            top_n=top,
            diversify=diversify,
            risk_level=risk,
            share_mode=share,
            json_output=json_output,
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


@app.command(name="watch")
def watch_cmd(
    price: Optional[str] = typer.Option(
        None, "--price", "-p", help="Price alert (e.g., 'TAO:500', '>500', '<400')"
    ),
    validator: Optional[str] = typer.Option(
        None, "--validator", "-v", help="Validator name or hotkey to watch"
    ),
    registration: Optional[float] = typer.Option(
        None, "--registration", "-r", help="Alert when registration burn cost <= value"
    ),
    netuid: int = typer.Option(1, "--netuid", "-n", help="Subnet ID for validator/registration alerts"),
    interval: int = typer.Option(30, "--interval", "-i", help="Polling interval in seconds"),
    duration: Optional[int] = typer.Option(None, "--duration", "-d", help="Run for N seconds (default: indefinitely)"),
    list_alerts: bool = typer.Option(False, "--list", "-l", help="List all configured alerts"),
    clear: bool = typer.Option(False, "--clear", help="Clear all alert rules"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Watch mode with alerts.

    Monitor prices, validators, and registration windows with alerts.

    [green]Examples:[/green]
        taox watch                           # Watch with existing alerts
        taox watch --price TAO:500           # Alert when TAO >= $500
        taox watch --price "<400"            # Alert when TAO <= $400
        taox watch --validator taostats -n 1 # Watch validator on SN1
        taox watch --registration 1.0 -n 18  # Alert when SN18 burn <= 1 TAO
        taox watch --list                    # List all alerts
        taox watch --clear                   # Remove all alerts
    """
    from taox.commands.watch import clear_alerts, watch
    from taox.commands.watch import list_alerts as show_alerts

    # Handle list
    if list_alerts:
        show_alerts(json_output=json_output)
        return

    # Handle clear
    if clear:
        count = clear_alerts()
        console.print(f"[success]Cleared {count} alert rule(s).[/success]")
        return

    taostats = TaostatsClient()
    asyncio.run(
        watch(
            taostats=taostats,
            price_alert=price,
            validator_alert=validator,
            registration_alert=registration,
            netuid=netuid,
            poll_interval=interval,
            duration=duration,
            json_output=json_output,
        )
    )


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
def rebalance(
    amount: float = typer.Argument(..., help="Total amount of TAO to stake"),
    netuid: int = typer.Option(1, "--netuid", "-n", help="Subnet ID"),
    top: int = typer.Option(5, "--top", "-t", help="Number of top validators"),
    mode: str = typer.Option("equal", "--mode", "-m", help="Mode: equal, weighted, top_heavy"),
    chunk_size: int = typer.Option(3, "--chunk", "-c", help="Operations per chunk"),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help="Show plan only"),
    skip_confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    wallet_name: Optional[str] = typer.Option(None, "--wallet", "-w", help="Wallet name"),
    share: bool = typer.Option(False, "--share", "-s", help="Redact addresses"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Batch stake across multiple validators.

    Distributes stake across top validators with chunking to avoid rate limits.

    Modes:
    - equal: Split evenly among validators
    - weighted: Proportional to validator stake
    - top_heavy: 50% to top validator, rest split evenly

    [green]Examples:[/green]
        taox rebalance 100
        taox rebalance 100 --top 3
        taox rebalance 500 --mode top_heavy
        taox rebalance 100 --dry-run
        taox rebalance 100 --yes
    """
    from taox.commands.batch import stake_rebalance

    wallet_name = get_wallet_name(wallet_name)
    taostats = TaostatsClient()
    sdk = BittensorSDK()
    executor = BtcliExecutor()

    asyncio.run(
        stake_rebalance(
            executor=executor,
            sdk=sdk,
            taostats=taostats,
            amount=amount,
            netuid=netuid,
            top_n=top,
            mode=mode,
            wallet_name=wallet_name,
            chunk_size=chunk_size,
            dry_run=dry_run,
            skip_confirm=skip_confirm,
            share_mode=share,
            json_output=json_output,
        )
    )


@app.command()
def doctor(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed dependency versions"
    ),
    network: str = typer.Option("finney", "--network", "-n", help="Network to check"),
    wallet_name: Optional[str] = typer.Option(
        None, "--wallet", "-w", help="Wallet to check (overrides default)"
    ),
    hotkey_name: Optional[str] = typer.Option(
        None, "--hotkey", "-k", help="Hotkey to check (overrides default)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Check environment and diagnose issues.

    Verifies that taox is properly configured with all dependencies.
    Shows a checklist of checks and fix commands for any issues found.

    [green]Examples:[/green]
        taox doctor
        taox doctor --verbose
        taox doctor --network finney --wallet mywall
        taox doctor --json
    """
    import json
    import shutil
    import subprocess
    import time
    from pathlib import Path

    settings = get_settings()

    # Use provided wallet/hotkey or defaults
    check_wallet = wallet_name or settings.bittensor.default_wallet
    check_hotkey = hotkey_name or settings.bittensor.default_hotkey

    # Collect results
    checks = []  # Passing checks
    warnings = []  # Non-critical issues
    errors = []  # Critical issues
    fix_commands = []  # Suggested fixes

    # For JSON output
    results = {
        "status": "ok",
        "checks": {},
        "warnings": [],
        "errors": [],
        "fix_commands": [],
    }

    # Helper to add check result
    def add_check(name: str, passed: bool, message: str, fix: str = None):
        results["checks"][name] = {"passed": passed, "message": message}
        if passed:
            checks.append(f"{Symbols.CHECK} {message}")
        else:
            if fix:
                warnings.append(f"{Symbols.WARN} {message}")
                results["warnings"].append(message)
                if fix not in fix_commands:
                    fix_commands.append(fix)
            else:
                errors.append(f"{Symbols.ERROR} {message}")
                results["errors"].append(message)
                results["status"] = "error"

    # === A) Environment Checks ===

    # 1. Python version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 10)
    add_check(
        "python",
        py_ok,
        f"Python version: {py_version}" + ("" if py_ok else " (requires 3.10+)"),
        "Install Python 3.10 or higher" if not py_ok else None,
    )

    # 2. taox version
    add_check("taox", True, f"taox version: {__version__}")

    # 3. btcli installation
    btcli_path = shutil.which("btcli")
    if btcli_path:
        try:
            result = subprocess.run(
                ["btcli", "--version"], capture_output=True, text=True, timeout=10
            )
            btcli_version = result.stdout.strip() or result.stderr.strip()
            version_str = btcli_version.split()[-1] if btcli_version else "unknown"
            add_check("btcli", True, f"btcli installed: {version_str}")
        except Exception:
            add_check("btcli", True, f"btcli installed: {btcli_path}")
    else:
        add_check(
            "btcli",
            False,
            "btcli not found",
            "pip install bittensor-cli",
        )

    # 4. Required dependencies check
    required_deps = ["pexpect", "keyring", "httpx", "pydantic"]
    missing_deps = []
    for dep in required_deps:
        try:
            __import__(dep)
        except ImportError:
            missing_deps.append(dep)

    if missing_deps:
        add_check(
            "dependencies",
            False,
            f"Missing dependencies: {', '.join(missing_deps)}",
            f"pip install {' '.join(missing_deps)}",
        )
    else:
        add_check("dependencies", True, "Required dependencies: installed")

    # === B) Wallet Path Checks ===

    wallet_path = Path.home() / ".bittensor" / "wallets"
    if wallet_path.exists():
        wallets = [w for w in wallet_path.iterdir() if w.is_dir()]
        wallet_count = len(wallets)

        if wallet_count > 0:
            add_check("wallet_dir", True, f"Wallet directory: {wallet_count} wallet(s) found")

            # Check specified wallet exists
            wallet_dir = wallet_path / check_wallet
            if wallet_dir.exists():
                add_check("wallet", True, f"Wallet '{check_wallet}': exists")

                # Check specified hotkey exists
                hotkey_file = wallet_dir / "hotkeys" / check_hotkey
                if hotkey_file.exists():
                    add_check("hotkey", True, f"Hotkey '{check_hotkey}': exists")
                else:
                    add_check(
                        "hotkey",
                        False,
                        f"Hotkey '{check_hotkey}' not found in wallet '{check_wallet}'",
                        f"btcli wallet new_hotkey --wallet.name {check_wallet} --wallet.hotkey {check_hotkey}",
                    )
            else:
                add_check(
                    "wallet",
                    False,
                    f"Wallet '{check_wallet}' not found",
                    f"btcli wallet new_coldkey --wallet.name {check_wallet}",
                )
        else:
            add_check(
                "wallet_dir",
                False,
                "Wallet directory exists but no wallets found",
                "btcli wallet new_coldkey --wallet.name default",
            )
    else:
        add_check(
            "wallet_dir",
            False,
            f"Wallet directory not found: {wallet_path}",
            "btcli wallet new_coldkey --wallet.name default",
        )

    # === C) Network/RPC Checks ===

    # Determine RPC endpoint based on network
    rpc_endpoints = {
        "finney": "https://entrypoint-finney.opentensor.ai:443",
        "test": "https://test.finney.opentensor.ai:443",
        "local": "http://127.0.0.1:9944",
    }
    rpc_url = rpc_endpoints.get(network, rpc_endpoints["finney"])

    if not json_output:
        console.print("[muted]Checking network connectivity...[/muted]", end="\r")

    try:
        import httpx

        start_time = time.time()
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                rpc_url,
                json={"jsonrpc": "2.0", "method": "system_health", "params": [], "id": 1},
                headers={"Content-Type": "application/json"},
            )
            latency_ms = (time.time() - start_time) * 1000

            if response.status_code == 200:
                add_check(
                    "rpc",
                    True,
                    f"{network.capitalize()} RPC: reachable ({latency_ms:.0f}ms)",
                )
                results["checks"]["rpc"]["latency_ms"] = latency_ms
            else:
                add_check(
                    "rpc",
                    False,
                    f"{network.capitalize()} RPC: returned {response.status_code}",
                    "Check your internet connection or try again later",
                )
    except Exception as e:
        add_check(
            "rpc",
            False,
            f"{network.capitalize()} RPC: unreachable ({type(e).__name__})",
            "Check your internet connection or firewall settings",
        )

    if not json_output:
        console.print(" " * 50, end="\r")  # Clear status line

    # === D) API Key Checks ===

    chutes_key = CredentialManager.get_chutes_key()
    taostats_key = CredentialManager.get_taostats_key()
    llm_mode = settings.llm.mode

    # Chutes key: required only when llm_mode=always
    if chutes_key:
        add_check("chutes_api", True, "Chutes API key: configured")
    elif llm_mode == "always":
        add_check(
            "chutes_api",
            False,
            "Chutes API key: missing (required for AI mode)",
            "taox setup",
        )
    else:
        add_check(
            "chutes_api",
            False,
            "Chutes API key: not configured (AI features limited)",
            "taox setup",
        )

    # Taostats key: always optional
    if taostats_key:
        add_check("taostats_api", True, "Taostats API key: configured")
    else:
        add_check(
            "taostats_api",
            False,
            "Taostats API key: not configured (using limited data)",
            "taox setup",
        )

    # === E) Safety Config Checks ===

    # Demo mode
    if settings.demo_mode:
        add_check(
            "demo_mode",
            False,
            "Demo mode: enabled (no real transactions)",
            "Set TAOX_DEMO_MODE=false or edit ~/.taox/config.yml",
        )
    else:
        add_check("demo_mode", True, "Demo mode: disabled")

    # LLM mode status
    add_check("llm_mode", True, f"LLM mode: {llm_mode}")

    # Config directory
    config_path = Path.home() / ".taox"
    if config_path.exists():
        add_check("config", True, f"Config directory: {config_path}")
    else:
        add_check(
            "config",
            False,
            "Config directory not found",
            "taox setup  # Will create config automatically",
        )

    # Rate limit status
    try:
        from taox.data.cache import backoff_manager

        active_backoffs = []
        for key in list(backoff_manager._failures.keys()):
            if not backoff_manager.should_retry(key):
                retry_after = backoff_manager.get_retry_after(key)
                if retry_after:
                    active_backoffs.append(f"{key}: {retry_after:.0f}s")

        if active_backoffs:
            add_check(
                "rate_limits",
                False,
                f"Rate limited: {', '.join(active_backoffs)}",
                "Wait for rate limit to expire",
            )
        else:
            add_check("rate_limits", True, "Rate limits: none active")
    except Exception:
        pass

    # Bittensor SDK (optional)
    try:
        import bittensor

        bt_version = getattr(bittensor, "__version__", "unknown")
        add_check("bittensor_sdk", True, f"Bittensor SDK: {bt_version}")
    except ImportError:
        add_check(
            "bittensor_sdk",
            False,
            "Bittensor SDK: not installed (optional)",
            "pip install bittensor",
        )

    # Collect fix commands
    results["fix_commands"] = fix_commands

    # === Output ===

    if json_output:
        # JSON output mode
        print(json.dumps(results, indent=2))
        if results["status"] == "error":
            raise typer.Exit(1)
        return

    # Rich output mode
    console.print()
    console.print(
        Panel(
            "[primary]taox[/primary] Environment Check",
            box=box.ROUNDED,
            border_style="primary",
        )
    )
    console.print()

    # Display checks
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

    # Verbose: Show dependency versions
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

    # Fix Commands Section
    if fix_commands:
        console.print()
        console.print("[bold]Fix Commands:[/bold]")
        for i, cmd in enumerate(fix_commands, 1):
            console.print(f"  {i}. [command]{cmd}[/command]")

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
