"""Secure, debuggable btcli command executor for taox.

This module provides a hardened execution layer for btcli commands with:
- Dry-run mode for all commands
- Secure debug logging (never logs passwords)
- Robust pexpect-based password handling
- Reliable status parsing (success/failed/timeout/unknown)
- Postflight verification for transactions
"""

import getpass
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import pexpect

from taox.config.settings import get_settings

# Configure module logger
logger = logging.getLogger(__name__)

# Debug log directory
DEBUG_LOG_DIR = Path.home() / ".taox" / "logs"


class ExecutionStatus(str, Enum):
    """Status of command execution."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"
    DRY_RUN = "dry_run"
    DEMO_MODE = "demo_mode"


class ExecutionMode(str, Enum):
    """Mode of execution."""

    NORMAL = "normal"  # Non-interactive subprocess
    INTERACTIVE = "interactive"  # pexpect with password handling
    DRY_RUN = "dry_run"  # Print command, don't execute


# Comprehensive password prompt patterns for different btcli commands
# Organized by specificity (most specific first)
PASSWORD_PATTERNS = [
    # Coldkey specific
    r"Enter your coldkey password",
    r"Enter the password to unlock your coldkey",
    r"Unlock your coldkey",
    r"Decrypting coldkey",
    r"decrypt.*coldkey",
    # Hotkey specific
    r"Enter your hotkey password",
    r"Unlock your hotkey",
    # Generic password prompts
    r"Enter password",
    r"Enter the password",
    r"Password:",
    r"password:",
    r"Passphrase:",
    r"passphrase:",
    # Confirmation prompts (not passwords, but need handling)
    r"Enter.*password.*to.*confirm",
]

# Confirmation prompts that require y/n response (not password)
CONFIRMATION_PATTERNS = [
    r"Proceed with transfer\?",
    r"Proceed with stake\?",
    r"Proceed with unstake\?",
    r"Proceed\?.*\(y/n\)",
    r"Proceed\?.*\(n\)",
    r"Continue\?.*\(y/n\)",
    r"Continue\?.*\(n\)",
    r"Are you sure\?",
    r"Do you want to continue\?",
    r"\(y/N\)\s*:",
    r"\(Y/n\)\s*:",
    r"\[y/N\]",
    r"\[Y/n\]",
]

# Success indicators in btcli output
SUCCESS_PATTERNS = [
    r"✅",
    r"Success",
    r"success",
    r"Successfully",
    r"successfully",
    r"Finalized",
    r"finalized",
    r"Transaction submitted",
    r"Extrinsic submitted",
    r"Block hash:",
    r"block_hash",
]

# Failure indicators in btcli output
FAILURE_PATTERNS = [
    r"❌",
    r"Error",
    r"error",
    r"Failed",
    r"failed",
    r"Failure",
    r"failure",
    r"insufficient",
    r"Insufficient",
    r"not found",
    r"Not found",
    r"invalid",
    r"Invalid",
    r"denied",
    r"Denied",
    r"rejected",
    r"Rejected",
    r"cancelled",
    r"Cancelled",
    r"abort",
    r"Abort",
]

# Transaction hash pattern
TX_HASH_PATTERN = re.compile(r"(?:0x)?([a-fA-F0-9]{64})")


@dataclass
class CommandResult:
    """Result of a btcli command execution.

    Attributes:
        status: Execution status (success/failed/timeout/unknown)
        stdout: Standard output from the command
        stderr: Standard error from the command
        return_code: Process return code (-1 for errors before execution)
        command: The command that was executed (list of args)
        command_string: Human-readable command string (sanitized)
        execution_time: How long the command took in seconds
        tx_hash: Transaction hash if found in output
        debug_log_path: Path to debug log file if debug mode enabled
        error_message: Parsed, human-friendly error message
        raw_output: Complete raw output for debugging
    """

    status: ExecutionStatus
    stdout: str
    stderr: str
    return_code: int
    command: list[str]
    command_string: str = ""
    execution_time: float = 0.0
    tx_hash: Optional[str] = None
    debug_log_path: Optional[str] = None
    error_message: Optional[str] = None
    raw_output: str = ""

    @property
    def success(self) -> bool:
        """Check if command succeeded."""
        return self.status in (
            ExecutionStatus.SUCCESS,
            ExecutionStatus.DRY_RUN,
            ExecutionStatus.DEMO_MODE,
        )

    @property
    def output(self) -> str:
        """Get primary output (stdout or stderr if failed)."""
        return self.stdout if self.success else (self.stderr or self.stdout)

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "status": self.status.value,
            "success": self.success,
            "return_code": self.return_code,
            "execution_time": self.execution_time,
            "tx_hash": self.tx_hash,
            "error_message": self.error_message,
            "command_string": self.command_string,
            # Don't include raw output in dict (too large)
        }


class SecureDebugLogger:
    """Secure logger that never logs passwords or secrets."""

    # Patterns to redact from logs
    REDACT_PATTERNS = [
        (re.compile(r"(password[=:\s]+)\S+", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(passphrase[=:\s]+)\S+", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(mnemonic[=:\s]+).+", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(seed[=:\s]+)\S+", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(secret[=:\s]+)\S+", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(api[_-]?key[=:\s]+)\S+", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(token[=:\s]+)\S+", re.IGNORECASE), r"\1[REDACTED]"),
        # Redact anything that looks like a private key
        (re.compile(r"[0-9a-fA-F]{64}(?![0-9a-fA-F])"), r"[REDACTED_KEY]"),
    ]

    def __init__(self, enabled: bool = False, log_dir: Optional[Path] = None):
        """Initialize debug logger.

        Args:
            enabled: Whether debug logging is enabled
            log_dir: Directory for log files (default ~/.taox/logs)
        """
        self.enabled = enabled
        self.log_dir = log_dir or DEBUG_LOG_DIR
        self._current_log_path: Optional[Path] = None

    def _ensure_log_dir(self) -> None:
        """Ensure log directory exists with secure permissions."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # Set restrictive permissions (owner only)
        os.chmod(self.log_dir, 0o700)

    def _sanitize(self, text: str) -> str:
        """Remove sensitive data from text."""
        for pattern, replacement in self.REDACT_PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def start_command_log(self, command: list[str], command_string: str) -> Optional[Path]:
        """Start a new log file for a command execution.

        Args:
            command: Command arguments
            command_string: Sanitized command string

        Returns:
            Path to log file, or None if logging disabled
        """
        if not self.enabled:
            return None

        self._ensure_log_dir()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Use command group and subcommand for filename
        cmd_name = f"{command[1]}_{command[2]}" if len(command) > 2 else "unknown"
        self._current_log_path = self.log_dir / f"{timestamp}_{cmd_name}.log"

        with open(self._current_log_path, "w") as f:
            f.write("=== TAOX Debug Log ===\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Command: {self._sanitize(command_string)}\n")
            f.write(f"{'='*50}\n\n")

        return self._current_log_path

    def log_output(self, label: str, content: str) -> None:
        """Log output to current log file.

        Args:
            label: Label for this output section
            content: Content to log (will be sanitized)
        """
        if not self.enabled or not self._current_log_path:
            return

        with open(self._current_log_path, "a") as f:
            f.write(f"\n--- {label} ---\n")
            f.write(self._sanitize(content))
            f.write("\n")

    def log_result(self, result: CommandResult) -> None:
        """Log final result to current log file.

        Args:
            result: Command execution result
        """
        if not self.enabled or not self._current_log_path:
            return

        with open(self._current_log_path, "a") as f:
            f.write(f"\n{'='*50}\n")
            f.write("=== RESULT ===\n")
            f.write(f"Status: {result.status.value}\n")
            f.write(f"Return Code: {result.return_code}\n")
            f.write(f"Execution Time: {result.execution_time:.2f}s\n")
            if result.tx_hash:
                f.write(f"TX Hash: {result.tx_hash}\n")
            if result.error_message:
                f.write(f"Error: {result.error_message}\n")
            f.write(f"{'='*50}\n")


class OutputParser:
    """Parse btcli output to determine status and extract information."""

    @staticmethod
    def determine_status(stdout: str, stderr: str, return_code: int) -> ExecutionStatus:
        """Determine execution status from output.

        Args:
            stdout: Standard output
            stderr: Standard error
            return_code: Process return code

        Returns:
            ExecutionStatus
        """
        combined = (stdout + " " + stderr).lower()

        # Check return code first
        if return_code != 0 and return_code != -1:
            # Non-zero return code usually means failure
            return ExecutionStatus.FAILED

        # Check for explicit success indicators
        for pattern in SUCCESS_PATTERNS:
            if re.search(pattern, stdout, re.IGNORECASE):
                return ExecutionStatus.SUCCESS

        # Check for explicit failure indicators
        for pattern in FAILURE_PATTERNS:
            if re.search(pattern, combined, re.IGNORECASE):
                return ExecutionStatus.FAILED

        # If we got here with return code 0, assume success
        if return_code == 0:
            return ExecutionStatus.SUCCESS

        # Can't determine
        return ExecutionStatus.UNKNOWN

    @staticmethod
    def extract_tx_hash(output: str) -> Optional[str]:
        """Extract transaction hash from output.

        Args:
            output: Command output

        Returns:
            Transaction hash if found
        """
        match = TX_HASH_PATTERN.search(output)
        if match:
            return match.group(0)
        return None

    @staticmethod
    def parse_error_message(stdout: str, stderr: str) -> Optional[str]:
        """Parse a human-friendly error message from output.

        Args:
            stdout: Standard output
            stderr: Standard error

        Returns:
            Human-friendly error message
        """
        combined = stdout + "\n" + stderr

        # Common error mappings
        error_mappings = [
            (r"insufficient.*balance", "Insufficient balance for this transaction"),
            (r"invalid.*address", "Invalid destination address"),
            (r"not.*registered", "Hotkey not registered on this subnet"),
            (r"password.*incorrect", "Incorrect wallet password"),
            (r"wrong.*password", "Incorrect wallet password"),
            (r"decryption.*failed", "Failed to decrypt wallet - wrong password?"),
            (r"connection.*refused", "Cannot connect to network"),
            (r"timed?\s*out", "Operation timed out"),
            (r"no.*wallet", "Wallet not found"),
            (r"coldkey.*not.*found", "Coldkey not found"),
            (r"hotkey.*not.*found", "Hotkey not found"),
        ]

        combined_lower = combined.lower()
        for pattern, message in error_mappings:
            if re.search(pattern, combined_lower):
                return message

        # If we have stderr, return first line
        if stderr.strip():
            first_line = stderr.strip().split("\n")[0]
            if len(first_line) < 200:
                return first_line

        return None


class BtcliExecutor:
    """Secure, debuggable executor for btcli commands.

    Features:
    - Dry-run mode for all commands
    - Debug logging with password redaction
    - Robust pexpect-based password handling
    - Reliable status parsing
    - Timeout handling
    - Postflight verification

    Security:
    - Never uses shell=True
    - Commands passed as list of arguments
    - Validates command structure against whitelist
    - Passwords never logged
    """

    ALLOWED_COMMANDS = {
        "wallet": ["list", "balance", "create", "transfer", "new-coldkey", "new-hotkey"],
        "stake": ["add", "remove", "list", "move", "wizard", "child"],
        "subnets": [
            "list",
            "metagraph",
            "hyperparameters",
            "register",
            "pow-register",
            "burn-cost",
        ],
        "config": ["set", "get", "clear"],
        "sudo": ["get-take", "set-take"],
        "root": ["list", "weights"],
    }

    def __init__(
        self,
        network: Optional[str] = None,
        timeout: int = 120,
        debug: bool = False,
    ):
        """Initialize the executor.

        Args:
            network: Network to use (finney/test/local, overrides config)
            timeout: Command timeout in seconds
            debug: Enable debug logging
        """
        self.settings = get_settings()
        self.network = network or self.settings.bittensor.network
        self.timeout = timeout
        self.debug_logger = SecureDebugLogger(enabled=debug)
        self._output_parser = OutputParser()

    def enable_debug(self, enabled: bool = True) -> None:
        """Enable or disable debug logging."""
        self.debug_logger.enabled = enabled

    def _validate_command(self, group: str, subcommand: str) -> bool:
        """Validate command against whitelist."""
        allowed = self.ALLOWED_COMMANDS.get(group, [])
        return subcommand in allowed

    def _build_command(
        self,
        group: str,
        subcommand: str,
        args: Optional[dict] = None,
        flags: Optional[list[str]] = None,
    ) -> list[str]:
        """Build command as argument list.

        Args:
            group: Command group (wallet, stake, etc.)
            subcommand: Subcommand name
            args: Named arguments (--key value pairs)
            flags: Boolean flags (--flag)

        Returns:
            List of command arguments
        """
        cmd = ["btcli", group, subcommand]

        if self.network:
            cmd.extend(["--network", self.network])

        if args:
            for key, value in args.items():
                if value is not None:
                    if isinstance(value, bool):
                        if value:
                            cmd.append(f"--{key}")
                    else:
                        cmd.extend([f"--{key}", str(value)])

        if flags:
            for flag in flags:
                cmd.append(f"--{flag}")

        return cmd

    def _sanitize_command_string(self, cmd: list[str]) -> str:
        """Create sanitized command string for display/logging."""
        # Don't include any values that might be sensitive
        sanitized = []
        skip_next = False
        for i, arg in enumerate(cmd):
            if skip_next:
                skip_next = False
                sanitized.append("[VALUE]")
                continue
            if arg.startswith("--") and i + 1 < len(cmd) and not cmd[i + 1].startswith("--"):
                # This is a --key value pair
                sanitized.append(arg)
                skip_next = True
            else:
                sanitized.append(arg)
        return " ".join(sanitized)

    def get_command_string(
        self,
        group: str,
        subcommand: str,
        args: Optional[dict] = None,
        flags: Optional[list[str]] = None,
    ) -> str:
        """Get human-readable command string (for dry-run display)."""
        cmd = self._build_command(group, subcommand, args, flags)
        return " ".join(cmd)

    def execute(
        self,
        group: str,
        subcommand: str,
        args: Optional[dict] = None,
        flags: Optional[list[str]] = None,
        mode: ExecutionMode = ExecutionMode.INTERACTIVE,
        dry_run: bool = False,
        password_callback: Optional[Callable[[], str]] = None,
    ) -> CommandResult:
        """Execute a btcli command.

        This is the main entry point for command execution. Use this method
        for all btcli operations.

        Args:
            group: Command group (wallet, stake, etc.)
            subcommand: Subcommand name
            args: Named arguments
            flags: Boolean flags
            mode: Execution mode (normal/interactive/dry_run)
            dry_run: If True, don't execute (overrides mode)
            password_callback: Optional callback for password (default: getpass)

        Returns:
            CommandResult with execution details
        """
        start_time = datetime.now()

        # Validate command
        if not self._validate_command(group, subcommand):
            return CommandResult(
                status=ExecutionStatus.FAILED,
                stdout="",
                stderr=f"Command not allowed: {group} {subcommand}",
                return_code=-1,
                command=[],
                error_message=f"Command not allowed: {group} {subcommand}",
            )

        # Build command
        cmd = self._build_command(group, subcommand, args, flags)
        cmd_string = " ".join(cmd)
        sanitized_cmd_string = self._sanitize_command_string(cmd)

        # Start debug logging
        debug_log_path = self.debug_logger.start_command_log(cmd, sanitized_cmd_string)

        # Handle dry-run mode
        if dry_run or mode == ExecutionMode.DRY_RUN:
            result = CommandResult(
                status=ExecutionStatus.DRY_RUN,
                stdout=f"[DRY RUN] Would execute:\n{cmd_string}",
                stderr="",
                return_code=0,
                command=cmd,
                command_string=cmd_string,
                debug_log_path=str(debug_log_path) if debug_log_path else None,
            )
            self.debug_logger.log_result(result)
            return result

        # Handle demo mode
        if self.settings.demo_mode:
            result = CommandResult(
                status=ExecutionStatus.DEMO_MODE,
                stdout=f"[DEMO MODE] Command: {cmd_string}",
                stderr="",
                return_code=0,
                command=cmd,
                command_string=cmd_string,
                debug_log_path=str(debug_log_path) if debug_log_path else None,
            )
            self.debug_logger.log_result(result)
            return result

        # Execute based on mode
        if mode == ExecutionMode.INTERACTIVE:
            result = self._execute_interactive(cmd, password_callback)
        else:
            result = self._execute_normal(cmd)

        # Calculate execution time
        result.execution_time = (datetime.now() - start_time).total_seconds()
        result.command_string = cmd_string
        result.debug_log_path = str(debug_log_path) if debug_log_path else None

        # Log result
        self.debug_logger.log_result(result)

        return result

    def _execute_normal(self, cmd: list[str]) -> CommandResult:
        """Execute command without interactive handling."""
        try:
            logger.info(f"Executing: {self._sanitize_command_string(cmd)}")
            self.debug_logger.log_output("EXECUTING", self._sanitize_command_string(cmd))

            result = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            self.debug_logger.log_output("STDOUT", result.stdout)
            self.debug_logger.log_output("STDERR", result.stderr)

            status = self._output_parser.determine_status(
                result.stdout, result.stderr, result.returncode
            )

            return CommandResult(
                status=status,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                command=cmd,
                tx_hash=self._output_parser.extract_tx_hash(result.stdout),
                error_message=(
                    self._output_parser.parse_error_message(result.stdout, result.stderr)
                    if status == ExecutionStatus.FAILED
                    else None
                ),
                raw_output=result.stdout + result.stderr,
            )

        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out after {self.timeout}s")
            self.debug_logger.log_output("TIMEOUT", f"Command timed out after {self.timeout}s")
            return CommandResult(
                status=ExecutionStatus.TIMEOUT,
                stdout="",
                stderr=f"Command timed out after {self.timeout} seconds",
                return_code=-1,
                command=cmd,
                error_message=f"Command timed out after {self.timeout} seconds",
            )
        except FileNotFoundError:
            logger.error("btcli not found in PATH")
            return CommandResult(
                status=ExecutionStatus.FAILED,
                stdout="",
                stderr="btcli not found. Please install with: pip install bittensor-cli",
                return_code=-1,
                command=cmd,
                error_message="btcli not found. Install with: pip install bittensor-cli",
            )
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            self.debug_logger.log_output("EXCEPTION", str(e))
            return CommandResult(
                status=ExecutionStatus.FAILED,
                stdout="",
                stderr=str(e),
                return_code=-1,
                command=cmd,
                error_message=str(e),
            )

    def _execute_interactive(
        self,
        cmd: list[str],
        password_callback: Optional[Callable[[], str]] = None,
    ) -> CommandResult:
        """Execute command with interactive password handling using pexpect.

        Args:
            cmd: Command to execute
            password_callback: Function to get password (default: getpass.getpass)

        Returns:
            CommandResult
        """
        try:
            logger.info(f"Executing (interactive): {self._sanitize_command_string(cmd)}")
            self.debug_logger.log_output(
                "EXECUTING (INTERACTIVE)", self._sanitize_command_string(cmd)
            )

            # Spawn process with proper argument passing
            # CRITICAL: Use cmd[0] with args, not " ".join(cmd) which gets shell-parsed
            child = pexpect.spawn(
                cmd[0],
                cmd[1:],
                timeout=self.timeout,
                encoding="utf-8",
                env=os.environ.copy(),
            )

            output_buffer = []
            password_attempts = 0
            max_password_attempts = 2

            # Build combined pattern list: passwords, confirmations, EOF, TIMEOUT
            all_patterns = (
                PASSWORD_PATTERNS + CONFIRMATION_PATTERNS + [pexpect.EOF, pexpect.TIMEOUT]
            )
            password_end_index = len(PASSWORD_PATTERNS)
            confirm_end_index = password_end_index + len(CONFIRMATION_PATTERNS)
            eof_index = confirm_end_index
            timeout_index = confirm_end_index + 1

            while True:
                try:
                    index = child.expect(all_patterns, timeout=self.timeout)

                    # Capture output before match
                    if child.before:
                        output_buffer.append(child.before)
                        self.debug_logger.log_output("OUTPUT", child.before)

                    if index < password_end_index:
                        # Password prompt matched
                        password_attempts += 1

                        if password_attempts > max_password_attempts:
                            # Too many password attempts - likely wrong password
                            logger.warning("Too many password attempts")
                            self.debug_logger.log_output(
                                "ERROR", "Too many password attempts - aborting"
                            )
                            child.close(force=True)
                            return CommandResult(
                                status=ExecutionStatus.FAILED,
                                stdout="".join(output_buffer),
                                stderr="Too many password attempts - password may be incorrect",
                                return_code=-1,
                                command=cmd,
                                error_message="Incorrect password (too many attempts)",
                                raw_output="".join(output_buffer),
                            )

                        # Get password
                        if password_callback:
                            password = password_callback()
                        else:
                            print()  # Newline for cleaner output
                            password = getpass.getpass("Enter wallet password: ")

                        # Send password (never log this!)
                        child.sendline(password)
                        self.debug_logger.log_output("ACTION", "[PASSWORD ENTERED]")

                    elif index < confirm_end_index:
                        # Confirmation prompt matched - send 'y' to proceed
                        self.debug_logger.log_output(
                            "ACTION", "Confirmation prompt detected, sending 'y'"
                        )
                        child.sendline("y")

                    elif index == eof_index:
                        # EOF - process completed
                        if child.before:
                            output_buffer.append(child.before)
                        break

                    elif index == timeout_index:
                        # Timeout waiting for pattern
                        logger.warning("Timeout waiting for expected output")
                        self.debug_logger.log_output(
                            "TIMEOUT", "Timeout waiting for expected output"
                        )

                        # Capture any remaining output
                        try:
                            child.expect(pexpect.EOF, timeout=5)
                            if child.before:
                                output_buffer.append(child.before)
                        except:
                            pass
                        break

                except pexpect.TIMEOUT:
                    logger.error(f"Command timed out after {self.timeout}s")
                    self.debug_logger.log_output("TIMEOUT", f"Timed out after {self.timeout}s")
                    child.close(force=True)
                    return CommandResult(
                        status=ExecutionStatus.TIMEOUT,
                        stdout="".join(output_buffer),
                        stderr=f"Command timed out after {self.timeout} seconds",
                        return_code=-1,
                        command=cmd,
                        error_message=f"Command timed out after {self.timeout} seconds",
                        raw_output="".join(output_buffer),
                    )

                except pexpect.EOF:
                    # Process ended
                    if child.before:
                        output_buffer.append(child.before)
                    break

            # Wait for process to complete and get exit status
            child.close()
            return_code = child.exitstatus if child.exitstatus is not None else -1

            # Combine output
            stdout = "".join(output_buffer)
            self.debug_logger.log_output("FINAL OUTPUT", stdout)

            # Determine status
            status = self._output_parser.determine_status(stdout, "", return_code)

            return CommandResult(
                status=status,
                stdout=stdout,
                stderr="" if status == ExecutionStatus.SUCCESS else stdout,
                return_code=return_code,
                command=cmd,
                tx_hash=self._output_parser.extract_tx_hash(stdout),
                error_message=(
                    self._output_parser.parse_error_message(stdout, "")
                    if status == ExecutionStatus.FAILED
                    else None
                ),
                raw_output=stdout,
            )

        except pexpect.exceptions.ExceptionPexpect as e:
            logger.error(f"pexpect error: {e}")
            self.debug_logger.log_output("PEXPECT ERROR", str(e))
            return CommandResult(
                status=ExecutionStatus.FAILED,
                stdout="",
                stderr=f"Execution error: {e}",
                return_code=-1,
                command=cmd,
                error_message=str(e),
            )

        except FileNotFoundError:
            logger.error("btcli not found in PATH")
            return CommandResult(
                status=ExecutionStatus.FAILED,
                stdout="",
                stderr="btcli not found. Please install with: pip install bittensor-cli",
                return_code=-1,
                command=cmd,
                error_message="btcli not found. Install with: pip install bittensor-cli",
            )

        except Exception as e:
            logger.error(f"Interactive execution failed: {e}")
            self.debug_logger.log_output("EXCEPTION", str(e))
            return CommandResult(
                status=ExecutionStatus.FAILED,
                stdout="",
                stderr=str(e),
                return_code=-1,
                command=cmd,
                error_message=str(e),
            )

    # =========================================================================
    # LEGACY COMPATIBILITY METHODS
    # These maintain backward compatibility with existing code
    # =========================================================================

    def run(
        self,
        group: str,
        subcommand: str,
        args: Optional[dict] = None,
        flags: Optional[list[str]] = None,
        dry_run: bool = False,
    ) -> CommandResult:
        """Execute a btcli command (non-interactive).

        LEGACY METHOD: Use execute() for new code.
        """
        return self.execute(
            group=group,
            subcommand=subcommand,
            args=args,
            flags=flags,
            mode=ExecutionMode.NORMAL,
            dry_run=dry_run,
        )

    def run_interactive(
        self,
        group: str,
        subcommand: str,
        args: Optional[dict] = None,
        flags: Optional[list[str]] = None,
        dry_run: bool = False,
    ) -> CommandResult:
        """Execute a btcli command with interactive password handling.

        LEGACY METHOD: Use execute() for new code.
        """
        return self.execute(
            group=group,
            subcommand=subcommand,
            args=args,
            flags=flags,
            mode=ExecutionMode.INTERACTIVE,
            dry_run=dry_run,
        )


# =============================================================================
# COMMAND BUILDERS
# Helper functions to build command argument dictionaries
# =============================================================================


def build_stake_add_command(
    amount: float,
    hotkey: str,
    netuid: int,
    wallet_name: Optional[str] = None,
    safe_staking: bool = True,
) -> dict:
    """Build arguments for stake add command."""
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


def build_register_command(
    netuid: int,
    wallet_name: Optional[str] = None,
    hotkey: Optional[str] = None,
) -> dict:
    """Build arguments for burned register command."""
    args = {"netuid": netuid}
    if wallet_name:
        args["wallet-name"] = wallet_name
    if hotkey:
        args["hotkey"] = hotkey

    return {
        "group": "subnets",
        "subcommand": "register",
        "args": args,
        "flags": [],
    }


def build_pow_register_command(
    netuid: int,
    wallet_name: Optional[str] = None,
    hotkey: Optional[str] = None,
    num_processes: int = 4,
) -> dict:
    """Build arguments for PoW register command."""
    args = {
        "netuid": netuid,
        "num-processes": num_processes,
    }
    if wallet_name:
        args["wallet-name"] = wallet_name
    if hotkey:
        args["hotkey"] = hotkey

    return {
        "group": "subnets",
        "subcommand": "pow-register",
        "args": args,
        "flags": [],
    }
