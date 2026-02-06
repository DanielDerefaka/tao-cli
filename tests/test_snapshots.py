"""Tests for portfolio snapshots."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from taox.data.snapshots import (
    PortfolioSnapshot,
    PositionSnapshot,
    SnapshotStore,
    get_snapshot_store,
)


@pytest.fixture
def temp_storage():
    """Create a temporary storage directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def snapshot_store(temp_storage):
    """Create a snapshot store with temp storage."""
    return SnapshotStore(storage_path=temp_storage)


@pytest.fixture
def sample_snapshot():
    """Create a sample snapshot."""
    return PortfolioSnapshot(
        timestamp=datetime.now().isoformat(),
        coldkey="5Sample123456789",
        free_balance=100.0,
        total_staked=500.0,
        total_value=600.0,
        tao_price_usd=450.0,
        usd_value=270000.0,
        positions=[
            PositionSnapshot(
                netuid=1,
                hotkey="5Val111111",
                validator_name="Taostats",
                stake=300.0,
                alpha_balance=280.5,
            ),
            PositionSnapshot(
                netuid=18,
                hotkey="5Val222222",
                validator_name="OpenTensor",
                stake=200.0,
                alpha_balance=195.2,
            ),
        ],
    )


class TestPositionSnapshot:
    """Tests for PositionSnapshot dataclass."""

    def test_create_position_snapshot(self):
        """Test creating a position snapshot."""
        pos = PositionSnapshot(
            netuid=1,
            hotkey="5AAA111",
            validator_name="Test Validator",
            stake=100.0,
            alpha_balance=95.5,
        )

        assert pos.netuid == 1
        assert pos.hotkey == "5AAA111"
        assert pos.validator_name == "Test Validator"
        assert pos.stake == 100.0
        assert pos.alpha_balance == 95.5


class TestPortfolioSnapshot:
    """Tests for PortfolioSnapshot dataclass."""

    def test_create_snapshot(self, sample_snapshot):
        """Test creating a portfolio snapshot."""
        assert sample_snapshot.coldkey == "5Sample123456789"
        assert sample_snapshot.free_balance == 100.0
        assert sample_snapshot.total_staked == 500.0
        assert len(sample_snapshot.positions) == 2

    def test_to_dict(self, sample_snapshot):
        """Test converting snapshot to dict."""
        data = sample_snapshot.to_dict()

        assert data["coldkey"] == "5Sample123456789"
        assert data["free_balance"] == 100.0
        assert len(data["positions"]) == 2
        assert data["positions"][0]["netuid"] == 1

    def test_from_dict(self, sample_snapshot):
        """Test creating snapshot from dict."""
        data = sample_snapshot.to_dict()
        restored = PortfolioSnapshot.from_dict(data)

        assert restored.coldkey == sample_snapshot.coldkey
        assert restored.free_balance == sample_snapshot.free_balance
        assert len(restored.positions) == len(sample_snapshot.positions)


class TestSnapshotStore:
    """Tests for SnapshotStore."""

    def test_save_and_load_snapshot(self, snapshot_store, sample_snapshot):
        """Test saving and loading a snapshot."""
        snapshot_store.save_snapshot(sample_snapshot)

        loaded = snapshot_store.get_latest_snapshot(sample_snapshot.coldkey)

        assert loaded is not None
        assert loaded.coldkey == sample_snapshot.coldkey
        assert loaded.free_balance == sample_snapshot.free_balance

    def test_get_latest_snapshot_no_data(self, snapshot_store):
        """Test getting latest snapshot when none exists."""
        result = snapshot_store.get_latest_snapshot("5NoData123456789")
        assert result is None

    def test_overwrites_same_day_snapshot(self, snapshot_store, sample_snapshot):
        """Test that same-day snapshots are overwritten."""
        # Save first snapshot
        snapshot_store.save_snapshot(sample_snapshot)

        # Modify and save again
        sample_snapshot.free_balance = 200.0
        snapshot_store.save_snapshot(sample_snapshot)

        # Should only have one snapshot
        snapshots = snapshot_store.get_snapshots_in_range(sample_snapshot.coldkey, 7)
        assert len(snapshots) == 1
        assert snapshots[0].free_balance == 200.0

    def test_preserves_different_day_snapshots(self, snapshot_store):
        """Test that different day snapshots are preserved."""
        coldkey = "5MultiDay123456789"

        # Create snapshots for different days (skip today to avoid overwrite)
        # Note: save_snapshot removes "today's" snapshot each time
        # So we save oldest first, then newest last
        for days_ago in [5, 4, 3, 2, 1]:
            timestamp = (datetime.now() - timedelta(days=days_ago)).isoformat()
            snapshot = PortfolioSnapshot(
                timestamp=timestamp,
                coldkey=coldkey,
                free_balance=100.0 + days_ago * 10,
                total_staked=500.0,
                total_value=600.0 + days_ago * 10,
                tao_price_usd=450.0,
                usd_value=270000.0,
            )
            snapshot_store.save_snapshot(snapshot)

        # Finally save today's snapshot
        today_snapshot = PortfolioSnapshot(
            timestamp=datetime.now().isoformat(),
            coldkey=coldkey,
            free_balance=100.0,
            total_staked=500.0,
            total_value=600.0,
            tao_price_usd=450.0,
            usd_value=270000.0,
        )
        snapshot_store.save_snapshot(today_snapshot)

        snapshots = snapshot_store.get_snapshots_in_range(coldkey, 7)
        # Should have 6 snapshots (today + 5 past days)
        assert len(snapshots) == 6

    def test_get_snapshot_at(self, snapshot_store):
        """Test getting snapshot at specific days ago."""
        coldkey = "5Historical123456789"

        # Create snapshot 7 days ago
        old_timestamp = (datetime.now() - timedelta(days=7)).isoformat()
        old_snapshot = PortfolioSnapshot(
            timestamp=old_timestamp,
            coldkey=coldkey,
            free_balance=50.0,
            total_staked=400.0,
            total_value=450.0,
            tao_price_usd=400.0,
            usd_value=180000.0,
        )
        snapshot_store.save_snapshot(old_snapshot)

        # Get snapshot at 7 days ago
        result = snapshot_store.get_snapshot_at(coldkey, 7)
        assert result is not None
        assert result.free_balance == 50.0

    def test_get_snapshots_in_range(self, snapshot_store):
        """Test getting snapshots within a range."""
        coldkey = "5Range123456789"

        # Create snapshots: 1, 5, 10, and 20 days ago
        for days_ago in [1, 5, 10, 20]:
            timestamp = (datetime.now() - timedelta(days=days_ago)).isoformat()
            snapshot = PortfolioSnapshot(
                timestamp=timestamp,
                coldkey=coldkey,
                free_balance=100.0,
                total_staked=500.0,
                total_value=600.0,
                tao_price_usd=450.0,
                usd_value=270000.0,
            )
            snapshot_store.save_snapshot(snapshot)

        # Get last 7 days
        range_7d = snapshot_store.get_snapshots_in_range(coldkey, 7)
        assert len(range_7d) == 2  # 1 and 5 days ago

        # Get last 30 days
        range_30d = snapshot_store.get_snapshots_in_range(coldkey, 30)
        assert len(range_30d) == 4


class TestComputeDelta:
    """Tests for delta computation."""

    def test_compute_delta_basic(self, snapshot_store):
        """Test basic delta computation."""
        coldkey = "5Delta123456789"

        # Create old snapshot (7 days ago)
        old_timestamp = (datetime.now() - timedelta(days=7)).isoformat()
        old_snapshot = PortfolioSnapshot(
            timestamp=old_timestamp,
            coldkey=coldkey,
            free_balance=100.0,
            total_staked=400.0,
            total_value=500.0,
            tao_price_usd=400.0,
            usd_value=200000.0,
            positions=[
                PositionSnapshot(netuid=1, hotkey="5Val1", validator_name="Val1", stake=400.0),
            ],
        )
        snapshot_store.save_snapshot(old_snapshot)

        # Create current snapshot
        current = PortfolioSnapshot(
            timestamp=datetime.now().isoformat(),
            coldkey=coldkey,
            free_balance=150.0,
            total_staked=450.0,
            total_value=600.0,
            tao_price_usd=450.0,
            usd_value=270000.0,
            positions=[
                PositionSnapshot(netuid=1, hotkey="5Val1", validator_name="Val1", stake=450.0),
            ],
        )

        delta = snapshot_store.compute_delta(coldkey, 7, current)

        assert delta is not None
        assert delta.days == 7
        assert delta.total_value_change == 100.0  # 600 - 500
        assert delta.free_balance_change == 50.0  # 150 - 100
        assert delta.total_staked_change == 50.0  # 450 - 400

    def test_compute_delta_no_history(self, snapshot_store):
        """Test delta when no historical data exists."""
        current = PortfolioSnapshot(
            timestamp=datetime.now().isoformat(),
            coldkey="5NoHistory123456789",
            free_balance=100.0,
            total_staked=400.0,
            total_value=500.0,
            tao_price_usd=400.0,
            usd_value=200000.0,
        )

        delta = snapshot_store.compute_delta("5NoHistory123456789", 7, current)
        assert delta is None

    def test_compute_delta_with_position_changes(self, snapshot_store):
        """Test delta with position changes."""
        coldkey = "5PosChange123456789"

        # Old snapshot with position
        old_timestamp = (datetime.now() - timedelta(days=7)).isoformat()
        old_snapshot = PortfolioSnapshot(
            timestamp=old_timestamp,
            coldkey=coldkey,
            free_balance=100.0,
            total_staked=300.0,
            total_value=400.0,
            tao_price_usd=400.0,
            usd_value=160000.0,
            positions=[
                PositionSnapshot(netuid=1, hotkey="5Val1", validator_name="Good Val", stake=200.0),
                PositionSnapshot(netuid=2, hotkey="5Val2", validator_name="Bad Val", stake=100.0),
            ],
        )
        snapshot_store.save_snapshot(old_snapshot)

        # Current: position 1 grew, position 2 shrank
        current = PortfolioSnapshot(
            timestamp=datetime.now().isoformat(),
            coldkey=coldkey,
            free_balance=100.0,
            total_staked=350.0,
            total_value=450.0,
            tao_price_usd=450.0,
            usd_value=202500.0,
            positions=[
                PositionSnapshot(netuid=1, hotkey="5Val1", validator_name="Good Val", stake=280.0),
                PositionSnapshot(netuid=2, hotkey="5Val2", validator_name="Bad Val", stake=70.0),
            ],
        )

        delta = snapshot_store.compute_delta(coldkey, 7, current)

        assert delta is not None
        assert delta.best_performer is not None
        assert delta.best_performer.netuid == 1
        assert delta.best_performer.stake_change == 80.0  # 280 - 200

        assert delta.worst_performer is not None
        assert delta.worst_performer.netuid == 2
        assert delta.worst_performer.stake_change == -30.0  # 70 - 100


class TestGetHistory:
    """Tests for history retrieval."""

    def test_get_history(self, snapshot_store):
        """Test getting simplified history."""
        coldkey = "5History123456789"

        # Create several snapshots - save oldest first to avoid overwrites
        for days_ago in [4, 3, 2, 1]:
            timestamp = (datetime.now() - timedelta(days=days_ago)).isoformat()
            snapshot = PortfolioSnapshot(
                timestamp=timestamp,
                coldkey=coldkey,
                free_balance=100.0 + days_ago,
                total_staked=500.0,
                total_value=600.0 + days_ago,
                tao_price_usd=450.0 - days_ago,
                usd_value=270000.0,
            )
            snapshot_store.save_snapshot(snapshot)

        # Save today's last
        today_snapshot = PortfolioSnapshot(
            timestamp=datetime.now().isoformat(),
            coldkey=coldkey,
            free_balance=100.0,
            total_staked=500.0,
            total_value=600.0,
            tao_price_usd=450.0,
            usd_value=270000.0,
        )
        snapshot_store.save_snapshot(today_snapshot)

        history = snapshot_store.get_history(coldkey, 30)

        assert len(history) == 5
        # History should have date, total_tao, etc.
        assert "date" in history[0]
        assert "total_tao" in history[0]
        assert "tao_price" in history[0]


class TestGlobalStore:
    """Tests for global store instance."""

    def test_get_snapshot_store(self):
        """Test getting the global snapshot store."""
        store = get_snapshot_store()
        assert store is not None
        assert isinstance(store, SnapshotStore)

    def test_get_snapshot_store_singleton(self):
        """Test that store is a singleton."""
        store1 = get_snapshot_store()
        store2 = get_snapshot_store()
        assert store1 is store2
