"""Interactive prompts using InquirerPy for taox."""

from typing import Optional

from InquirerPy import inquirer
from InquirerPy.base.control import Choice

from taox.ui.theme import Symbols


def select_action() -> str:
    """Display main action selection menu.

    Returns:
        Selected action value
    """
    choices = [
        Choice(value="balance", name=f"{Symbols.WALLET} Check Balance"),
        Choice(value="stake", name=f"{Symbols.STAKE} Stake TAO"),
        Choice(value="unstake", name=f"{Symbols.STAKE} Unstake TAO"),
        Choice(value="transfer", name=f"{Symbols.TRANSFER} Transfer TAO"),
        Choice(value="portfolio", name=f"{Symbols.STAR} View Portfolio"),
        Choice(value="validators", name=f"{Symbols.STAR} View Validators"),
        Choice(value="subnets", name=f"{Symbols.SUBNET} View Subnets"),
        Choice(value="chat", name=f"{Symbols.INFO} Chat Mode"),
        Choice(value="quit", name=f"{Symbols.CROSS} Quit"),
    ]

    return inquirer.select(
        message="What would you like to do?",
        choices=choices,
        pointer=f"{Symbols.ARROW} ",
    ).execute()


def select_wallet(wallets: list[dict]) -> Optional[str]:
    """Display wallet selection menu.

    Args:
        wallets: List of wallet dicts with 'name' and 'coldkey_ss58' keys

    Returns:
        Selected wallet name or None
    """
    if not wallets:
        return None

    choices = [
        Choice(
            value=w.get("name"),
            name=f"{w.get('name')} ({w.get('coldkey_ss58', 'N/A')[:12]}...)",
        )
        for w in wallets
    ]

    return inquirer.select(
        message="Select wallet:",
        choices=choices,
        pointer=f"{Symbols.ARROW} ",
    ).execute()


def select_validator(validators: list[dict]) -> Optional[str]:
    """Display validator selection with fuzzy search.

    Args:
        validators: List of validator dicts with 'name' and 'hotkey' keys

    Returns:
        Selected validator hotkey or None
    """
    if not validators:
        return None

    choices = [
        Choice(
            value=v.get("hotkey"),
            name=f"{v.get('name', 'Unknown')} - {v.get('hotkey', '')[:12]}...",
        )
        for v in validators
    ]

    return inquirer.fuzzy(
        message="Select validator:",
        choices=choices,
        max_height="70%",
    ).execute()


def select_subnet(subnets: list[dict]) -> Optional[int]:
    """Display subnet selection menu.

    Args:
        subnets: List of subnet dicts with 'netuid' and 'name' keys

    Returns:
        Selected subnet netuid or None
    """
    if not subnets:
        return None

    choices = [
        Choice(
            value=s.get("netuid"),
            name=f"SN{s.get('netuid')} - {s.get('name', 'Unknown')}",
        )
        for s in sorted(subnets, key=lambda x: x.get("netuid", 0))
    ]

    return inquirer.select(
        message="Select subnet:",
        choices=choices,
        pointer=f"{Symbols.ARROW} ",
    ).execute()


def input_amount(prompt: str = "Enter amount", default: Optional[float] = None) -> float:
    """Prompt for a TAO amount.

    Args:
        prompt: Prompt message
        default: Default value

    Returns:
        Entered amount as float
    """
    result = inquirer.number(
        message=f"{prompt} (TAO):",
        default=default,
        float_allowed=True,
        min_allowed=0.0001,  # Minimum transaction amount
    ).execute()

    return float(result)


def input_address(prompt: str = "Enter SS58 address") -> str:
    """Prompt for an SS58 address.

    Args:
        prompt: Prompt message

    Returns:
        Entered address
    """
    return inquirer.text(
        message=f"{prompt}:",
        validate=lambda x: len(x) == 48 and x.startswith("5"),
        invalid_message="Invalid SS58 address (should be 48 chars starting with 5)",
    ).execute()


def input_netuid(prompt: str = "Enter subnet ID", default: int = 1) -> int:
    """Prompt for a subnet ID.

    Args:
        prompt: Prompt message
        default: Default value

    Returns:
        Entered netuid as int
    """
    result = inquirer.number(
        message=f"{prompt}:",
        default=default,
        min_allowed=0,
        max_allowed=999,
    ).execute()

    return int(result)


def confirm(message: str, default: bool = False) -> bool:
    """Simple confirmation prompt.

    Args:
        message: Confirmation message
        default: Default value

    Returns:
        True if confirmed
    """
    return inquirer.confirm(
        message=message,
        default=default,
    ).execute()
