"""Tests for data source attribution and grounding."""

import pytest
from datetime import datetime, timedelta

from taox.data.sources import (
    DataSource,
    SourceAttribution,
    GroundedData,
    DataAvailability,
    DataGrounder,
    GroundedResponse,
    format_balance_with_source,
    check_data_available,
)
from taox.data.cache import (
    CacheStatus,
    CacheEntry,
    CacheResult,
    BackoffManager,
)


class TestDataSource:
    """Test DataSource enum."""

    def test_live_sources(self):
        """Test live source identification."""
        live = [DataSource.BITTENSOR_SDK, DataSource.TAOSTATS_API, DataSource.BTCLI_OUTPUT]
        for source in live:
            assert source.value in ["bittensor_sdk", "taostats_api", "btcli_output"]

    def test_cached_sources(self):
        """Test cached source identification."""
        assert DataSource.CACHE_FRESH.value == "cache_fresh"
        assert DataSource.CACHE_STALE.value == "cache_stale"


class TestSourceAttribution:
    """Test SourceAttribution."""

    def test_is_live(self):
        """Test live source detection."""
        live_attr = SourceAttribution(source=DataSource.TAOSTATS_API)
        assert live_attr.is_live is True

        cache_attr = SourceAttribution(source=DataSource.CACHE_FRESH)
        assert cache_attr.is_live is False

    def test_is_cached(self):
        """Test cache detection."""
        cache_attr = SourceAttribution(source=DataSource.CACHE_FRESH)
        assert cache_attr.is_cached is True

        live_attr = SourceAttribution(source=DataSource.TAOSTATS_API)
        assert live_attr.is_cached is False

    def test_is_mock(self):
        """Test mock detection."""
        mock_attr = SourceAttribution(source=DataSource.MOCK_DATA)
        assert mock_attr.is_mock is True

        live_attr = SourceAttribution(source=DataSource.TAOSTATS_API)
        assert live_attr.is_mock is False

    def test_to_label_basic(self):
        """Test basic label generation."""
        attr = SourceAttribution(source=DataSource.TAOSTATS_API)
        label = attr.to_label()
        assert "Taostats" in label

    def test_to_label_with_age(self):
        """Test label with cache age."""
        attr = SourceAttribution(source=DataSource.CACHE_FRESH, cache_age_seconds=45)
        label = attr.to_label(verbose=True)
        assert "45s ago" in label

    def test_to_label_with_fallback(self):
        """Test label with fallback marker."""
        attr = SourceAttribution(source=DataSource.CACHE_STALE, is_fallback=True)
        label = attr.to_label(verbose=True)
        assert "fallback" in label.lower()


class TestGroundedData:
    """Test GroundedData container."""

    def test_is_available(self):
        """Test availability check."""
        available = GroundedData(
            value=100.0,
            attribution=SourceAttribution(source=DataSource.TAOSTATS_API),
        )
        assert available.is_available is True

        unavailable = GroundedData(
            value=None,
            attribution=SourceAttribution(source=DataSource.UNAVAILABLE),
        )
        assert unavailable.is_available is False

    def test_is_reliable(self):
        """Test reliability check."""
        live = GroundedData(
            value=100.0,
            attribution=SourceAttribution(source=DataSource.TAOSTATS_API),
        )
        assert live.is_reliable is True

        stale = GroundedData(
            value=100.0,
            attribution=SourceAttribution(source=DataSource.CACHE_STALE),
        )
        assert stale.is_reliable is False

        mock = GroundedData(
            value=100.0,
            attribution=SourceAttribution(source=DataSource.MOCK_DATA),
        )
        assert mock.is_reliable is False

    def test_add_assumption(self):
        """Test adding assumptions."""
        data = GroundedData(
            value=100.0,
            attribution=SourceAttribution(source=DataSource.MOCK_DATA),
        )
        data.add_assumption("Using sample data")
        assert len(data.assumptions) == 1
        assert "sample" in data.assumptions[0].lower()

    def test_format_for_display(self):
        """Test display formatting."""
        data = GroundedData(
            value=100.5,
            attribution=SourceAttribution(source=DataSource.TAOSTATS_API),
        )
        formatted = data.format_for_display(show_source=True)
        assert "100.5" in formatted
        assert "Taostats" in formatted

        no_source = data.format_for_display(show_source=False)
        assert "100.5" in no_source
        assert "Taostats" not in no_source


class TestDataAvailability:
    """Test DataAvailability tracking."""

    def test_any_live_source_both(self):
        """Test when both sources available."""
        avail = DataAvailability(taostats_api=True, bittensor_sdk=True)
        assert avail.any_live_source is True

    def test_any_live_source_one(self):
        """Test when one source available."""
        avail = DataAvailability(taostats_api=True, bittensor_sdk=False)
        assert avail.any_live_source is True

    def test_any_live_source_none(self):
        """Test when no sources available."""
        avail = DataAvailability(taostats_api=False, bittensor_sdk=False)
        assert avail.any_live_source is False

    def test_status_message_demo(self):
        """Test status message in demo mode."""
        avail = DataAvailability(demo_mode=True)
        msg = avail.get_status_message()
        assert "demo" in msg.lower()

    def test_status_message_connected(self):
        """Test status message when connected."""
        avail = DataAvailability(taostats_api=True)
        msg = avail.get_status_message()
        assert "Connected" in msg or "Taostats" in msg


class TestDataGrounder:
    """Test DataGrounder service."""

    def test_ground(self):
        """Test basic grounding."""
        grounder = DataGrounder()
        grounded = grounder.ground(100.0, DataSource.TAOSTATS_API)
        assert grounded.value == 100.0
        assert grounded.attribution.source == DataSource.TAOSTATS_API

    def test_ground_with_metadata(self):
        """Test grounding with full metadata."""
        grounder = DataGrounder()
        grounded = grounder.ground(
            100.0,
            DataSource.CACHE_STALE,
            cache_age=300,
            is_fallback=True,
            error="API timeout",
        )
        assert grounded.attribution.cache_age_seconds == 300
        assert grounded.attribution.is_fallback is True
        assert grounded.attribution.error_message == "API timeout"

    def test_unavailable(self):
        """Test creating unavailable response."""
        grounder = DataGrounder()
        grounded = grounder.unavailable("Network error")
        assert grounded.value is None
        assert grounded.attribution.source == DataSource.UNAVAILABLE
        assert "Network error" in grounded.attribution.error_message


class TestGroundedResponse:
    """Test GroundedResponse formatting."""

    def test_add_data(self):
        """Test adding grounded data."""
        response = GroundedResponse(message="Balance check")
        data = GroundedData(
            value=100.0,
            attribution=SourceAttribution(source=DataSource.BITTENSOR_SDK),
            assumptions=["Using default wallet"],
        )
        response.add_data(data)
        assert len(response.data_sources) == 1
        assert len(response.assumptions) == 1

    def test_format_basic(self):
        """Test basic formatting."""
        response = GroundedResponse(message="Your balance is 100 τ")
        formatted = response.format()
        assert "100" in formatted

    def test_format_with_sources(self):
        """Test formatting with sources."""
        response = GroundedResponse(message="Balance: 100 τ")
        response.data_sources.append(SourceAttribution(source=DataSource.BITTENSOR_SDK))
        formatted = response.format(show_sources=True)
        assert "Sources:" in formatted or "Bittensor" in formatted

    def test_format_with_limitations(self):
        """Test formatting with limitations."""
        response = GroundedResponse(message="Balance: 100 τ")
        response.add_limitation("Using cached data")
        formatted = response.format()
        assert "Limitation" in formatted or "cached" in formatted


class TestCacheResult:
    """Test CacheResult from cache module."""

    def test_is_fresh(self):
        """Test fresh status detection."""
        result = CacheResult(value=100, status=CacheStatus.HIT_FRESH)
        assert result.is_fresh is True
        assert result.is_stale is False
        assert result.is_miss is False

    def test_is_stale(self):
        """Test stale status detection."""
        result = CacheResult(value=100, status=CacheStatus.HIT_STALE)
        assert result.is_fresh is False
        assert result.is_stale is True

    def test_is_miss(self):
        """Test miss status detection."""
        result = CacheResult(value=None, status=CacheStatus.MISS)
        assert result.is_miss is True


class TestBackoffManager:
    """Test BackoffManager."""

    def test_initial_no_delay(self):
        """Test no delay before first failure."""
        manager = BackoffManager()
        assert manager.get_delay("test_key") == 0
        assert manager.should_retry("test_key") is True

    def test_delay_after_failure(self):
        """Test delay after failure."""
        manager = BackoffManager(initial_delay=1.0)
        manager.record_failure("test_key")
        assert manager.get_delay("test_key") == 1.0

    def test_exponential_increase(self):
        """Test exponential backoff."""
        manager = BackoffManager(initial_delay=1.0, multiplier=2.0)
        manager.record_failure("test_key")
        manager.record_failure("test_key")
        assert manager.get_delay("test_key") == 2.0

        manager.record_failure("test_key")
        assert manager.get_delay("test_key") == 4.0

    def test_max_delay(self):
        """Test maximum delay cap."""
        manager = BackoffManager(initial_delay=1.0, max_delay=5.0, multiplier=10.0)
        for _ in range(10):
            manager.record_failure("test_key")
        assert manager.get_delay("test_key") == 5.0

    def test_success_resets(self):
        """Test that success resets backoff."""
        manager = BackoffManager()
        manager.record_failure("test_key")
        manager.record_failure("test_key")
        manager.record_success("test_key")
        assert manager.get_delay("test_key") == 0


class TestCacheEntry:
    """Test CacheEntry with metadata."""

    def test_get_status_fresh(self):
        """Test fresh status."""
        entry = CacheEntry(
            value=100,
            created_at=datetime.now().isoformat(),
            ttl=300,
        )
        assert entry.get_status() == CacheStatus.HIT_FRESH

    def test_get_status_stale(self):
        """Test stale status."""
        old_time = (datetime.now() - timedelta(seconds=400)).isoformat()
        entry = CacheEntry(
            value=100,
            created_at=old_time,
            ttl=300,
        )
        assert entry.get_status() == CacheStatus.HIT_STALE

    def test_age_seconds(self):
        """Test age calculation."""
        entry = CacheEntry(
            value=100,
            created_at=datetime.now().isoformat(),
            ttl=300,
        )
        assert entry.age_seconds() < 1  # Should be very recent
