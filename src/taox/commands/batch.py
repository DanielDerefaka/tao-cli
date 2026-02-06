"""Batch operations for taox.

Provides safe batch staking operations with:
- Plan view before execution
- Chunking to avoid rate limits
- Progress tracking
- Dry-run support
"""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from rich import box
from rich.panel import Panel
from rich.table import Table

from taox.commands.executor import BtcliExecutor, build_stake_add_command
from taox.config.settings import get_settings
from taox.data.sdk import BittensorSDK
from taox.data.taostats import TaostatsClient, Validator
from taox.errors import ErrorCategory, translate_error
from taox.ui.console import (
    console,
    format_address,
    format_tao,
    print_error,
)
from taox.ui.prompts import confirm
from taox.ui.theme import Symbols, TaoxColors


class RebalanceMode(Enum):
    """Rebalancing modes."""

    EQUAL = "equal"  # Equal distribution
    WEIGHTED = "weighted"  # Weighted by validator score
    TOP_HEAVY = "top_heavy"  # 50% to top, rest split


@dataclass
class BatchOperation:
    """A single operation in a batch."""

    action: str  # "stake", "unstake"
    amount: float
    validator_hotkey: str
    validator_name: Optional[str]
    netuid: int
    status: str = "pending"  # pending, running, success, failed, skipped
    error: Optional[str] = None
    tx_hash: Optional[str] = None


@dataclass
class BatchPlan:
    """A plan for batch operations."""

    operations: list[BatchOperation]
    total_amount: float
    netuid: int
    mode: str
    description: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class BatchResult:
    """Result of batch execution."""

    total_operations: int
    successful: int
    failed: int
    skipped: int
    operations: list[BatchOperation]
    stopped_due_to_rate_limit: bool = False


def calculate_rebalance_plan(
    current_positions: list[dict],
    target_validators: list[Validator],
    total_to_stake: float,
    mode: RebalanceMode,
    netuid: int,
) -> BatchPlan:
    """Calculate a rebalancing plan.

    Args:
        current_positions: Current stake positions
        target_validators: Target validators to stake to
        total_to_stake: Total amount to distribute
        mode: Rebalancing mode
        netuid: Subnet ID

    Returns:
        BatchPlan with operations
    """
    operations = []
    warnings = []

    if not target_validators:
        return BatchPlan(
            operations=[],
            total_amount=total_to_stake,
            netuid=netuid,
            mode=mode.value,
            description="No target validators found",
            warnings=["No validators available for staking"],
        )

    # Calculate allocations based on mode
    allocations = []
    if mode == RebalanceMode.EQUAL:
        # Equal split
        per_validator = total_to_stake / len(target_validators)
        allocations = [(v, per_validator) for v in target_validators]
        description = f"Equal split: {format_tao(per_validator)} each to {len(target_validators)} validators"

    elif mode == RebalanceMode.TOP_HEAVY:
        # 50% to top, rest split equally
        if len(target_validators) == 1:
            allocations = [(target_validators[0], total_to_stake)]
        else:
            top_amount = total_to_stake * 0.5
            rest_amount = total_to_stake * 0.5
            rest_per = rest_amount / (len(target_validators) - 1)

            allocations = [(target_validators[0], top_amount)]
            for v in target_validators[1:]:
                allocations.append((v, rest_per))

        description = f"Top-heavy: 50% to top, rest split to {len(target_validators)-1} others"

    elif mode == RebalanceMode.WEIGHTED:
        # Weighted by stake (higher stake = larger allocation)
        total_stake = sum(v.stake for v in target_validators)
        if total_stake > 0:
            for v in target_validators:
                weight = v.stake / total_stake
                allocations.append((v, total_to_stake * weight))
        else:
            # Fallback to equal if no stake data
            per_validator = total_to_stake / len(target_validators)
            allocations = [(v, per_validator) for v in target_validators]

        description = f"Weighted by stake to {len(target_validators)} validators"

    # Create operations
    for validator, amount in allocations:
        if amount < 0.001:  # Skip tiny amounts
            continue

        operations.append(BatchOperation(
            action="stake",
            amount=amount,
            validator_hotkey=validator.hotkey,
            validator_name=validator.name,
            netuid=netuid,
        ))

    # Add warnings
    if total_to_stake >= 100:
        warnings.append(f"Large stake amount: {format_tao(total_to_stake)}")

    high_take_validators = [v for v, _ in allocations if v.take > 0.15]
    if high_take_validators:
        names = [v.name or v.hotkey[:8] for v in high_take_validators[:3]]
        warnings.append(f"High take rate (>15%): {', '.join(names)}")

    return BatchPlan(
        operations=operations,
        total_amount=total_to_stake,
        netuid=netuid,
        mode=mode.value,
        description=description,
        warnings=warnings,
    )


def display_batch_plan(plan: BatchPlan, share_mode: bool = False) -> None:
    """Display a batch plan for user review."""
    console.print()
    console.print(
        Panel(
            f"[bold]Batch Operation Plan[/bold]\n"
            f"Mode: {plan.mode} | Subnet: {plan.netuid}\n"
            f"Total: {format_tao(plan.total_amount)}",
            box=box.ROUNDED,
            border_style="primary",
        )
    )
    console.print()

    console.print(f"[info]{plan.description}[/info]")
    console.print()

    # Operations table
    table = Table(
        title="[primary]Planned Operations[/primary]",
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
    )
    table.add_column("#", justify="right", style="muted")
    table.add_column("Action", style="info")
    table.add_column("Amount", justify="right", style="tao")
    table.add_column("Validator", style="validator")
    table.add_column("Take", justify="right", style="warning")

    for i, op in enumerate(plan.operations, 1):
        name = op.validator_name or format_address(op.validator_hotkey)
        if share_mode:
            from taox.ui.console import redact_address
            name = op.validator_name or redact_address(op.validator_hotkey)

        # Get take rate if available (would need validator lookup)
        take_str = "-"

        table.add_row(
            str(i),
            op.action.upper(),
            format_tao(op.amount),
            name[:20] + "..." if len(str(name)) > 20 else str(name),
            take_str,
        )

    console.print(table)

    # Warnings
    if plan.warnings:
        console.print()
        console.print("[bold yellow]Warnings:[/bold yellow]")
        for warning in plan.warnings:
            console.print(f"  {Symbols.WARN} {warning}")

    console.print()


async def execute_batch(
    plan: BatchPlan,
    executor: BtcliExecutor,
    wallet_name: str,
    chunk_size: int = 3,
    chunk_delay: float = 5.0,
    dry_run: bool = False,
    on_progress: Optional[callable] = None,
) -> BatchResult:
    """Execute a batch plan with chunking.

    Args:
        plan: BatchPlan to execute
        executor: BtcliExecutor instance
        wallet_name: Wallet name
        chunk_size: Number of operations per chunk
        chunk_delay: Seconds to wait between chunks
        dry_run: If True, don't actually execute
        on_progress: Callback for progress updates

    Returns:
        BatchResult with execution status
    """
    result = BatchResult(
        total_operations=len(plan.operations),
        successful=0,
        failed=0,
        skipped=0,
        operations=plan.operations,
    )

    if dry_run:
        console.print("[info]Dry run - no operations executed[/info]")
        for op in plan.operations:
            op.status = "skipped"
            result.skipped += 1
        return result

    # Process in chunks
    for chunk_start in range(0, len(plan.operations), chunk_size):
        chunk = plan.operations[chunk_start:chunk_start + chunk_size]
        chunk_num = (chunk_start // chunk_size) + 1
        total_chunks = (len(plan.operations) + chunk_size - 1) // chunk_size

        console.print(f"\n[info]Processing chunk {chunk_num}/{total_chunks}...[/info]")

        for op in chunk:
            op.status = "running"

            if on_progress:
                on_progress(op)

            try:
                # Build and execute command
                cmd_info = build_stake_add_command(
                    amount=op.amount,
                    hotkey=op.validator_hotkey,
                    netuid=op.netuid,
                    wallet_name=wallet_name,
                    safe_staking=True,
                )

                console.print(f"  {Symbols.PENDING} Staking {format_tao(op.amount)} to {op.validator_name or op.validator_hotkey[:12]}...")

                exec_result = executor.run_interactive(**cmd_info)

                if exec_result.success:
                    op.status = "success"
                    result.successful += 1
                    console.print(f"  {Symbols.CHECK} Success")
                else:
                    op.status = "failed"
                    op.error = exec_result.stderr
                    result.failed += 1
                    console.print(f"  {Symbols.ERROR} Failed: {exec_result.stderr[:50]}")

                    # Check for rate limit
                    error_info = translate_error(exec_result.stderr or "")
                    if error_info.category == ErrorCategory.RATE_LIMIT:
                        console.print("[warning]Rate limit detected - stopping batch[/warning]")
                        result.stopped_due_to_rate_limit = True

                        # Mark remaining as skipped
                        remaining_start = plan.operations.index(op) + 1
                        for remaining_op in plan.operations[remaining_start:]:
                            remaining_op.status = "skipped"
                            result.skipped += 1

                        return result

            except Exception as e:
                op.status = "failed"
                op.error = str(e)
                result.failed += 1
                console.print(f"  {Symbols.ERROR} Error: {e}")

        # Delay between chunks (except for last chunk)
        if chunk_start + chunk_size < len(plan.operations):
            console.print(f"[muted]Waiting {chunk_delay}s before next chunk...[/muted]")
            await asyncio.sleep(chunk_delay)

    return result


def display_batch_result(result: BatchResult) -> None:
    """Display batch execution result."""
    console.print()

    if result.stopped_due_to_rate_limit:
        console.print(
            Panel(
                "[warning]Batch stopped due to rate limit[/warning]\n"
                "Wait a few minutes and run again to continue.",
                box=box.ROUNDED,
                border_style="warning",
            )
        )
        console.print()

    # Summary
    success_color = "success" if result.successful > 0 else "muted"
    failed_color = "error" if result.failed > 0 else "muted"

    console.print("[bold]Batch Result:[/bold]")
    console.print(f"  [{success_color}]{Symbols.CHECK} Successful: {result.successful}[/{success_color}]")
    console.print(f"  [{failed_color}]{Symbols.ERROR} Failed: {result.failed}[/{failed_color}]")
    if result.skipped > 0:
        console.print(f"  [muted]{Symbols.WARN} Skipped: {result.skipped}[/muted]")


async def stake_rebalance(
    executor: BtcliExecutor,
    sdk: BittensorSDK,
    taostats: TaostatsClient,
    amount: float,
    netuid: int = 1,
    top_n: int = 5,
    mode: str = "equal",
    wallet_name: Optional[str] = None,
    chunk_size: int = 3,
    dry_run: bool = False,
    skip_confirm: bool = False,
    share_mode: bool = False,
    json_output: bool = False,
) -> BatchResult:
    """Rebalance stake across top validators.

    Args:
        executor: BtcliExecutor instance
        sdk: BittensorSDK instance
        taostats: TaostatsClient instance
        amount: Total amount to stake
        netuid: Subnet ID
        top_n: Number of top validators to stake to
        mode: Rebalancing mode (equal, weighted, top_heavy)
        wallet_name: Wallet name
        chunk_size: Operations per chunk
        dry_run: Show plan without executing
        skip_confirm: Skip confirmation prompt
        share_mode: Redact addresses
        json_output: Output as JSON

    Returns:
        BatchResult
    """
    import json

    settings = get_settings()
    wallet_name = wallet_name or settings.bittensor.default_wallet

    # Parse mode
    try:
        rebalance_mode = RebalanceMode(mode.lower())
    except ValueError:
        print_error(f"Invalid mode: {mode}. Use: equal, weighted, top_heavy")
        return BatchResult(
            total_operations=0,
            successful=0,
            failed=0,
            skipped=0,
            operations=[],
        )

    # Get target validators
    with console.status("[bold green]Fetching validators..."):
        validators = await taostats.get_validators(netuid=netuid, limit=top_n)

    if not validators:
        print_error(f"No validators found on subnet {netuid}")
        return BatchResult(
            total_operations=0,
            successful=0,
            failed=0,
            skipped=0,
            operations=[],
        )

    # Get current positions (if any)
    wallet = sdk.get_wallet(name=wallet_name)
    if wallet:
        current_positions = await taostats.get_stake_balance(wallet.coldkey.ss58_address)
        current_positions = current_positions.get("positions", [])
    else:
        current_positions = []

    # Calculate plan
    plan = calculate_rebalance_plan(
        current_positions=current_positions,
        target_validators=validators,
        total_to_stake=amount,
        mode=rebalance_mode,
        netuid=netuid,
    )

    if not plan.operations:
        console.print("[warning]No operations to execute.[/warning]")
        return BatchResult(
            total_operations=0,
            successful=0,
            failed=0,
            skipped=0,
            operations=[],
        )

    # JSON output for dry-run
    if json_output:
        output = {
            "mode": plan.mode,
            "netuid": plan.netuid,
            "total_amount": plan.total_amount,
            "operations": [
                {
                    "action": op.action,
                    "amount": op.amount,
                    "validator": op.validator_name,
                    "hotkey": op.validator_hotkey if not share_mode else "***",
                    "status": op.status,
                }
                for op in plan.operations
            ],
            "warnings": plan.warnings,
            "dry_run": dry_run,
        }
        print(json.dumps(output, indent=2))

        if dry_run:
            return BatchResult(
                total_operations=len(plan.operations),
                successful=0,
                failed=0,
                skipped=len(plan.operations),
                operations=plan.operations,
            )

    # Display plan
    if not json_output:
        display_batch_plan(plan, share_mode=share_mode)

    # Dry run stops here
    if dry_run:
        console.print("[info]Dry run complete. No operations executed.[/info]")
        return BatchResult(
            total_operations=len(plan.operations),
            successful=0,
            failed=0,
            skipped=len(plan.operations),
            operations=plan.operations,
        )

    # Confirm
    if not skip_confirm:
        console.print(f"[warning]This will execute {len(plan.operations)} stake operations.[/warning]")
        if not confirm("Proceed with batch stake?"):
            console.print("[muted]Batch cancelled.[/muted]")
            return BatchResult(
                total_operations=len(plan.operations),
                successful=0,
                failed=0,
                skipped=len(plan.operations),
                operations=plan.operations,
            )

    # Execute
    console.print()
    console.print("[info]Executing batch operations...[/info]")

    result = await execute_batch(
        plan=plan,
        executor=executor,
        wallet_name=wallet_name,
        chunk_size=chunk_size,
        dry_run=settings.demo_mode,  # Use demo mode setting
    )

    # Display result
    if not json_output:
        display_batch_result(result)

    return result
