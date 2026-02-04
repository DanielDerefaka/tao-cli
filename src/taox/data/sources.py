"""Data source attribution and response grounding for taox.

This module ensures all responses are grounded in real data with clear attribution:
- Every data point is tagged with its source
- Facts are separated from assumptions
- Missing data triggers honest messaging
- Caching is transparent with staleness indicators
"""

import logging
from enum import Enum
from datetime import datetime
from typing import Optional, Any, Generic, TypeVar
from dataclasses import dataclass, field

from taox.config.settings import get_settings


logger = logging.getLogger(__name__)

T = TypeVar("T")


class DataSource(str, Enum):
    """Sources of data in taox."""

    # Live data sources
    BITTENSOR_SDK = "bittensor_sdk"  # Direct SDK calls to chain
    TAOSTATS_API = "taostats_api"  # Taostats API calls
    BTCLI_OUTPUT = "btcli_output"  # Parsed btcli command output

    # Cached data
    CACHE_FRESH = "cache_fresh"  # Cached data within TTL
    CACHE_STALE = "cache_stale"  # Cached data past TTL (fallback)

    # Fallback/Demo
    MOCK_DATA = "mock_data"  # Static mock data for demo mode
    USER_INPUT = "user_input"  # Value provided by user

    # Unknown/Error
    UNAVAILABLE = "unavailable"  # Data could not be fetched
    UNKNOWN = "unknown"  # Source not tracked


@dataclass
class SourceAttribution:
    """Attribution info for a piece of data."""

    source: DataSource
    timestamp: datetime = field(default_factory=datetime.now)
    cache_age_seconds: Optional[float] = None
    api_endpoint: Optional[str] = None
    is_fallback: bool = False
    error_message: Optional[str] = None

    @property
    def is_live(self) -> bool:
        """Check if data is from a live source."""
        return self.source in (
            DataSource.BITTENSOR_SDK,
            DataSource.TAOSTATS_API,
            DataSource.BTCLI_OUTPUT,
        )

    @property
    def is_cached(self) -> bool:
        """Check if data is from cache."""
        return self.source in (DataSource.CACHE_FRESH, DataSource.CACHE_STALE)

    @property
    def is_mock(self) -> bool:
        """Check if data is mock/demo data."""
        return self.source == DataSource.MOCK_DATA

    def to_label(self, verbose: bool = False) -> str:
        """Get human-readable label for the source.

        Args:
            verbose: Include additional details like timestamp

        Returns:
            Source label string
        """
        labels = {
            DataSource.BITTENSOR_SDK: "from Bittensor chain",
            DataSource.TAOSTATS_API: "from Taostats API",
            DataSource.BTCLI_OUTPUT: "from btcli",
            DataSource.CACHE_FRESH: "from cache",
            DataSource.CACHE_STALE: "from cache (stale)",
            DataSource.MOCK_DATA: "demo data",
            DataSource.USER_INPUT: "user provided",
            DataSource.UNAVAILABLE: "unavailable",
            DataSource.UNKNOWN: "unknown source",
        }

        label = labels.get(self.source, str(self.source))

        if verbose:
            if self.cache_age_seconds is not None:
                age = int(self.cache_age_seconds)
                if age < 60:
                    label += f" ({age}s ago)"
                elif age < 3600:
                    label += f" ({age // 60}m ago)"
                else:
                    label += f" ({age // 3600}h ago)"

            if self.is_fallback:
                label += " [fallback]"

        return label


@dataclass
class GroundedData(Generic[T]):
    """Data container with source attribution.

    Wraps any data value with information about where it came from.
    """

    value: T
    attribution: SourceAttribution
    assumptions: list[str] = field(default_factory=list)

    @property
    def is_available(self) -> bool:
        """Check if data is actually available."""
        return (
            self.value is not None
            and self.attribution.source != DataSource.UNAVAILABLE
        )

    @property
    def is_reliable(self) -> bool:
        """Check if data is from a reliable (non-mock, non-stale) source."""
        return self.attribution.is_live or self.attribution.source == DataSource.CACHE_FRESH

    def add_assumption(self, assumption: str) -> None:
        """Add an assumption about this data."""
        self.assumptions.append(assumption)

    def format_for_display(self, show_source: bool = True) -> str:
        """Format the data value with optional source annotation.

        Args:
            show_source: Whether to include source label

        Returns:
            Formatted string
        """
        value_str = str(self.value) if self.value is not None else "N/A"

        if show_source:
            return f"{value_str} ({self.attribution.to_label()})"

        return value_str


@dataclass
class DataAvailability:
    """Tracks what data sources are available."""

    taostats_api: bool = False
    bittensor_sdk: bool = False
    cache_available: bool = True
    demo_mode: bool = False

    taostats_error: Optional[str] = None
    sdk_error: Optional[str] = None

    @property
    def any_live_source(self) -> bool:
        """Check if any live data source is available."""
        return self.taostats_api or self.bittensor_sdk

    def get_status_message(self) -> str:
        """Get human-readable status message."""
        if self.demo_mode:
            return "Running in demo mode with sample data"

        if self.any_live_source:
            sources = []
            if self.taostats_api:
                sources.append("Taostats API")
            if self.bittensor_sdk:
                sources.append("Bittensor SDK")
            return f"Connected to: {', '.join(sources)}"

        # No live sources
        messages = ["Running in limited mode"]
        if self.taostats_error:
            messages.append(f"Taostats: {self.taostats_error}")
        if self.sdk_error:
            messages.append(f"SDK: {self.sdk_error}")

        if self.cache_available:
            messages.append("Using cached data where available")

        return " | ".join(messages)


class DataGrounder:
    """Service for grounding data with source attribution.

    Provides methods to:
    - Check data source availability
    - Wrap data with attribution
    - Handle fallback chains
    - Generate honest messaging about data limitations
    """

    def __init__(self):
        """Initialize the data grounder."""
        self.settings = get_settings()
        self._availability: Optional[DataAvailability] = None

    @property
    def availability(self) -> DataAvailability:
        """Get current data availability status."""
        if self._availability is None:
            self._availability = self._check_availability()
        return self._availability

    def refresh_availability(self) -> DataAvailability:
        """Refresh the availability check."""
        self._availability = self._check_availability()
        return self._availability

    def _check_availability(self) -> DataAvailability:
        """Check what data sources are available."""
        from taox.security.credentials import CredentialManager

        availability = DataAvailability(
            demo_mode=self.settings.demo_mode,
        )

        if self.settings.demo_mode:
            return availability

        # Check Taostats API key
        taostats_key = CredentialManager.get_taostats_key()
        if taostats_key:
            availability.taostats_api = True
        else:
            availability.taostats_error = "No API key configured"

        # Check Bittensor SDK
        try:
            from taox.data.sdk import BITTENSOR_AVAILABLE
            availability.bittensor_sdk = BITTENSOR_AVAILABLE
            if not BITTENSOR_AVAILABLE:
                availability.sdk_error = "SDK not installed"
        except ImportError:
            availability.sdk_error = "SDK not installed"

        return availability

    def ground(
        self,
        value: T,
        source: DataSource,
        cache_age: Optional[float] = None,
        endpoint: Optional[str] = None,
        is_fallback: bool = False,
        error: Optional[str] = None,
    ) -> GroundedData[T]:
        """Wrap a value with source attribution.

        Args:
            value: The data value
            source: Where the data came from
            cache_age: Age of cached data in seconds
            endpoint: API endpoint used (if applicable)
            is_fallback: Whether this is fallback data
            error: Error message if data fetch failed

        Returns:
            GroundedData with attribution
        """
        attribution = SourceAttribution(
            source=source,
            cache_age_seconds=cache_age,
            api_endpoint=endpoint,
            is_fallback=is_fallback,
            error_message=error,
        )

        return GroundedData(value=value, attribution=attribution)

    def unavailable(self, reason: str) -> GroundedData[None]:
        """Create a grounded response for unavailable data.

        Args:
            reason: Why the data is unavailable

        Returns:
            GroundedData with UNAVAILABLE source
        """
        return self.ground(
            value=None,
            source=DataSource.UNAVAILABLE,
            error=reason,
        )

    def get_limitation_message(self) -> Optional[str]:
        """Get a message about current data limitations.

        Returns:
            Limitation message or None if no limitations
        """
        if self.settings.demo_mode:
            return "Running in demo mode - showing sample data, not real balances"

        if not self.availability.any_live_source:
            parts = ["Running in limited mode"]

            if not self.availability.taostats_api:
                parts.append("no Taostats API key")
            if not self.availability.bittensor_sdk:
                parts.append("Bittensor SDK unavailable")

            parts.append("run 'taox setup' to configure")
            return " | ".join(parts)

        return None


# Global instance
_data_grounder: Optional[DataGrounder] = None


def get_data_grounder() -> DataGrounder:
    """Get the global DataGrounder instance."""
    global _data_grounder
    if _data_grounder is None:
        _data_grounder = DataGrounder()
    return _data_grounder


# =============================================================================
# Response Formatting
# =============================================================================

@dataclass
class GroundedResponse:
    """A response with data grounding information."""

    message: str
    data_sources: list[SourceAttribution] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def add_data(self, grounded: GroundedData) -> None:
        """Add grounded data to this response."""
        self.data_sources.append(grounded.attribution)
        self.assumptions.extend(grounded.assumptions)

    def add_limitation(self, limitation: str) -> None:
        """Add a limitation note."""
        self.limitations.append(limitation)

    def add_suggestion(self, suggestion: str) -> None:
        """Add a suggested action."""
        self.suggestions.append(suggestion)

    def format(self, show_sources: bool = True, show_assumptions: bool = True) -> str:
        """Format the response with annotations.

        Args:
            show_sources: Include source attribution
            show_assumptions: Include assumptions section

        Returns:
            Formatted response string
        """
        parts = [self.message]

        if show_sources and self.data_sources:
            # Deduplicate sources
            unique_sources = list({s.source: s for s in self.data_sources}.values())
            source_labels = [s.to_label() for s in unique_sources]
            parts.append(f"\n[dim]Sources: {', '.join(source_labels)}[/dim]")

        if show_assumptions and self.assumptions:
            parts.append("\n[dim]Assumptions:[/dim]")
            for assumption in self.assumptions:
                parts.append(f"[dim]  • {assumption}[/dim]")

        if self.limitations:
            parts.append("\n[warning]Limitations:[/warning]")
            for limitation in self.limitations:
                parts.append(f"[warning]  • {limitation}[/warning]")

        if self.suggestions:
            parts.append("\n[muted]Suggestions:[/muted]")
            for suggestion in self.suggestions:
                parts.append(f"[muted]  • {suggestion}[/muted]")

        return "\n".join(parts)


# =============================================================================
# Helper Functions
# =============================================================================

def format_balance_with_source(
    balance: float,
    source: DataSource,
    show_source: bool = True,
) -> str:
    """Format a balance value with source attribution.

    Args:
        balance: Balance in TAO
        source: Data source
        show_source: Whether to show source label

    Returns:
        Formatted balance string
    """
    formatted = f"{balance:,.4f} τ"

    if show_source:
        grounder = get_data_grounder()
        grounded = grounder.ground(balance, source)
        return grounded.format_for_display(show_source=True)

    return formatted


def check_data_available(
    require_live: bool = False,
    require_taostats: bool = False,
    require_sdk: bool = False,
) -> tuple[bool, Optional[str]]:
    """Check if required data sources are available.

    Args:
        require_live: Require at least one live source
        require_taostats: Require Taostats API
        require_sdk: Require Bittensor SDK

    Returns:
        Tuple of (available, error_message)
    """
    grounder = get_data_grounder()
    availability = grounder.availability

    if availability.demo_mode:
        return True, "Running in demo mode with sample data"

    if require_taostats and not availability.taostats_api:
        return False, "Taostats API not available - run 'taox setup' to configure"

    if require_sdk and not availability.bittensor_sdk:
        return False, "Bittensor SDK not available - install with 'pip install bittensor'"

    if require_live and not availability.any_live_source:
        return False, "No live data sources available - run 'taox setup' to configure"

    return True, None
