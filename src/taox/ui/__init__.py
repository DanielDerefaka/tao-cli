"""UI components for taox - Rich console, themes, and prompts."""

from taox.ui.console import console, print_error, print_success, print_warning, print_info
from taox.ui.theme import TaoxColors, taox_theme

__all__ = [
    "console",
    "print_error",
    "print_success",
    "print_warning",
    "print_info",
    "TaoxColors",
    "taox_theme",
]
