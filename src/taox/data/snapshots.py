"""Portfolio snapshot storage for taox.

Stores daily snapshots of portfolio state to enable:
- 7d/30d delta comparisons
- Historical tracking
- Performance analysis
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


@dataclass
class PositionSnapshot:
    """Snapshot of a single stake position."""

    netuid: int
    hotkey: str
    validator_name: Optional[str]
    stake: float  # TAO value
    alpha_balance: float = 0.0


@dataclass
class PortfolioSnapshot:
    """Complete portfolio snapshot at a point in time."""

    timestamp: str  # ISO format
    coldkey: str
    free_balance: float
    total_staked: float
    total_value: float  # free + staked
    tao_price_usd: float
    usd_value: float
    positions: list[PositionSnapshot] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "PortfolioSnapshot":
        """Create snapshot from dict."""
        positions = [PositionSnapshot(**p) for p in data.get("positions", [])]
        return cls(
            timestamp=data["timestamp"],
            coldkey=data["coldkey"],
            free_balance=data["free_balance"],
            total_staked=data["total_staked"],
            total_value=data["total_value"],
            tao_price_usd=data["tao_price_usd"],
            usd_value=data["usd_value"],
            positions=positions,
        )

    def to_dict(self) -> dict:
        """Convert to dict for storage."""
        return {
            "timestamp": self.timestamp,
            "coldkey": self.coldkey,
            "free_balance": self.free_balance,
            "total_staked": self.total_staked,
            "total_value": self.total_value,
            "tao_price_usd": self.tao_price_usd,
            "usd_value": self.usd_value,
            "positions": [asdict(p) for p in self.positions],
        }


@dataclass
class PositionDelta:
    """Change in a position between two snapshots."""

    netuid: int
    hotkey: str
    validator_name: Optional[str]
    stake_before: float
    stake_after: float
    stake_change: float
    stake_change_percent: float


@dataclass
class PortfolioDelta:
    """Change between two portfolio snapshots."""

    days: int
    from_timestamp: str
    to_timestamp: str
    free_balance_change: float
    total_staked_change: float
    total_value_change: float
    total_value_change_percent: float
    usd_value_change: float
    tao_price_change_percent: float
    position_deltas: list[PositionDelta] = field(default_factory=list)
    best_performer: Optional[PositionDelta] = None
    worst_performer: Optional[PositionDelta] = None
    estimated_rewards: float = 0.0


class SnapshotStore:
    """Local storage for portfolio snapshots."""

    def __init__(self, storage_path: Optional[Path] = None):
        """Initialize snapshot store.

        Args:
            storage_path: Path to storage directory (default: ~/.taox/snapshots)
        """
        if storage_path is None:
            storage_path = Path.home() / ".taox" / "snapshots"

        self.storage_path = storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _get_snapshot_file(self, coldkey: str) -> Path:
        """Get snapshot file path for a coldkey."""
        # Use first 12 chars of coldkey as filename
        safe_key = coldkey[:12].replace("/", "_")
        return self.storage_path / f"portfolio_{safe_key}.json"

    def _load_snapshots(self, coldkey: str) -> list[PortfolioSnapshot]:
        """Load all snapshots for a coldkey."""
        filepath = self._get_snapshot_file(coldkey)
        if not filepath.exists():
            return []

        try:
            with open(filepath) as f:
                data = json.load(f)
            return [PortfolioSnapshot.from_dict(s) for s in data.get("snapshots", [])]
        except (json.JSONDecodeError, KeyError, TypeError):
            return []

    def _save_snapshots(self, coldkey: str, snapshots: list[PortfolioSnapshot]) -> None:
        """Save snapshots for a coldkey."""
        filepath = self._get_snapshot_file(coldkey)

        # Keep only last 90 days of snapshots
        cutoff = datetime.now() - timedelta(days=90)
        filtered = [s for s in snapshots if datetime.fromisoformat(s.timestamp) > cutoff]

        data = {
            "coldkey": coldkey,
            "last_updated": datetime.now().isoformat(),
            "snapshots": [s.to_dict() for s in filtered],
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    def save_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        """Save a new portfolio snapshot.

        Only saves one snapshot per day (overwrites if same day).
        """
        snapshots = self._load_snapshots(snapshot.coldkey)

        # Get today's date
        today = datetime.now().date()

        # Remove any snapshot from today
        snapshots = [s for s in snapshots if datetime.fromisoformat(s.timestamp).date() != today]

        # Add new snapshot
        snapshots.append(snapshot)

        # Sort by timestamp
        snapshots.sort(key=lambda s: s.timestamp)

        self._save_snapshots(snapshot.coldkey, snapshots)

    def get_latest_snapshot(self, coldkey: str) -> Optional[PortfolioSnapshot]:
        """Get the most recent snapshot for a coldkey."""
        snapshots = self._load_snapshots(coldkey)
        if not snapshots:
            return None
        return snapshots[-1]

    def get_snapshot_at(
        self,
        coldkey: str,
        days_ago: int,
    ) -> Optional[PortfolioSnapshot]:
        """Get snapshot closest to N days ago.

        Args:
            coldkey: Wallet coldkey
            days_ago: Number of days ago to look for

        Returns:
            Snapshot closest to that date, or None
        """
        snapshots = self._load_snapshots(coldkey)
        if not snapshots:
            return None

        target_date = datetime.now() - timedelta(days=days_ago)

        # Find closest snapshot
        closest = None
        min_diff = float("inf")

        for snap in snapshots:
            snap_date = datetime.fromisoformat(snap.timestamp)
            diff = abs((snap_date - target_date).total_seconds())
            if diff < min_diff:
                min_diff = diff
                closest = snap

        return closest

    def get_snapshots_in_range(
        self,
        coldkey: str,
        days: int,
    ) -> list[PortfolioSnapshot]:
        """Get all snapshots within the last N days.

        Args:
            coldkey: Wallet coldkey
            days: Number of days to look back

        Returns:
            List of snapshots in chronological order
        """
        snapshots = self._load_snapshots(coldkey)
        cutoff = datetime.now() - timedelta(days=days)

        return [s for s in snapshots if datetime.fromisoformat(s.timestamp) > cutoff]

    def compute_delta(
        self,
        coldkey: str,
        days: int,
        current: PortfolioSnapshot,
    ) -> Optional[PortfolioDelta]:
        """Compute portfolio change over N days.

        Args:
            coldkey: Wallet coldkey
            days: Number of days to compare
            current: Current portfolio snapshot

        Returns:
            PortfolioDelta or None if no historical data
        """
        past = self.get_snapshot_at(coldkey, days)
        if not past:
            return None

        # Compute overall delta
        free_change = current.free_balance - past.free_balance
        staked_change = current.total_staked - past.total_staked
        value_change = current.total_value - past.total_value
        value_change_pct = (value_change / past.total_value * 100) if past.total_value > 0 else 0

        usd_change = current.usd_value - past.usd_value
        price_change_pct = (
            (current.tao_price_usd - past.tao_price_usd) / past.tao_price_usd * 100
            if past.tao_price_usd > 0
            else 0
        )

        # Compute position deltas
        past_positions = {(p.netuid, p.hotkey): p for p in past.positions}
        current_positions = {(p.netuid, p.hotkey): p for p in current.positions}

        position_deltas = []
        all_keys = set(past_positions.keys()) | set(current_positions.keys())

        for key in all_keys:
            past_pos = past_positions.get(key)
            curr_pos = current_positions.get(key)

            stake_before = past_pos.stake if past_pos else 0
            stake_after = curr_pos.stake if curr_pos else 0
            stake_change = stake_after - stake_before
            stake_change_pct = (stake_change / stake_before * 100) if stake_before > 0 else 0

            netuid, hotkey = key
            validator_name = (
                curr_pos.validator_name
                if curr_pos
                else past_pos.validator_name if past_pos else None
            )

            position_deltas.append(
                PositionDelta(
                    netuid=netuid,
                    hotkey=hotkey,
                    validator_name=validator_name,
                    stake_before=stake_before,
                    stake_after=stake_after,
                    stake_change=stake_change,
                    stake_change_percent=stake_change_pct,
                )
            )

        # Sort by stake change
        position_deltas.sort(key=lambda p: p.stake_change, reverse=True)

        # Find best and worst performers (only for existing positions)
        active_deltas = [p for p in position_deltas if p.stake_before > 0 and p.stake_after > 0]
        best_performer = active_deltas[0] if active_deltas else None
        worst_performer = active_deltas[-1] if active_deltas else None

        # Estimate rewards (staked change that wasn't from new deposits)
        # This is a rough estimate: rewards = staked_change - new_deposits
        # We approximate by looking at positions that existed before
        estimated_rewards = sum(
            p.stake_change for p in position_deltas if p.stake_before > 0 and p.stake_change > 0
        )

        return PortfolioDelta(
            days=days,
            from_timestamp=past.timestamp,
            to_timestamp=current.timestamp,
            free_balance_change=free_change,
            total_staked_change=staked_change,
            total_value_change=value_change,
            total_value_change_percent=value_change_pct,
            usd_value_change=usd_change,
            tao_price_change_percent=price_change_pct,
            position_deltas=position_deltas,
            best_performer=best_performer,
            worst_performer=worst_performer,
            estimated_rewards=estimated_rewards,
        )

    def get_history(
        self,
        coldkey: str,
        days: int = 30,
    ) -> list[dict]:
        """Get simplified history for display.

        Args:
            coldkey: Wallet coldkey
            days: Number of days to show

        Returns:
            List of dicts with date, total_value, usd_value
        """
        snapshots = self.get_snapshots_in_range(coldkey, days)
        return [
            {
                "date": datetime.fromisoformat(s.timestamp).strftime("%Y-%m-%d"),
                "total_tao": s.total_value,
                "free_balance": s.free_balance,
                "total_staked": s.total_staked,
                "tao_price": s.tao_price_usd,
                "usd_value": s.usd_value,
            }
            for s in snapshots
        ]


# Global store instance
_snapshot_store: Optional[SnapshotStore] = None


def get_snapshot_store() -> SnapshotStore:
    """Get or create the global snapshot store."""
    global _snapshot_store
    if _snapshot_store is None:
        _snapshot_store = SnapshotStore()
    return _snapshot_store
