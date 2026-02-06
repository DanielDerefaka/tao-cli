"""Theme and color definitions for taox."""

from dataclasses import dataclass

from rich.theme import Theme


@dataclass(frozen=True)
class TaoxColors:
    """Color palette for taox UI."""

    # Primary colors
    PRIMARY = "#61afef"
    SECONDARY = "#c678dd"

    # Status colors
    SUCCESS = "#98c379"
    WARNING = "#e5c07b"
    ERROR = "#e06c75"
    INFO = "#56b6c2"

    # Bittensor specific
    TAO = "#00d4aa"
    ALPHA = "#ff6b6b"

    # UI elements
    MUTED = "#5c6370"
    BORDER = "#3e4451"
    HIGHLIGHT = "#e5c07b"

    # Text
    TEXT = "#abb2bf"
    TEXT_BRIGHT = "#ffffff"
    TEXT_DIM = "#5c6370"


# Rich theme for console styling
taox_theme = Theme(
    {
        # Primary styles
        "primary": f"bold {TaoxColors.PRIMARY}",
        "secondary": f"{TaoxColors.SECONDARY}",
        # Status styles
        "success": f"bold {TaoxColors.SUCCESS}",
        "warning": f"bold {TaoxColors.WARNING}",
        "error": f"bold {TaoxColors.ERROR}",
        "info": f"{TaoxColors.INFO}",
        # Bittensor styles
        "tao": f"bold {TaoxColors.TAO}",
        "alpha": f"{TaoxColors.ALPHA}",
        "balance": f"bold {TaoxColors.TAO}",
        "address": f"{TaoxColors.PRIMARY}",
        "validator": f"bold {TaoxColors.SECONDARY}",
        "subnet": f"bold {TaoxColors.INFO}",
        # UI styles
        "muted": f"{TaoxColors.MUTED}",
        "highlight": f"bold {TaoxColors.HIGHLIGHT}",
        "prompt": f"bold {TaoxColors.PRIMARY}",
        "command": f"bold {TaoxColors.SUCCESS}",
        # Table styles
        "table.header": f"bold {TaoxColors.PRIMARY}",
        "table.border": f"{TaoxColors.BORDER}",
    }
)


# Unicode symbols used in the UI
class Symbols:
    """Unicode symbols for UI elements."""

    TAO = "τ"
    CHECK = "✓"
    CROSS = "✗"
    ERROR = "✗"
    ARROW = "→"
    BULLET = "•"
    STAR = "★"
    WARN = "⚠"
    INFO = "ℹ"
    LOCK = "🔒"
    UNLOCK = "🔓"
    WALLET = "💰"
    STAKE = "📊"
    TRANSFER = "🔄"
    SUBNET = "🌐"
    ALPHA = "α"
    # Tx lifecycle
    PENDING = "⏳"
    SIGNING = "✍️"
    BROADCAST = "📡"
    IN_BLOCK = "📦"
    FINALIZED = "✅"
    FAILED = "❌"
    # Next steps
    NEXT = "➜"
