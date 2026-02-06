"""UI components for taox - Rich console, themes, and prompts."""

from taox.ui.console import (
    CommandContext,
    PlanItem,
    TxPhase,
    TxStatus,
    console,
    format_balance_range,
    print_confirmation_prompt,
    print_error,
    print_info,
    print_next_steps,
    print_plan,
    print_share_notice,
    print_success,
    print_title_panel,
    print_tx_lifecycle,
    print_tx_status,
    print_warning,
    redact_address,
    redact_wallet_name,
)
from taox.ui.onboarding import (
    detect_wallets,
    get_wallet_name,
    is_multi_wallet_mode,
    is_onboarding_needed,
    prompt_wallet_selection,
    run_onboarding,
    show_welcome_banner,
)
from taox.ui.theme import Symbols, TaoxColors, taox_theme

__all__ = [
    # Console basics
    "console",
    "print_error",
    "print_success",
    "print_warning",
    "print_info",
    # Layout helpers
    "CommandContext",
    "print_title_panel",
    "print_next_steps",
    # Tx lifecycle
    "TxPhase",
    "TxStatus",
    "print_tx_status",
    "print_tx_lifecycle",
    # Plan view
    "PlanItem",
    "print_plan",
    "print_confirmation_prompt",
    # Share mode
    "redact_address",
    "redact_wallet_name",
    "format_balance_range",
    "print_share_notice",
    # Theme
    "TaoxColors",
    "taox_theme",
    "Symbols",
    # Onboarding
    "run_onboarding",
    "is_onboarding_needed",
    "show_welcome_banner",
    "detect_wallets",
    "is_multi_wallet_mode",
    "prompt_wallet_selection",
    "get_wallet_name",
]
