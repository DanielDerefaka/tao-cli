"""UI components for taox - Rich console, themes, and prompts."""

from taox.ui.console import console, print_error, print_info, print_success, print_warning
from taox.ui.onboarding import (
    detect_wallets,
    get_wallet_name,
    is_multi_wallet_mode,
    is_onboarding_needed,
    prompt_wallet_selection,
    run_onboarding,
    show_welcome_banner,
)
from taox.ui.theme import TaoxColors, taox_theme

__all__ = [
    "console",
    "print_error",
    "print_success",
    "print_warning",
    "print_info",
    "TaoxColors",
    "taox_theme",
    "run_onboarding",
    "is_onboarding_needed",
    "show_welcome_banner",
    "detect_wallets",
    "is_multi_wallet_mode",
    "prompt_wallet_selection",
    "get_wallet_name",
]
