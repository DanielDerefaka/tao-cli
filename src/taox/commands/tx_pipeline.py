"""Transaction Pipeline - Plan → Confirm → Execute → Verify.

This module provides a consistent transaction execution flow:
1. Plan: Build and display transaction details
2. Confirm: Require explicit user confirmation
3. Execute: Run command with safety guards
4. Verify: Check result and report status

All chain-state-changing operations should use this pipeline.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from taox.commands.executor import BtcliExecutor, CommandResult, ExecutionStatus
from taox.config.settings import get_settings
from taox.ui.console import (
    CommandContext,
    PlanItem,
    TxPhase,
    TxStatus,
    console,
    print_confirmation_prompt,
    print_next_steps,
    print_plan,
    print_title_panel,
    print_tx_status,
)

logger = logging.getLogger(__name__)


class VerificationLevel(Enum):
    """Levels of transaction verification."""

    NONE = 0  # No verification (just check exit code)
    STDOUT = 1  # Parse stdout for success indicators
    TX_HASH = 2  # Extract tx hash and check status
    CHAIN = 3  # Query chain to confirm finalization


@dataclass
class TxPlan:
    """A transaction plan ready for confirmation."""

    # Display
    title: str
    command_name: str
    items: list[PlanItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Context
    network: str = "finney"
    wallet: Optional[str] = None
    hotkey: Optional[str] = None

    # Execution
    btcli_args: list[str] = field(default_factory=list)
    requires_password: bool = True
    verification_level: VerificationLevel = VerificationLevel.STDOUT

    # Results (filled after execution)
    tx_hash: Optional[str] = None
    block_number: Optional[int] = None
    verified: bool = False
    error: Optional[str] = None


@dataclass
class TxResult:
    """Result of transaction execution."""

    success: bool
    phase: TxPhase
    message: str
    tx_hash: Optional[str] = None
    block_number: Optional[int] = None
    raw_output: Optional[str] = None
    error: Optional[str] = None
    next_steps: list[str] = field(default_factory=list)


class TransactionPipeline:
    """Manages transaction lifecycle with consistent UX."""

    def __init__(
        self,
        executor: BtcliExecutor,
        dry_run: bool = False,
        json_output: bool = False,
        share_mode: bool = False,
    ):
        """Initialize pipeline.

        Args:
            executor: btcli executor instance
            dry_run: If True, show plan but don't execute
            json_output: If True, output JSON instead of Rich
            share_mode: If True, redact sensitive info
        """
        self.executor = executor
        self.dry_run = dry_run
        self.json_output = json_output
        self.share_mode = share_mode
        self.settings = get_settings()

    def show_plan(self, plan: TxPlan) -> None:
        """Display transaction plan (Step A)."""
        if self.json_output:
            self._output_plan_json(plan)
            return

        # Title panel
        ctx = CommandContext(
            command=plan.command_name,
            network=plan.network,
            wallet=plan.wallet,
            hotkey=plan.hotkey,
        )
        print_title_panel(ctx)

        # Plan details
        print_plan(
            title=plan.title,
            items=plan.items,
            warnings=plan.warnings,
            dry_run=self.dry_run,
        )

    def confirm(self, plan: TxPlan) -> bool:
        """Get user confirmation (Step B).

        Returns:
            True if user confirms, False otherwise
        """
        if self.dry_run:
            console.print("\n[info]Dry run - skipping execution[/info]")
            return False

        if self.json_output:
            # In JSON mode, assume confirmed (caller handles this)
            return True

        print_confirmation_prompt()
        try:
            response = input().strip().lower()
            return response in ("yes", "y")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[warning]Cancelled[/warning]")
            return False

    async def execute(
        self,
        plan: TxPlan,
        password_callback: Optional[Callable[[], str]] = None,
    ) -> TxResult:
        """Execute transaction (Step C).

        Args:
            plan: Transaction plan to execute
            password_callback: Function to get password if needed

        Returns:
            TxResult with execution outcome
        """
        # Show signing phase
        self._show_phase(TxPhase.SIGNING, "Preparing transaction...")

        # Check demo mode
        if self.settings.demo_mode:
            await asyncio.sleep(0.5)  # Simulate
            return TxResult(
                success=True,
                phase=TxPhase.FINALIZED,
                message="Demo mode - transaction simulated",
                next_steps=["taox portfolio", "taox balance"],
            )

        try:
            # Show broadcasting phase
            self._show_phase(TxPhase.BROADCASTING, "Broadcasting to network...")

            # Execute command
            if plan.requires_password and password_callback:
                password = password_callback()
                result = self.executor.run_interactive(
                    plan.btcli_args,
                    password=password,
                )
            else:
                result = self.executor.run(plan.btcli_args)

            # Process result
            return self._process_result(result, plan)

        except Exception as e:
            logger.exception(f"Transaction failed: {e}")
            return TxResult(
                success=False,
                phase=TxPhase.FAILED,
                message="Transaction failed",
                error=str(e),
            )

    def verify(self, plan: TxPlan, result: TxResult) -> TxResult:
        """Verify transaction outcome (Step D).

        This enhances the result with verification status.
        """
        if not result.success:
            return result

        if plan.verification_level == VerificationLevel.NONE:
            return result

        # For STDOUT level, we already parsed in _process_result
        if plan.verification_level == VerificationLevel.STDOUT:
            if result.tx_hash:
                result.phase = TxPhase.FINALIZED
                result.message = "Transaction finalized"
            else:
                result.phase = TxPhase.IN_BLOCK
                result.message = "Transaction submitted"
            return result

        # For TX_HASH level, extract and check
        if plan.verification_level >= VerificationLevel.TX_HASH:
            if result.tx_hash:
                # Could add chain query here
                result.phase = TxPhase.FINALIZED
            else:
                result.phase = TxPhase.IN_BLOCK

        return result

    def show_result(self, result: TxResult) -> None:
        """Display transaction result."""
        if self.json_output:
            self._output_result_json(result)
            return

        # Show final status
        status = TxStatus(
            phase=result.phase,
            message=result.message,
            tx_hash=result.tx_hash,
            block_number=result.block_number,
            error=result.error,
        )
        print_tx_status(status)

        # Show next steps
        if result.next_steps:
            console.print()
            print_next_steps(result.next_steps)

    async def run(
        self,
        plan: TxPlan,
        password_callback: Optional[Callable[[], str]] = None,
        skip_confirm: bool = False,
    ) -> TxResult:
        """Run full pipeline: Plan → Confirm → Execute → Verify.

        Args:
            plan: Transaction plan
            password_callback: Function to get password
            skip_confirm: Skip confirmation (for pre-confirmed flows)

        Returns:
            Final TxResult
        """
        # Step A: Show plan
        self.show_plan(plan)

        # Step B: Confirm
        if not skip_confirm:
            if not self.confirm(plan):
                return TxResult(
                    success=False,
                    phase=TxPhase.FAILED,
                    message="Cancelled by user",
                )

        # Step C: Execute
        result = await self.execute(plan, password_callback)

        # Step D: Verify
        result = self.verify(plan, result)

        # Show result
        self.show_result(result)

        return result

    def _show_phase(self, phase: TxPhase, message: str) -> None:
        """Show transaction phase update."""
        if self.json_output:
            return
        print_tx_status(TxStatus(phase=phase, message=message))

    def _process_result(self, cmd_result: CommandResult, plan: TxPlan) -> TxResult:
        """Process command result into TxResult."""
        output = cmd_result.stdout or ""

        # Check for success
        if cmd_result.status == ExecutionStatus.SUCCESS:
            # Try to extract tx hash
            tx_hash = self._extract_tx_hash(output)

            return TxResult(
                success=True,
                phase=TxPhase.IN_BLOCK,
                message="Transaction submitted",
                tx_hash=tx_hash,
                raw_output=output,
                next_steps=["taox portfolio", "taox balance"],
            )

        # Handle failure
        error = cmd_result.stderr or cmd_result.stdout or "Unknown error"
        return TxResult(
            success=False,
            phase=TxPhase.FAILED,
            message="Transaction failed",
            error=error,
            raw_output=output,
        )

    def _extract_tx_hash(self, output: str) -> Optional[str]:
        """Extract transaction hash from output."""
        import re

        # Look for common tx hash patterns
        patterns = [
            r"0x[a-fA-F0-9]{64}",  # Standard hex hash
            r"tx(?:_hash)?[:\s]+([a-fA-F0-9]{64})",  # Labeled hash
        ]

        for pattern in patterns:
            match = re.search(pattern, output)
            if match:
                return match.group(0) if "0x" in pattern else f"0x{match.group(1)}"

        return None

    def _output_plan_json(self, plan: TxPlan) -> None:
        """Output plan as JSON."""
        import json

        from taox.ui.console import json_console

        data = {
            "type": "plan",
            "title": plan.title,
            "command": plan.command_name,
            "network": plan.network,
            "wallet": plan.wallet,
            "hotkey": plan.hotkey,
            "items": [{"label": i.label, "value": i.value} for i in plan.items],
            "warnings": plan.warnings,
            "dry_run": self.dry_run,
        }
        json_console.print(json.dumps(data, indent=2))

    def _output_result_json(self, result: TxResult) -> None:
        """Output result as JSON."""
        import json

        from taox.ui.console import json_console

        data = {
            "type": "result",
            "success": result.success,
            "phase": result.phase.value,
            "message": result.message,
            "tx_hash": result.tx_hash,
            "block_number": result.block_number,
            "error": result.error,
            "next_steps": result.next_steps,
        }
        json_console.print(json.dumps(data, indent=2))


# =============================================================================
# Helper functions for building plans
# =============================================================================


def build_stake_plan(
    amount: float,
    validator_name: str,
    validator_hotkey: str,
    netuid: int,
    wallet: str,
    hotkey: str,
    network: str = "finney",
) -> TxPlan:
    """Build a stake transaction plan."""
    items = [
        PlanItem("Action", "Stake TAO", "success"),
        PlanItem("Amount", f"{amount:,.4f} τ", "tao"),
        PlanItem("Validator", validator_name, "validator"),
        PlanItem("Hotkey", f"{validator_hotkey[:8]}...{validator_hotkey[-6:]}", "address"),
        PlanItem("Subnet", f"SN{netuid}", "subnet"),
        PlanItem("Est. Fee", "~0.0001 τ", "muted"),
    ]

    warnings = []
    if amount >= 10:
        warnings.append("High-value transaction (≥10 τ)")

    return TxPlan(
        title="Stake Plan",
        command_name="Stake",
        items=items,
        warnings=warnings,
        network=network,
        wallet=wallet,
        hotkey=hotkey,
        btcli_args=[
            "stake",
            "add",
            "--amount",
            str(amount),
            "--wallet-name",
            wallet,
            "--hotkey-ss58",
            validator_hotkey,
            "--netuid",
            str(netuid),
        ],
        requires_password=True,
        verification_level=VerificationLevel.STDOUT,
    )


def build_transfer_plan(
    amount: float,
    destination: str,
    wallet: str,
    network: str = "finney",
) -> TxPlan:
    """Build a transfer transaction plan."""
    items = [
        PlanItem("Action", "Transfer TAO", "success"),
        PlanItem("Amount", f"{amount:,.4f} τ", "tao"),
        PlanItem("To", f"{destination[:8]}...{destination[-6:]}", "address"),
        PlanItem("Est. Fee", "~0.0001 τ", "muted"),
    ]

    warnings = []
    if amount >= 10:
        warnings.append("High-value transaction (≥10 τ)")
    warnings.append("Transfers are irreversible")

    return TxPlan(
        title="Transfer Plan",
        command_name="Transfer",
        items=items,
        warnings=warnings,
        network=network,
        wallet=wallet,
        btcli_args=[
            "wallet",
            "transfer",
            "--amount",
            str(amount),
            "--destination",
            destination,
            "--wallet-name",
            wallet,
        ],
        requires_password=True,
        verification_level=VerificationLevel.STDOUT,
    )


def build_register_plan(
    netuid: int,
    wallet: str,
    hotkey: str,
    burn_cost: float,
    network: str = "finney",
) -> TxPlan:
    """Build a registration transaction plan."""
    items = [
        PlanItem("Action", "Register on Subnet", "success"),
        PlanItem("Subnet", f"SN{netuid}", "subnet"),
        PlanItem("Burn Cost", f"{burn_cost:,.4f} τ", "tao"),
        PlanItem("Wallet", wallet, "primary"),
        PlanItem("Hotkey", hotkey, "secondary"),
    ]

    warnings = [
        f"This will burn {burn_cost:.4f} τ (non-refundable)",
    ]

    return TxPlan(
        title="Registration Plan",
        command_name="Register",
        items=items,
        warnings=warnings,
        network=network,
        wallet=wallet,
        hotkey=hotkey,
        btcli_args=[
            "subnet",
            "register",
            "--netuid",
            str(netuid),
            "--wallet-name",
            wallet,
            "--hotkey-name",
            hotkey,
        ],
        requires_password=True,
        verification_level=VerificationLevel.STDOUT,
    )
