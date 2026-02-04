"""Secure btcli command executor for taox."""

import subprocess
import logging
import shlex
from typing import Optional
from dataclasses import dataclass

from taox.config.settings import get_settings


logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a btcli command execution."""

    success: bool
    stdout: str
    stderr: str
    return_code: int
    command: list[str]

    @property
    def output(self) -> str:
        """Get the primary output (stdout or stderr if failed)."""
        return self.stdout if self.success else self.stderr


class BtcliExecutor:
    """Secure executor for btcli commands.

    Security measures:
    - Never uses shell=True
    - Commands passed as list of arguments
    - Validates command structure
    - Timeout on all commands
    """

    ALLOWED_COMMANDS = {
        "wallet": ["list", "balance", "create", "transfer", "new-coldkey", "new-hotkey"],
        "stake": ["add", "remove", "list", "move", "wizard"],
        "subnets": ["list", "metagraph", "hyperparameters", "register", "burn-cost"],
        "config": ["set", "get", "clear"],
        "sudo": ["get-take", "set-take"],
        "root": ["list", "weights"],
    }

    def __init__(self, network: Optional[str] = None, timeout: int = 120):
        """Initialize the executor.

        Args:
            network: Network to use (overrides config)
            timeout: Command timeout in seconds
        """
        self.settings = get_settings()
        self.network = network or self.settings.bittensor.network
        self.timeout = timeout

    def _validate_command(self, group: str, subcommand: str) -> bool:
        """Validate that the command is allowed.

        Args:
            group: Command group (wallet, stake, etc.)
            subcommand: Subcommand name

        Returns:
            True if command is allowed
        """
        allowed = self.ALLOWED_COMMANDS.get(group, [])
        return subcommand in allowed

    def _build_command(
        self,
        group: str,
        subcommand: str,
        args: Optional[dict] = None,
        flags: Optional[list[str]] = None,
    ) -> list[str]:
        """Build a btcli command as a list of arguments.

        Args:
            group: Command group (wallet, stake, etc.)
            subcommand: Subcommand name
            args: Named arguments (--key value pairs)
            flags: Boolean flags (--flag)

        Returns:
            List of command arguments
        """
        cmd = ["btcli", group, subcommand]

        # Add network if specified
        if self.network:
            cmd.extend(["--network", self.network])

        # Add named arguments
        if args:
            for key, value in args.items():
                if value is not None:
                    # Handle boolean values
                    if isinstance(value, bool):
                        if value:
                            cmd.append(f"--{key}")
                    else:
                        cmd.extend([f"--{key}", str(value)])

        # Add flags
        if flags:
            for flag in flags:
                cmd.append(f"--{flag}")

        return cmd

    def run(
        self,
        group: str,
        subcommand: str,
        args: Optional[dict] = None,
        flags: Optional[list[str]] = None,
        dry_run: bool = False,
    ) -> CommandResult:
        """Execute a btcli command.

        Args:
            group: Command group (wallet, stake, etc.)
            subcommand: Subcommand name
            args: Named arguments
            flags: Boolean flags
            dry_run: If True, don't execute, just return the command

        Returns:
            CommandResult with execution details
        """
        # Validate command
        if not self._validate_command(group, subcommand):
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"Command not allowed: {group} {subcommand}",
                return_code=-1,
                command=[],
            )

        # Build command
        cmd = self._build_command(group, subcommand, args, flags)

        if dry_run:
            return CommandResult(
                success=True,
                stdout=f"Would execute: {' '.join(cmd)}",
                stderr="",
                return_code=0,
                command=cmd,
            )

        # Check if in demo mode
        if self.settings.demo_mode:
            return CommandResult(
                success=True,
                stdout=f"[Demo Mode] Command: {' '.join(cmd)}",
                stderr="",
                return_code=0,
                command=cmd,
            )

        # Execute command
        try:
            logger.info(f"Executing: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                shell=False,  # SECURITY: Never use shell=True
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                command=cmd,
            )

        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out after {self.timeout}s")
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"Command timed out after {self.timeout} seconds",
                return_code=-1,
                command=cmd,
            )
        except FileNotFoundError:
            logger.error("btcli not found in PATH")
            return CommandResult(
                success=False,
                stdout="",
                stderr="btcli not found. Please install with: pip install bittensor-cli",
                return_code=-1,
                command=cmd,
            )
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return CommandResult(
                success=False,
                stdout="",
                stderr=str(e),
                return_code=-1,
                command=cmd,
            )

    def get_command_string(
        self,
        group: str,
        subcommand: str,
        args: Optional[dict] = None,
        flags: Optional[list[str]] = None,
    ) -> str:
        """Get the command as a string for display.

        Args:
            group: Command group
            subcommand: Subcommand name
            args: Named arguments
            flags: Boolean flags

        Returns:
            Command string
        """
        cmd = self._build_command(group, subcommand, args, flags)
        return " ".join(cmd)


# Command builders for common operations


def build_stake_add_command(
    amount: float,
    hotkey: str,
    netuid: int,
    wallet_name: Optional[str] = None,
    safe_staking: bool = True,
) -> dict:
    """Build arguments for stake add command.

    Args:
        amount: Amount of TAO to stake
        hotkey: Validator hotkey SS58 address
        netuid: Subnet ID
        wallet_name: Wallet name (optional)
        safe_staking: Enable MEV protection

    Returns:
        Dict with group, subcommand, args, and flags
    """
    args = {
        "amount": amount,
        "include-hotkeys": hotkey,
        "netuid": netuid,
    }
    if wallet_name:
        args["wallet-name"] = wallet_name

    flags = []
    if safe_staking:
        flags.append("safe")

    return {
        "group": "stake",
        "subcommand": "add",
        "args": args,
        "flags": flags,
    }


def build_stake_remove_command(
    amount: float,
    hotkey: str,
    netuid: int,
    wallet_name: Optional[str] = None,
) -> dict:
    """Build arguments for stake remove command."""
    args = {
        "amount": amount,
        "hotkey": hotkey,
        "netuid": netuid,
    }
    if wallet_name:
        args["wallet-name"] = wallet_name

    return {
        "group": "stake",
        "subcommand": "remove",
        "args": args,
        "flags": [],
    }


def build_transfer_command(
    amount: float,
    destination: str,
    wallet_name: Optional[str] = None,
) -> dict:
    """Build arguments for transfer command."""
    args = {
        "amount": amount,
        "dest": destination,
    }
    if wallet_name:
        args["wallet-name"] = wallet_name

    return {
        "group": "wallet",
        "subcommand": "transfer",
        "args": args,
        "flags": [],
    }


def build_balance_command(
    wallet_name: Optional[str] = None,
    all_wallets: bool = False,
) -> dict:
    """Build arguments for balance command."""
    args = {}
    if wallet_name:
        args["wallet-name"] = wallet_name

    flags = []
    if all_wallets:
        flags.append("all")

    return {
        "group": "wallet",
        "subcommand": "balance",
        "args": args,
        "flags": flags,
    }


def build_metagraph_command(
    netuid: int,
    json_output: bool = False,
) -> dict:
    """Build arguments for metagraph command."""
    args = {"netuid": netuid}
    flags = []
    if json_output:
        flags.append("json-output")

    return {
        "group": "subnets",
        "subcommand": "metagraph",
        "args": args,
        "flags": flags,
    }
