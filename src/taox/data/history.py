"""Transaction history tracking and export for taox."""

import csv
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from rich import box
from rich.table import Table

from taox.ui.console import console, format_address, format_tao
from taox.ui.theme import TaoxColors

logger = logging.getLogger(__name__)

HISTORY_DIR = Path.home() / ".taox" / "history"
HISTORY_FILE = HISTORY_DIR / "transactions.json"


class TransactionType(str, Enum):
    """Types of transactions."""

    STAKE = "stake"
    UNSTAKE = "unstake"
    TRANSFER = "transfer"
    REGISTER = "register"
    CHILD_SET = "child_set"
    CHILD_REVOKE = "child_revoke"
    CHILD_TAKE = "child_take"


class TransactionStatus(str, Enum):
    """Status of a transaction."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Transaction:
    """A recorded transaction."""

    id: str
    type: TransactionType
    status: TransactionStatus
    timestamp: str
    amount: Optional[float] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    netuid: Optional[int] = None
    wallet_name: Optional[str] = None
    validator_name: Optional[str] = None
    command: Optional[str] = None
    error: Optional[str] = None
    tx_hash: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "type": self.type.value,
            "status": self.status.value,
            "timestamp": self.timestamp,
            "amount": self.amount,
            "from_address": self.from_address,
            "to_address": self.to_address,
            "netuid": self.netuid,
            "wallet_name": self.wallet_name,
            "validator_name": self.validator_name,
            "command": self.command,
            "error": self.error,
            "tx_hash": self.tx_hash,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Transaction":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            type=TransactionType(data["type"]),
            status=TransactionStatus(data["status"]),
            timestamp=data["timestamp"],
            amount=data.get("amount"),
            from_address=data.get("from_address"),
            to_address=data.get("to_address"),
            netuid=data.get("netuid"),
            wallet_name=data.get("wallet_name"),
            validator_name=data.get("validator_name"),
            command=data.get("command"),
            error=data.get("error"),
            tx_hash=data.get("tx_hash"),
            metadata=data.get("metadata", {}),
        )


class TransactionHistory:
    """Manages transaction history."""

    _instance: Optional["TransactionHistory"] = None

    def __new__(cls) -> "TransactionHistory":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._transactions: list[Transaction] = []
        self._load()

    def _ensure_dir(self) -> None:
        """Ensure history directory exists."""
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        """Load history from disk."""
        try:
            if HISTORY_FILE.exists():
                with open(HISTORY_FILE) as f:
                    data = json.load(f)
                    self._transactions = [Transaction.from_dict(t) for t in data]
                logger.debug(f"Loaded {len(self._transactions)} transactions from history")
        except Exception as e:
            logger.warning(f"Failed to load transaction history: {e}")
            self._transactions = []

    def _save(self) -> None:
        """Save history to disk."""
        try:
            self._ensure_dir()
            with open(HISTORY_FILE, "w") as f:
                json.dump([t.to_dict() for t in self._transactions], f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save transaction history: {e}")

    def _generate_id(self) -> str:
        """Generate a unique transaction ID."""
        import uuid

        return str(uuid.uuid4())[:8]

    def record(
        self,
        tx_type: TransactionType,
        status: TransactionStatus = TransactionStatus.PENDING,
        amount: Optional[float] = None,
        from_address: Optional[str] = None,
        to_address: Optional[str] = None,
        netuid: Optional[int] = None,
        wallet_name: Optional[str] = None,
        validator_name: Optional[str] = None,
        command: Optional[str] = None,
        error: Optional[str] = None,
        tx_hash: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Transaction:
        """Record a new transaction.

        Args:
            tx_type: Type of transaction
            status: Transaction status
            amount: Amount in TAO
            from_address: Source address
            to_address: Destination address
            netuid: Subnet ID
            wallet_name: Wallet name used
            validator_name: Validator name
            command: btcli command executed
            error: Error message if failed
            tx_hash: Transaction hash if available
            metadata: Additional metadata

        Returns:
            The recorded Transaction
        """
        tx = Transaction(
            id=self._generate_id(),
            type=tx_type,
            status=status,
            timestamp=datetime.now().isoformat(),
            amount=amount,
            from_address=from_address,
            to_address=to_address,
            netuid=netuid,
            wallet_name=wallet_name,
            validator_name=validator_name,
            command=command,
            error=error,
            tx_hash=tx_hash,
            metadata=metadata or {},
        )
        self._transactions.append(tx)
        self._save()
        logger.info(f"Recorded transaction {tx.id}: {tx_type.value} - {status.value}")
        return tx

    def update_status(
        self,
        tx_id: str,
        status: TransactionStatus,
        error: Optional[str] = None,
        tx_hash: Optional[str] = None,
    ) -> bool:
        """Update a transaction's status.

        Args:
            tx_id: Transaction ID
            status: New status
            error: Error message if failed
            tx_hash: Transaction hash if available

        Returns:
            True if updated, False if not found
        """
        for tx in self._transactions:
            if tx.id == tx_id:
                tx.status = status
                if error:
                    tx.error = error
                if tx_hash:
                    tx.tx_hash = tx_hash
                self._save()
                return True
        return False

    def get_all(
        self,
        tx_type: Optional[TransactionType] = None,
        status: Optional[TransactionStatus] = None,
        limit: int = 100,
    ) -> list[Transaction]:
        """Get transactions with optional filtering.

        Args:
            tx_type: Filter by type
            status: Filter by status
            limit: Maximum number to return

        Returns:
            List of transactions (newest first)
        """
        transactions = self._transactions.copy()

        if tx_type:
            transactions = [t for t in transactions if t.type == tx_type]
        if status:
            transactions = [t for t in transactions if t.status == status]

        # Sort by timestamp descending
        transactions.sort(key=lambda t: t.timestamp, reverse=True)
        return transactions[:limit]

    def get_by_id(self, tx_id: str) -> Optional[Transaction]:
        """Get a transaction by ID."""
        for tx in self._transactions:
            if tx.id == tx_id:
                return tx
        return None

    def clear(self) -> None:
        """Clear all transaction history."""
        self._transactions = []
        if HISTORY_FILE.exists():
            HISTORY_FILE.unlink()

    def export_json(self, filepath: Path, **filters) -> int:
        """Export transactions to JSON file.

        Args:
            filepath: Output file path
            **filters: Filters to pass to get_all()

        Returns:
            Number of transactions exported
        """
        transactions = self.get_all(**filters)
        with open(filepath, "w") as f:
            json.dump([t.to_dict() for t in transactions], f, indent=2)
        return len(transactions)

    def export_csv(self, filepath: Path, **filters) -> int:
        """Export transactions to CSV file.

        Args:
            filepath: Output file path
            **filters: Filters to pass to get_all()

        Returns:
            Number of transactions exported
        """
        transactions = self.get_all(**filters)
        if not transactions:
            return 0

        fieldnames = [
            "id",
            "type",
            "status",
            "timestamp",
            "amount",
            "from_address",
            "to_address",
            "netuid",
            "wallet_name",
            "validator_name",
            "command",
            "error",
            "tx_hash",
        ]

        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for tx in transactions:
                row = tx.to_dict()
                del row["metadata"]  # Skip metadata in CSV
                writer.writerow(row)

        return len(transactions)


def show_history(
    limit: int = 20,
    tx_type: Optional[TransactionType] = None,
    status: Optional[TransactionStatus] = None,
) -> None:
    """Display transaction history in a table.

    Args:
        limit: Maximum transactions to show
        tx_type: Filter by type
        status: Filter by status
    """
    history = TransactionHistory()
    transactions = history.get_all(tx_type=tx_type, status=status, limit=limit)

    if not transactions:
        console.print("[muted]No transactions found[/muted]")
        return

    table = Table(
        title="[primary]Transaction History[/primary]",
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
    )
    table.add_column("ID", style="dim", width=8)
    table.add_column("Time", style="muted")
    table.add_column("Type", style="info")
    table.add_column("Amount", justify="right", style="tao")
    table.add_column("To/Validator", style="address")
    table.add_column("Status")

    for tx in transactions:
        # Format timestamp
        try:
            dt = datetime.fromisoformat(tx.timestamp)
            time_str = dt.strftime("%m/%d %H:%M")
        except Exception:
            time_str = tx.timestamp[:16]

        # Format amount
        amount_str = format_tao(tx.amount) if tx.amount else "-"

        # Format destination
        dest = tx.validator_name or (format_address(tx.to_address) if tx.to_address else "-")

        # Format status with color
        status_colors = {
            TransactionStatus.SUCCESS: "success",
            TransactionStatus.FAILED: "error",
            TransactionStatus.PENDING: "warning",
            TransactionStatus.CANCELLED: "muted",
        }
        status_color = status_colors.get(tx.status, "muted")
        status_str = f"[{status_color}]{tx.status.value}[/{status_color}]"

        table.add_row(
            tx.id,
            time_str,
            tx.type.value,
            amount_str,
            dest[:20] if dest != "-" else dest,
            status_str,
        )

    console.print(table)
    console.print(
        f"\n[muted]Showing {len(transactions)} of {len(history._transactions)} total transactions[/muted]"
    )


# Global history instance
transaction_history = TransactionHistory()
