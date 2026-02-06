"""Tests for transaction pipeline.

Tests cover:
- Plan building
- Dry-run behavior
- Verification status mapping
- JSON output
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from taox.commands.tx_pipeline import (
    TransactionPipeline,
    TxPlan,
    TxResult,
    TxPhase,
    VerificationLevel,
    PlanItem,
    build_stake_plan,
    build_transfer_plan,
    build_register_plan,
)


class TestTxPlan:
    """Tests for TxPlan building."""

    def test_stake_plan_basic(self):
        """Test building a basic stake plan."""
        plan = build_stake_plan(
            amount=10.0,
            validator_name="Taostats",
            validator_hotkey="5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v",
            netuid=1,
            wallet="default",
            hotkey="default",
        )

        assert plan.title == "Stake Plan"
        assert plan.command_name == "Stake"
        assert len(plan.items) == 6
        assert plan.network == "finney"
        assert plan.requires_password is True
        assert "High-value transaction" in plan.warnings[0]

    def test_stake_plan_no_warning_small_amount(self):
        """Test that small amounts don't trigger warning."""
        plan = build_stake_plan(
            amount=1.0,
            validator_name="Taostats",
            validator_hotkey="5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v",
            netuid=1,
            wallet="default",
            hotkey="default",
        )

        assert len(plan.warnings) == 0

    def test_transfer_plan_basic(self):
        """Test building a transfer plan."""
        plan = build_transfer_plan(
            amount=5.0,
            destination="5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
            wallet="default",
        )

        assert plan.title == "Transfer Plan"
        assert plan.command_name == "Transfer"
        assert "irreversible" in plan.warnings[0].lower() or "irreversible" in plan.warnings[1].lower()

    def test_register_plan_basic(self):
        """Test building a register plan."""
        plan = build_register_plan(
            netuid=24,
            wallet="default",
            hotkey="default",
            burn_cost=1.5,
        )

        assert plan.title == "Registration Plan"
        assert plan.command_name == "Register"
        assert "burn" in plan.warnings[0].lower()

    def test_plan_btcli_args(self):
        """Test that btcli args are correctly set."""
        plan = build_stake_plan(
            amount=10.0,
            validator_name="Test",
            validator_hotkey="5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v",
            netuid=1,
            wallet="mywall",
            hotkey="myhot",
        )

        assert "stake" in plan.btcli_args
        assert "add" in plan.btcli_args
        assert "--amount" in plan.btcli_args
        assert "10.0" in plan.btcli_args
        assert "--wallet-name" in plan.btcli_args
        assert "mywall" in plan.btcli_args


class TestTxResult:
    """Tests for TxResult."""

    def test_result_success(self):
        """Test successful result creation."""
        result = TxResult(
            success=True,
            phase=TxPhase.FINALIZED,
            message="Transaction complete",
            tx_hash="0x1234567890abcdef",
        )

        assert result.success is True
        assert result.phase == TxPhase.FINALIZED
        assert result.tx_hash is not None

    def test_result_failure(self):
        """Test failed result creation."""
        result = TxResult(
            success=False,
            phase=TxPhase.FAILED,
            message="Transaction failed",
            error="Insufficient balance",
        )

        assert result.success is False
        assert result.phase == TxPhase.FAILED
        assert result.error is not None


class TestTransactionPipeline:
    """Tests for TransactionPipeline."""

    @pytest.fixture
    def mock_executor(self):
        """Create mock executor."""
        from taox.commands.executor import CommandResult, ExecutionStatus

        executor = MagicMock()
        executor.run = MagicMock(
            return_value=CommandResult(
                status=ExecutionStatus.SUCCESS,
                stdout="Transaction submitted successfully\nhash: 0x1234abcd",
                stderr="",
                return_code=0,
                command=["btcli", "stake", "add"],
            )
        )
        executor.run_interactive = MagicMock(
            return_value=CommandResult(
                status=ExecutionStatus.SUCCESS,
                stdout="Transaction submitted successfully\nhash: 0x1234abcd",
                stderr="",
                return_code=0,
                command=["btcli", "stake", "add"],
            )
        )
        return executor

    def test_dry_run_skips_execution(self, mock_executor):
        """Test that dry-run doesn't execute."""
        pipeline = TransactionPipeline(
            executor=mock_executor,
            dry_run=True,
        )

        plan = build_stake_plan(
            amount=10.0,
            validator_name="Test",
            validator_hotkey="5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v",
            netuid=1,
            wallet="default",
            hotkey="default",
        )

        # Confirm should return False in dry-run
        confirmed = pipeline.confirm(plan)
        assert confirmed is False

        # Executor should not be called
        mock_executor.run.assert_not_called()
        mock_executor.run_interactive.assert_not_called()

    def test_json_output_mode(self, mock_executor):
        """Test JSON output mode."""
        pipeline = TransactionPipeline(
            executor=mock_executor,
            json_output=True,
        )

        plan = build_stake_plan(
            amount=5.0,
            validator_name="Test",
            validator_hotkey="5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v",
            netuid=1,
            wallet="default",
            hotkey="default",
        )

        # In JSON mode, confirm returns True
        confirmed = pipeline.confirm(plan)
        assert confirmed is True

    @pytest.mark.asyncio
    async def test_demo_mode_simulates(self, mock_executor):
        """Test demo mode simulation."""
        with patch("taox.commands.tx_pipeline.get_settings") as mock_settings:
            mock_settings.return_value.demo_mode = True

            pipeline = TransactionPipeline(executor=mock_executor)

            plan = build_stake_plan(
                amount=5.0,
                validator_name="Test",
                validator_hotkey="5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v",
                netuid=1,
                wallet="default",
                hotkey="default",
            )

            result = await pipeline.execute(plan)

            assert result.success is True
            assert "demo" in result.message.lower()
            mock_executor.run.assert_not_called()

    def test_extract_tx_hash(self, mock_executor):
        """Test tx hash extraction from output."""
        pipeline = TransactionPipeline(executor=mock_executor)

        # Standard hex hash
        output1 = "Transaction submitted\n0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        hash1 = pipeline._extract_tx_hash(output1)
        assert hash1 == "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"

        # No hash
        output2 = "Transaction submitted"
        hash2 = pipeline._extract_tx_hash(output2)
        assert hash2 is None

    def test_verification_levels(self, mock_executor):
        """Test different verification levels."""
        pipeline = TransactionPipeline(executor=mock_executor)

        # NONE level
        plan_none = TxPlan(
            title="Test",
            command_name="Test",
            verification_level=VerificationLevel.NONE,
        )
        result_none = TxResult(success=True, phase=TxPhase.IN_BLOCK, message="ok")
        verified_none = pipeline.verify(plan_none, result_none)
        assert verified_none.phase == TxPhase.IN_BLOCK  # Unchanged

        # STDOUT level with hash
        plan_stdout = TxPlan(
            title="Test",
            command_name="Test",
            verification_level=VerificationLevel.STDOUT,
        )
        result_stdout = TxResult(
            success=True,
            phase=TxPhase.IN_BLOCK,
            message="ok",
            tx_hash="0x123",
        )
        verified_stdout = pipeline.verify(plan_stdout, result_stdout)
        assert verified_stdout.phase == TxPhase.FINALIZED


class TestPlanItem:
    """Tests for PlanItem."""

    def test_plan_item_basic(self):
        """Test basic PlanItem creation."""
        item = PlanItem(label="Amount", value="10.0 τ", style="tao")

        assert item.label == "Amount"
        assert item.value == "10.0 τ"
        assert item.style == "tao"
        assert item.is_warning is False

    def test_plan_item_warning(self):
        """Test warning PlanItem."""
        item = PlanItem(
            label="Risk",
            value="High",
            style="warning",
            is_warning=True,
        )

        assert item.is_warning is True


class TestTxPhase:
    """Tests for TxPhase enum."""

    def test_all_phases_exist(self):
        """Test that all expected phases exist."""
        phases = [
            TxPhase.PLANNING,
            TxPhase.SIGNING,
            TxPhase.BROADCASTING,
            TxPhase.IN_BLOCK,
            TxPhase.FINALIZED,
            TxPhase.FAILED,
        ]

        for phase in phases:
            assert phase.value is not None
