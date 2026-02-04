"""Tests for transaction history."""

import pytest
import json
from pathlib import Path
from datetime import datetime

from taox.data.history import (
    Transaction,
    TransactionHistory,
    TransactionType,
    TransactionStatus,
)


class TestTransaction:
    """Tests for Transaction dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        tx = Transaction(
            id="test123",
            type=TransactionType.STAKE,
            status=TransactionStatus.SUCCESS,
            timestamp="2024-01-01T12:00:00",
            amount=100.0,
            to_address="5xxx...",
            netuid=1,
            validator_name="Taostats",
        )

        data = tx.to_dict()
        assert data["id"] == "test123"
        assert data["type"] == "stake"
        assert data["status"] == "success"
        assert data["amount"] == 100.0
        assert data["netuid"] == 1

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "id": "test456",
            "type": "transfer",
            "status": "pending",
            "timestamp": "2024-01-01T12:00:00",
            "amount": 50.0,
            "to_address": "5yyy...",
        }

        tx = Transaction.from_dict(data)
        assert tx.id == "test456"
        assert tx.type == TransactionType.TRANSFER
        assert tx.status == TransactionStatus.PENDING
        assert tx.amount == 50.0


class TestTransactionHistory:
    """Tests for TransactionHistory."""

    @pytest.fixture
    def history(self, tmp_path, monkeypatch):
        """Create a TransactionHistory with temp storage."""
        history_dir = tmp_path / ".taox" / "history"
        history_dir.mkdir(parents=True)
        history_file = history_dir / "transactions.json"

        monkeypatch.setattr("taox.data.history.HISTORY_DIR", history_dir)
        monkeypatch.setattr("taox.data.history.HISTORY_FILE", history_file)

        # Clear singleton
        TransactionHistory._instance = None

        return TransactionHistory()

    def test_record_transaction(self, history):
        """Test recording a transaction."""
        tx = history.record(
            tx_type=TransactionType.STAKE,
            status=TransactionStatus.SUCCESS,
            amount=100.0,
            netuid=1,
            validator_name="Taostats",
        )

        assert tx.id is not None
        assert tx.type == TransactionType.STAKE
        assert tx.amount == 100.0

    def test_get_all(self, history):
        """Test getting all transactions."""
        # Record multiple transactions
        history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.SUCCESS)
        history.record(tx_type=TransactionType.TRANSFER, status=TransactionStatus.FAILED)
        history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.PENDING)

        all_tx = history.get_all()
        assert len(all_tx) == 3

    def test_get_all_filtered_by_type(self, history):
        """Test filtering by transaction type."""
        history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.SUCCESS)
        history.record(tx_type=TransactionType.TRANSFER, status=TransactionStatus.SUCCESS)
        history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.SUCCESS)

        stake_tx = history.get_all(tx_type=TransactionType.STAKE)
        assert len(stake_tx) == 2

    def test_get_all_filtered_by_status(self, history):
        """Test filtering by status."""
        history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.SUCCESS)
        history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.FAILED)
        history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.SUCCESS)

        success_tx = history.get_all(status=TransactionStatus.SUCCESS)
        assert len(success_tx) == 2

    def test_get_by_id(self, history):
        """Test getting transaction by ID."""
        tx = history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.SUCCESS)

        found = history.get_by_id(tx.id)
        assert found is not None
        assert found.id == tx.id

    def test_get_by_id_not_found(self, history):
        """Test getting nonexistent transaction."""
        found = history.get_by_id("nonexistent")
        assert found is None

    def test_update_status(self, history):
        """Test updating transaction status."""
        tx = history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.PENDING)

        success = history.update_status(
            tx.id,
            TransactionStatus.SUCCESS,
            tx_hash="0xabc123",
        )

        assert success is True

        updated = history.get_by_id(tx.id)
        assert updated.status == TransactionStatus.SUCCESS
        assert updated.tx_hash == "0xabc123"

    def test_update_status_with_error(self, history):
        """Test updating status to failed with error."""
        tx = history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.PENDING)

        history.update_status(
            tx.id,
            TransactionStatus.FAILED,
            error="Insufficient balance",
        )

        updated = history.get_by_id(tx.id)
        assert updated.status == TransactionStatus.FAILED
        assert updated.error == "Insufficient balance"

    def test_clear(self, history):
        """Test clearing history."""
        history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.SUCCESS)
        history.record(tx_type=TransactionType.TRANSFER, status=TransactionStatus.SUCCESS)

        history.clear()

        assert len(history.get_all()) == 0

    def test_export_json(self, history, tmp_path):
        """Test exporting to JSON."""
        history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.SUCCESS, amount=100.0)
        history.record(tx_type=TransactionType.TRANSFER, status=TransactionStatus.SUCCESS, amount=50.0)

        export_path = tmp_path / "export.json"
        count = history.export_json(export_path)

        assert count == 2
        assert export_path.exists()

        with open(export_path) as f:
            data = json.load(f)
            assert len(data) == 2

    def test_export_csv(self, history, tmp_path):
        """Test exporting to CSV."""
        history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.SUCCESS, amount=100.0)
        history.record(tx_type=TransactionType.TRANSFER, status=TransactionStatus.SUCCESS, amount=50.0)

        export_path = tmp_path / "export.csv"
        count = history.export_csv(export_path)

        assert count == 2
        assert export_path.exists()

        content = export_path.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 3  # Header + 2 rows

    def test_persistence(self, tmp_path, monkeypatch):
        """Test history persists across instances."""
        history_dir = tmp_path / ".taox" / "history"
        history_dir.mkdir(parents=True)
        history_file = history_dir / "transactions.json"

        monkeypatch.setattr("taox.data.history.HISTORY_DIR", history_dir)
        monkeypatch.setattr("taox.data.history.HISTORY_FILE", history_file)

        # Create first instance and record
        TransactionHistory._instance = None
        history1 = TransactionHistory()
        history1.record(tx_type=TransactionType.STAKE, status=TransactionStatus.SUCCESS)

        # Clear singleton and create new instance
        TransactionHistory._instance = None
        history2 = TransactionHistory()

        assert len(history2.get_all()) == 1

    def test_limit(self, history):
        """Test limiting results."""
        for i in range(10):
            history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.SUCCESS)

        limited = history.get_all(limit=5)
        assert len(limited) == 5

    def test_ordering(self, history):
        """Test results are ordered by timestamp descending."""
        tx1 = history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.SUCCESS)
        tx2 = history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.SUCCESS)
        tx3 = history.record(tx_type=TransactionType.STAKE, status=TransactionStatus.SUCCESS)

        all_tx = history.get_all()

        # Newest first
        assert all_tx[0].id == tx3.id
        assert all_tx[2].id == tx1.id
