"""Onboarding flow for taox - wallet detection and welcome screen."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.columns import Columns
from rich.text import Text

from taox.ui.console import console, print_success, print_warning, print_error, print_info
from taox.ui.theme import TaoxColors, Symbols
from taox.config.settings import (
    get_settings, load_config_file, save_config_file,
    get_config_path, reset_settings_cache
)


@dataclass
class WalletInfo:
    """Information about a detected wallet."""
    name: str
    path: Path
    has_coldkey: bool = False
    has_hotkey: bool = False
    hotkey_names: list[str] = field(default_factory=list)
    is_encrypted: bool = False
    coldkey_ss58: Optional[str] = None


def get_bittensor_wallets_path() -> Path:
    """Get the default bittensor wallets directory."""
    return Path.home() / ".bittensor" / "wallets"


def detect_wallets() -> list[WalletInfo]:
    """Scan for existing bittensor wallets.

    Looks in ~/.bittensor/wallets/ for wallet directories.
    Each wallet directory may contain:
    - coldkey (encrypted private key file)
    - coldkeypub.txt (public key)
    - hotkeys/ directory with hotkey files
    """
    wallets_path = get_bittensor_wallets_path()
    wallets: list[WalletInfo] = []

    if not wallets_path.exists():
        return wallets

    for wallet_dir in wallets_path.iterdir():
        if not wallet_dir.is_dir():
            continue

        # Skip hidden directories
        if wallet_dir.name.startswith('.'):
            continue

        wallet = WalletInfo(
            name=wallet_dir.name,
            path=wallet_dir,
        )

        # Check for coldkey
        coldkey_file = wallet_dir / "coldkey"
        coldkeypub_file = wallet_dir / "coldkeypub.txt"

        if coldkey_file.exists():
            wallet.has_coldkey = True
            # Check if encrypted (has non-plaintext content)
            try:
                content = coldkey_file.read_bytes()
                # Encrypted files typically start with specific bytes
                wallet.is_encrypted = not content.startswith(b'-----BEGIN')
            except:
                wallet.is_encrypted = True

        # Try to read coldkey SS58 address from coldkeypub.txt
        if coldkeypub_file.exists():
            try:
                wallet.coldkey_ss58 = coldkeypub_file.read_text().strip()
            except:
                pass

        # Check for hotkeys
        hotkeys_dir = wallet_dir / "hotkeys"
        if hotkeys_dir.exists() and hotkeys_dir.is_dir():
            for hotkey_file in hotkeys_dir.iterdir():
                if hotkey_file.is_file() and not hotkey_file.name.startswith('.'):
                    wallet.hotkey_names.append(hotkey_file.name)
                    wallet.has_hotkey = True

        wallets.append(wallet)

    # Sort wallets: 'default' first, then alphabetically
    wallets.sort(key=lambda w: (w.name != 'default', w.name.lower()))

    return wallets


def show_welcome_banner():
    """Display the taox welcome banner with branding."""
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


def show_commands_overview():
    """Display available commands."""
    commands = """
[primary]Commands:[/primary]

  [command]chat[/command]         Start AI chat mode
  [command]balance[/command]      Check your TAO balance
  [command]portfolio[/command]    View stakes and positions
  [command]stake[/command]        Stake TAO to validators
  [command]dashboard[/command]    Full TUI dashboard
  [command]validators[/command]   Browse validators
  [command]subnets[/command]      List all subnets
  [command]setup[/command]        Configure API keys

[muted]Type 'taox --help' for all commands[/muted]
"""
    console.print(commands)


def show_wallet_selection(wallets: list[WalletInfo]) -> Optional[WalletInfo]:
    """Display wallet selection menu and return selected wallet.

    Returns None if user wants to create a new wallet.
    """
    console.print("\n[primary]Detected Wallets:[/primary]\n")

    # Create selection table
    table = Table(
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
        show_header=True,
        header_style="table.header",
    )
    table.add_column("#", style="muted", width=3)
    table.add_column("Wallet Name", style="primary")
    table.add_column("Address", style="address")
    table.add_column("Hotkeys", style="muted")
    table.add_column("Status", style="muted")

    for i, wallet in enumerate(wallets, 1):
        # Format address
        address = wallet.coldkey_ss58 or "Unknown"
        if len(address) > 16:
            address = f"{address[:8]}...{address[-8:]}"

        # Format hotkeys
        hotkey_count = len(wallet.hotkey_names)
        hotkeys_str = f"{hotkey_count} hotkey{'s' if hotkey_count != 1 else ''}"
        if hotkey_count > 0 and hotkey_count <= 3:
            hotkeys_str = ", ".join(wallet.hotkey_names)

        # Status indicator
        status_parts = []
        if wallet.is_encrypted:
            status_parts.append(f"[warning]{Symbols.LOCK} encrypted[/warning]")
        else:
            status_parts.append(f"[success]{Symbols.UNLOCK} ready[/success]")

        status = " ".join(status_parts) if status_parts else "-"

        table.add_row(
            str(i),
            wallet.name,
            address,
            hotkeys_str,
            status,
        )

    console.print(table)
    console.print()

    # Show selection prompt
    console.print("[muted]Enter wallet number, or:[/muted]")
    console.print("[muted]  'a' - Use all wallets (prompt each time)[/muted]")
    console.print("[muted]  'n' - Create new wallet[/muted]")
    console.print("[muted]  's' - Skip (use demo mode)[/muted]")
    console.print()

    while True:
        try:
            choice = console.input("[prompt]Select wallet:[/prompt] ").strip().lower()

            if choice == 'a':
                return "all"  # Signal to use all wallets

            if choice == 'n':
                return None  # Signal to create new wallet

            if choice == 's':
                return "skip"  # Signal to skip/demo mode

            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(wallets):
                    return wallets[idx]
                else:
                    console.print(f"[error]Please enter 1-{len(wallets)}[/error]")
            else:
                # Try to match by name
                for wallet in wallets:
                    if wallet.name.lower() == choice:
                        return wallet
                console.print("[error]Invalid selection. Enter a number or wallet name.[/error]")

        except (EOFError, KeyboardInterrupt):
            console.print("\n[muted]Cancelled[/muted]")
            return "skip"


def select_hotkey(wallet: WalletInfo) -> Optional[str]:
    """Select a hotkey from the wallet.

    Returns the hotkey name to use.
    """
    if not wallet.hotkey_names:
        console.print("[warning]No hotkeys found for this wallet.[/warning]")
        return None

    if len(wallet.hotkey_names) == 1:
        hotkey = wallet.hotkey_names[0]
        console.print(f"[info]Using hotkey: {hotkey}[/info]")
        return hotkey

    console.print("\n[primary]Available Hotkeys:[/primary]")
    for i, hk in enumerate(wallet.hotkey_names, 1):
        console.print(f"  [muted]{i}.[/muted] [primary]{hk}[/primary]")
    console.print()

    while True:
        try:
            choice = console.input("[prompt]Select hotkey (or Enter for 'default'):[/prompt] ").strip()

            if not choice:
                # Default selection
                if "default" in wallet.hotkey_names:
                    return "default"
                return wallet.hotkey_names[0]

            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(wallet.hotkey_names):
                    return wallet.hotkey_names[idx]
                console.print(f"[error]Please enter 1-{len(wallet.hotkey_names)}[/error]")
            else:
                # Try to match by name
                if choice in wallet.hotkey_names:
                    return choice
                console.print("[error]Hotkey not found. Enter a number or name.[/error]")

        except (EOFError, KeyboardInterrupt):
            console.print("\n[muted]Using first hotkey[/muted]")
            return wallet.hotkey_names[0]


def save_wallet_config(wallet_name: str, hotkey_name: str):
    """Save selected wallet and hotkey to config."""
    config = load_config_file()

    # Disable demo mode since user selected a real wallet
    config["demo_mode"] = False

    if "bittensor" not in config:
        config["bittensor"] = {}

    config["bittensor"]["default_wallet"] = wallet_name
    config["bittensor"]["default_hotkey"] = hotkey_name
    config["bittensor"]["multi_wallet_mode"] = False

    save_config_file(config)
    reset_settings_cache()


def mark_onboarding_complete():
    """Mark that onboarding has been completed."""
    config = load_config_file()
    config["onboarding_complete"] = True
    save_config_file(config)
    reset_settings_cache()


def is_onboarding_needed() -> bool:
    """Check if onboarding should be shown."""
    config = load_config_file()
    return not config.get("onboarding_complete", False)


def prompt_create_wallet() -> bool:
    """Ask user if they want to create a new wallet.

    Returns True if they want to create one.
    """
    console.print("\n[warning]No wallets detected.[/warning]")
    console.print("[muted]You need a Bittensor wallet to use taox features.[/muted]\n")

    console.print("[primary]Options:[/primary]")
    console.print("  [command]1.[/command] Create a new wallet")
    console.print("  [command]2.[/command] Continue in demo mode")
    console.print("  [command]3.[/command] I have a wallet elsewhere (specify path)")
    console.print()

    while True:
        try:
            choice = console.input("[prompt]Choice (1/2/3):[/prompt] ").strip()

            if choice == "1":
                return "create"
            elif choice == "2":
                return "demo"
            elif choice == "3":
                return "custom_path"
            else:
                console.print("[error]Please enter 1, 2, or 3[/error]")

        except (EOFError, KeyboardInterrupt):
            console.print("\n[muted]Continuing in demo mode[/muted]")
            return "demo"


def run_wallet_creation():
    """Guide user through wallet creation using btcli."""
    import subprocess

    console.print("\n[primary]Creating New Wallet[/primary]\n")
    console.print("[muted]This will use btcli to create a new coldkey and hotkey.[/muted]")
    console.print("[warning]Make sure to save your mnemonic phrase securely![/warning]\n")

    # Get wallet name
    wallet_name = console.input("[prompt]Wallet name (default: 'default'):[/prompt] ").strip()
    if not wallet_name:
        wallet_name = "default"

    # Get hotkey name
    hotkey_name = console.input("[prompt]Hotkey name (default: 'default'):[/prompt] ").strip()
    if not hotkey_name:
        hotkey_name = "default"

    console.print()

    # Create coldkey
    console.print("[info]Creating coldkey...[/info]")
    console.print(f"[muted]Running: btcli wallet new-coldkey --wallet {wallet_name}[/muted]\n")

    try:
        result = subprocess.run(
            ["btcli", "wallet", "new-coldkey", "--wallet", wallet_name],
            check=False,
        )

        if result.returncode != 0:
            print_error("Failed to create coldkey. Make sure btcli is installed.")
            return None, None

        # Create hotkey
        console.print("\n[info]Creating hotkey...[/info]")
        console.print(f"[muted]Running: btcli wallet new-hotkey --wallet {wallet_name} --hotkey {hotkey_name}[/muted]\n")

        result = subprocess.run(
            ["btcli", "wallet", "new-hotkey", "--wallet", wallet_name, "--hotkey", hotkey_name],
            check=False,
        )

        if result.returncode != 0:
            print_error("Failed to create hotkey.")
            return wallet_name, None

        print_success(f"\nWallet '{wallet_name}' created successfully!")
        return wallet_name, hotkey_name

    except FileNotFoundError:
        print_error("btcli not found. Install with: pip install bittensor-cli")
        return None, None


def set_custom_wallet_path():
    """Allow user to specify a custom wallet path."""
    console.print("\n[primary]Custom Wallet Path[/primary]\n")
    console.print(f"[muted]Current path: {get_bittensor_wallets_path()}[/muted]")

    custom_path = console.input("[prompt]Enter wallet directory path:[/prompt] ").strip()

    if not custom_path:
        console.print("[muted]Cancelled[/muted]")
        return

    path = Path(custom_path).expanduser()

    if not path.exists():
        print_error(f"Path does not exist: {path}")
        return

    if not path.is_dir():
        print_error(f"Not a directory: {path}")
        return

    # Save to config
    config = load_config_file()
    if "bittensor" not in config:
        config["bittensor"] = {}
    config["bittensor"]["wallet_path"] = str(path)
    save_config_file(config)
    reset_settings_cache()

    print_success(f"Wallet path set to: {path}")


def run_onboarding() -> bool:
    """Run the full onboarding flow.

    Returns True if onboarding completed successfully.
    """
    console.clear()

    # Show welcome banner
    show_welcome_banner()

    # Show commands
    show_commands_overview()

    # Detect wallets
    wallets = detect_wallets()

    if not wallets:
        # No wallets found
        choice = prompt_create_wallet()

        if choice == "create":
            wallet_name, hotkey_name = run_wallet_creation()
            if wallet_name:
                save_wallet_config(wallet_name, hotkey_name or "default")
                mark_onboarding_complete()
                return True
            return False

        elif choice == "custom_path":
            set_custom_wallet_path()
            # Re-detect wallets with new path
            wallets = detect_wallets()
            if not wallets:
                console.print("[muted]No wallets found at custom path. Continuing in demo mode.[/muted]")
                _enable_demo_mode()
                mark_onboarding_complete()
                return True

        else:  # demo mode
            _enable_demo_mode()
            mark_onboarding_complete()
            return True

    # Wallets found - let user select
    selection = show_wallet_selection(wallets)

    if selection == "skip":
        _enable_demo_mode()
        mark_onboarding_complete()
        return True

    elif selection == "all":
        # User wants to use all wallets - will be prompted each time
        _enable_multi_wallet_mode(wallets)
        mark_onboarding_complete()
        console.print()
        print_success("Setup complete! You'll be prompted to select a wallet when needed.")
        return True

    elif selection is None:
        # User wants to create new wallet
        wallet_name, hotkey_name = run_wallet_creation()
        if wallet_name:
            save_wallet_config(wallet_name, hotkey_name or "default")
            mark_onboarding_complete()
            return True
        return False

    else:
        # User selected a wallet
        wallet = selection
        console.print(f"\n[success]{Symbols.CHECK} Selected wallet: {wallet.name}[/success]")

        # Select hotkey if multiple
        hotkey = select_hotkey(wallet)
        if hotkey:
            console.print(f"[success]{Symbols.CHECK} Selected hotkey: {hotkey}[/success]")

        # Save to config
        save_wallet_config(wallet.name, hotkey or "default")

        # Show encryption notice
        if wallet.is_encrypted:
            console.print(
                f"\n[info]{Symbols.LOCK} Your wallet is encrypted. "
                f"You'll be prompted for your password when needed.[/info]"
            )

        mark_onboarding_complete()
        console.print()
        print_success("Setup complete! Run 'taox chat' to get started.")
        return True


def _enable_demo_mode():
    """Enable demo mode in config."""
    config = load_config_file()
    config["demo_mode"] = True
    save_config_file(config)
    reset_settings_cache()
    console.print("[info]Demo mode enabled. No real transactions will be executed.[/info]")


def _enable_multi_wallet_mode(wallets: list[WalletInfo]):
    """Enable multi-wallet mode - prompts for wallet selection when needed."""
    config = load_config_file()

    # Disable demo mode since user has real wallets
    config["demo_mode"] = False

    if "bittensor" not in config:
        config["bittensor"] = {}

    # Store all wallet names for reference
    config["bittensor"]["multi_wallet_mode"] = True
    config["bittensor"]["available_wallets"] = [w.name for w in wallets]
    # Set first wallet as default fallback
    config["bittensor"]["default_wallet"] = wallets[0].name if wallets else "default"
    config["bittensor"]["default_hotkey"] = "default"

    save_config_file(config)
    reset_settings_cache()

    console.print(f"\n[success]{Symbols.CHECK} Multi-wallet mode enabled[/success]")
    console.print(f"[info]Available wallets: {', '.join(w.name for w in wallets)}[/info]")
    console.print("[muted]Use --wallet <name> to specify a wallet, or you'll be prompted.[/muted]")


def is_multi_wallet_mode() -> bool:
    """Check if multi-wallet mode is enabled."""
    config = load_config_file()
    return config.get("bittensor", {}).get("multi_wallet_mode", False)


def get_available_wallets() -> list[str]:
    """Get list of available wallet names from config."""
    config = load_config_file()
    return config.get("bittensor", {}).get("available_wallets", [])


def prompt_wallet_selection() -> Optional[str]:
    """Prompt user to select a wallet at runtime.

    Used when multi-wallet mode is enabled and no --wallet flag provided.
    """
    wallets = detect_wallets()

    if not wallets:
        console.print("[warning]No wallets found[/warning]")
        return None

    if len(wallets) == 1:
        return wallets[0].name

    console.print("\n[primary]Select wallet:[/primary]")
    for i, wallet in enumerate(wallets, 1):
        address = wallet.coldkey_ss58 or "Unknown"
        if len(address) > 16:
            address = f"{address[:8]}...{address[-8:]}"
        console.print(f"  [muted]{i}.[/muted] [primary]{wallet.name}[/primary] ({address})")

    while True:
        try:
            choice = console.input("[prompt]Wallet #:[/prompt] ").strip()

            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(wallets):
                    return wallets[idx].name
                console.print(f"[error]Please enter 1-{len(wallets)}[/error]")
            else:
                # Try to match by name
                for wallet in wallets:
                    if wallet.name.lower() == choice.lower():
                        return wallet.name
                console.print("[error]Wallet not found[/error]")

        except (EOFError, KeyboardInterrupt):
            return wallets[0].name


def show_current_wallet():
    """Display the currently configured wallet."""
    settings = get_settings()
    wallet_name = settings.bittensor.default_wallet
    hotkey_name = settings.bittensor.default_hotkey

    console.print(f"[primary]Current Wallet:[/primary] {wallet_name}")
    console.print(f"[primary]Current Hotkey:[/primary] {hotkey_name}")

    # Try to find the actual wallet
    wallets = detect_wallets()
    for wallet in wallets:
        if wallet.name == wallet_name:
            if wallet.coldkey_ss58:
                console.print(f"[primary]Address:[/primary] [address]{wallet.coldkey_ss58}[/address]")
            break


def get_wallet_name(provided: Optional[str] = None) -> str:
    """Get wallet name to use, prompting if needed.

    Args:
        provided: Wallet name provided via --wallet flag

    Returns:
        Wallet name to use for the operation
    """
    # If explicitly provided, use that
    if provided:
        return provided

    # If multi-wallet mode, prompt for selection
    if is_multi_wallet_mode():
        selected = prompt_wallet_selection()
        if selected:
            return selected

    # Fall back to default from settings
    settings = get_settings()
    return settings.bittensor.default_wallet
