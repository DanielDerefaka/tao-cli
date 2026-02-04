"""Tests for the btcli executor module.

Tests cover:
- OutputParser: status determination, tx hash extraction, error parsing
- CommandResult: properties and serialization
- SecureDebugLogger: password redaction
- BtcliExecutor: command building, validation, dry-run mode
"""

import re
from unittest.mock import MagicMock, patch

import pytest

from taox.commands.executor import (
    FAILURE_PATTERNS,
    PASSWORD_PATTERNS,
    SUCCESS_PATTERNS,
    TX_HASH_PATTERN,
    BtcliExecutor,
    CommandResult,
    ExecutionMode,
    ExecutionStatus,
    OutputParser,
    SecureDebugLogger,
    build_balance_command,
    build_metagraph_command,
    build_register_command,
    build_stake_add_command,
    build_stake_remove_command,
    build_transfer_command,
)

# =============================================================================
# OutputParser Tests
# =============================================================================


class TestOutputParserDetermineStatus:
    """Test OutputParser.determine_status with various btcli outputs."""

    def test_success_with_checkmark(self):
        """Detect success from ✅ emoji."""
        stdout = "Transfer complete ✅\nBlock: 12345"
        status = OutputParser.determine_status(stdout, "", 0)
        assert status == ExecutionStatus.SUCCESS

    def test_success_with_finalized(self):
        """Detect success from 'Finalized' keyword."""
        stdout = "Transaction Finalized\nBlock hash: 0xabc123"
        status = OutputParser.determine_status(stdout, "", 0)
        assert status == ExecutionStatus.SUCCESS

    def test_success_with_extrinsic_submitted(self):
        """Detect success from 'Extrinsic submitted'."""
        stdout = "Extrinsic submitted successfully\nHash: 0xdef456"
        status = OutputParser.determine_status(stdout, "", 0)
        assert status == ExecutionStatus.SUCCESS

    def test_failure_with_error_emoji(self):
        """Detect failure from ❌ emoji."""
        stdout = "Transaction failed ❌"
        status = OutputParser.determine_status(stdout, "", 1)
        assert status == ExecutionStatus.FAILED

    def test_failure_with_insufficient_balance(self):
        """Detect failure from 'insufficient balance'."""
        stdout = "Error: Insufficient balance to complete transaction"
        status = OutputParser.determine_status(stdout, "", 1)
        assert status == ExecutionStatus.FAILED

    def test_failure_with_invalid_address(self):
        """Detect failure from 'invalid address'."""
        stdout = "Error: Invalid destination address"
        status = OutputParser.determine_status(stdout, "", 1)
        assert status == ExecutionStatus.FAILED

    def test_failure_from_nonzero_return_code(self):
        """Non-zero return code indicates failure."""
        stdout = "Some output without clear indicators"
        status = OutputParser.determine_status(stdout, "", 1)
        assert status == ExecutionStatus.FAILED

    def test_success_from_zero_return_code_no_indicators(self):
        """Zero return code with no indicators assumes success."""
        stdout = "Command completed\n"
        status = OutputParser.determine_status(stdout, "", 0)
        assert status == ExecutionStatus.SUCCESS

    def test_stderr_failure_detection(self):
        """Failure detected in stderr."""
        stderr = "Error: Connection refused"
        status = OutputParser.determine_status("", stderr, 1)
        assert status == ExecutionStatus.FAILED

    def test_combined_output_failure(self):
        """Failure indicator in combined stdout+stderr."""
        stdout = "Processing..."
        stderr = "failed to connect"
        status = OutputParser.determine_status(stdout, stderr, 1)
        assert status == ExecutionStatus.FAILED

    def test_unknown_status_negative_return(self):
        """Negative return code without indicators returns UNKNOWN."""
        stdout = "Ambiguous output"
        status = OutputParser.determine_status(stdout, "", -1)
        assert status == ExecutionStatus.UNKNOWN

    def test_cancelled_detection(self):
        """Detect cancelled status."""
        stdout = "Operation cancelled by user"
        status = OutputParser.determine_status(stdout, "", 1)
        assert status == ExecutionStatus.FAILED  # Cancelled maps to failed


class TestOutputParserExtractTxHash:
    """Test OutputParser.extract_tx_hash."""

    def test_extract_hash_with_0x_prefix(self):
        """Extract hash with 0x prefix."""
        output = "Block hash: 0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        result = OutputParser.extract_tx_hash(output)
        assert result == "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"

    def test_extract_hash_without_prefix(self):
        """Extract hash without 0x prefix."""
        output = "Hash: 1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        result = OutputParser.extract_tx_hash(output)
        assert result == "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"

    def test_no_hash_in_output(self):
        """Return None when no hash present."""
        output = "Transaction completed without hash"
        result = OutputParser.extract_tx_hash(output)
        assert result is None

    def test_hash_in_multiline_output(self):
        """Extract hash from multiline output."""
        output = """
        Transaction submitted
        Waiting for confirmation...
        ✅ Success!
        Block hash: 0xaabbccdd11223344556677889900aabbccdd11223344556677889900aabbccdd
        Block number: 12345
        """
        result = OutputParser.extract_tx_hash(output)
        assert result == "0xaabbccdd11223344556677889900aabbccdd11223344556677889900aabbccdd"

    def test_first_hash_returned(self):
        """Returns first hash found in output."""
        output = """
        Extrinsic hash: 0x1111111111111111111111111111111111111111111111111111111111111111
        Block hash: 0x2222222222222222222222222222222222222222222222222222222222222222
        """
        result = OutputParser.extract_tx_hash(output)
        assert result == "0x1111111111111111111111111111111111111111111111111111111111111111"


class TestOutputParserParseErrorMessage:
    """Test OutputParser.parse_error_message."""

    def test_parse_insufficient_balance(self):
        """Parse insufficient balance error."""
        stdout = "Error: Account has insufficient balance for transfer"
        result = OutputParser.parse_error_message(stdout, "")
        assert result == "Insufficient balance for this transaction"

    def test_parse_invalid_address(self):
        """Parse invalid address error."""
        stdout = "Invalid address format provided"
        result = OutputParser.parse_error_message(stdout, "")
        assert result == "Invalid destination address"

    def test_parse_password_incorrect(self):
        """Parse password error."""
        stdout = "Decryption failed: password incorrect"
        result = OutputParser.parse_error_message(stdout, "")
        assert result == "Incorrect wallet password"

    def test_parse_connection_refused(self):
        """Parse connection error."""
        stderr = "ConnectionRefusedError: Connection refused by server"
        result = OutputParser.parse_error_message("", stderr)
        assert result == "Cannot connect to network"

    def test_parse_timeout(self):
        """Parse timeout error."""
        stdout = "Operation timed out after 120 seconds"
        result = OutputParser.parse_error_message(stdout, "")
        assert result == "Operation timed out"

    def test_parse_wallet_not_found(self):
        """Parse wallet not found error."""
        stderr = "Error: No wallet found at path"
        result = OutputParser.parse_error_message("", stderr)
        assert result == "Wallet not found"

    def test_fallback_to_stderr_first_line(self):
        """Falls back to first line of stderr."""
        stderr = "Unknown error occurred\nMore details here"
        result = OutputParser.parse_error_message("", stderr)
        assert result == "Unknown error occurred"

    def test_none_for_empty_output(self):
        """Returns None for empty output."""
        result = OutputParser.parse_error_message("", "")
        assert result is None


# =============================================================================
# CommandResult Tests
# =============================================================================


class TestCommandResult:
    """Test CommandResult dataclass."""

    def test_success_property_true_for_success(self):
        """success property returns True for SUCCESS status."""
        result = CommandResult(
            status=ExecutionStatus.SUCCESS,
            stdout="Done",
            stderr="",
            return_code=0,
            command=["btcli", "test"],
        )
        assert result.success is True

    def test_success_property_true_for_dry_run(self):
        """success property returns True for DRY_RUN status."""
        result = CommandResult(
            status=ExecutionStatus.DRY_RUN,
            stdout="[DRY RUN]",
            stderr="",
            return_code=0,
            command=["btcli", "test"],
        )
        assert result.success is True

    def test_success_property_true_for_demo_mode(self):
        """success property returns True for DEMO_MODE status."""
        result = CommandResult(
            status=ExecutionStatus.DEMO_MODE,
            stdout="[DEMO]",
            stderr="",
            return_code=0,
            command=["btcli", "test"],
        )
        assert result.success is True

    def test_success_property_false_for_failed(self):
        """success property returns False for FAILED status."""
        result = CommandResult(
            status=ExecutionStatus.FAILED,
            stdout="",
            stderr="Error",
            return_code=1,
            command=["btcli", "test"],
        )
        assert result.success is False

    def test_output_property_returns_stdout_on_success(self):
        """output property returns stdout when successful."""
        result = CommandResult(
            status=ExecutionStatus.SUCCESS,
            stdout="Success output",
            stderr="Some stderr",
            return_code=0,
            command=["btcli", "test"],
        )
        assert result.output == "Success output"

    def test_output_property_returns_stderr_on_failure(self):
        """output property returns stderr when failed."""
        result = CommandResult(
            status=ExecutionStatus.FAILED,
            stdout="",
            stderr="Error output",
            return_code=1,
            command=["btcli", "test"],
        )
        assert result.output == "Error output"

    def test_to_dict(self):
        """to_dict serializes correctly."""
        result = CommandResult(
            status=ExecutionStatus.SUCCESS,
            stdout="Done",
            stderr="",
            return_code=0,
            command=["btcli", "wallet", "balance"],
            command_string="btcli wallet balance",
            execution_time=1.5,
            tx_hash="0xabc123",
            error_message=None,
        )
        d = result.to_dict()
        assert d["status"] == "success"
        assert d["success"] is True
        assert d["return_code"] == 0
        assert d["execution_time"] == 1.5
        assert d["tx_hash"] == "0xabc123"
        assert d["command_string"] == "btcli wallet balance"


# =============================================================================
# SecureDebugLogger Tests
# =============================================================================


class TestSecureDebugLogger:
    """Test SecureDebugLogger password redaction."""

    def test_sanitize_password_keyword(self):
        """Redacts password values."""
        logger = SecureDebugLogger(enabled=True)
        text = "password=mysecretpassword123"
        result = logger._sanitize(text)
        assert "mysecretpassword123" not in result
        assert "[REDACTED]" in result

    def test_sanitize_mnemonic(self):
        """Redacts mnemonic phrases."""
        logger = SecureDebugLogger(enabled=True)
        text = "mnemonic: word1 word2 word3 word4"
        result = logger._sanitize(text)
        assert "word1" not in result
        assert "[REDACTED]" in result

    def test_sanitize_api_key(self):
        """Redacts API keys."""
        logger = SecureDebugLogger(enabled=True)
        text = "api_key=sk-abc123xyz789"
        result = logger._sanitize(text)
        assert "sk-abc123xyz789" not in result
        assert "[REDACTED]" in result

    def test_sanitize_hex_key(self):
        """Redacts 64-char hex strings (private keys)."""
        logger = SecureDebugLogger(enabled=True)
        text = "key: 1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        result = logger._sanitize(text)
        assert "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef" not in result
        assert "[REDACTED_KEY]" in result

    def test_disabled_logger_returns_none_for_path(self):
        """Disabled logger returns None for log path."""
        logger = SecureDebugLogger(enabled=False)
        path = logger.start_command_log(["btcli", "test"], "btcli test")
        assert path is None

    def test_enabled_logger_creates_log_file(self, tmp_path):
        """Enabled logger creates log file."""
        logger = SecureDebugLogger(enabled=True, log_dir=tmp_path)
        path = logger.start_command_log(["btcli", "wallet", "balance"], "btcli wallet balance")
        assert path is not None
        assert path.exists()
        assert "wallet_balance" in path.name


# =============================================================================
# BtcliExecutor Tests
# =============================================================================


class TestBtcliExecutorCommandValidation:
    """Test command validation."""

    def test_validate_allowed_command(self):
        """Validates allowed commands."""
        executor = BtcliExecutor()
        assert executor._validate_command("wallet", "balance") is True
        assert executor._validate_command("stake", "add") is True
        assert executor._validate_command("subnets", "metagraph") is True

    def test_reject_disallowed_command(self):
        """Rejects commands not in whitelist."""
        executor = BtcliExecutor()
        assert executor._validate_command("wallet", "dangerous-command") is False
        assert executor._validate_command("unknown", "command") is False

    def test_execute_returns_error_for_invalid_command(self):
        """Execute returns failure for invalid command."""
        executor = BtcliExecutor()
        result = executor.execute("wallet", "not-allowed")
        assert result.status == ExecutionStatus.FAILED
        assert "not allowed" in result.error_message.lower()


class TestBtcliExecutorCommandBuilding:
    """Test command building."""

    def test_build_basic_command(self):
        """Build basic command."""
        executor = BtcliExecutor(network="finney")
        cmd = executor._build_command("wallet", "balance", args=None, flags=None)
        assert cmd == ["btcli", "wallet", "balance", "--network", "finney"]

    def test_build_command_with_args(self):
        """Build command with arguments."""
        executor = BtcliExecutor(network="test")
        cmd = executor._build_command(
            "wallet", "transfer", args={"amount": 10.5, "dest": "5Abc123"}, flags=None
        )
        assert "--amount" in cmd
        assert "10.5" in cmd
        assert "--dest" in cmd
        assert "5Abc123" in cmd

    def test_build_command_with_flags(self):
        """Build command with boolean flags."""
        executor = BtcliExecutor(network="finney")
        cmd = executor._build_command("wallet", "balance", args=None, flags=["all", "json-output"])
        assert "--all" in cmd
        assert "--json-output" in cmd

    def test_build_command_skips_none_values(self):
        """Build command skips None argument values."""
        executor = BtcliExecutor()
        cmd = executor._build_command(
            "wallet", "balance", args={"wallet-name": None, "format": "table"}, flags=None
        )
        assert "--wallet-name" not in cmd
        assert "--format" in cmd


class TestBtcliExecutorDryRun:
    """Test dry-run mode."""

    def test_dry_run_mode_parameter(self):
        """Dry run via mode parameter."""
        executor = BtcliExecutor()
        result = executor.execute("wallet", "balance", mode=ExecutionMode.DRY_RUN)
        assert result.status == ExecutionStatus.DRY_RUN
        assert result.success is True
        assert "[DRY RUN]" in result.stdout

    def test_dry_run_flag_parameter(self):
        """Dry run via dry_run flag."""
        executor = BtcliExecutor()
        result = executor.execute("wallet", "balance", dry_run=True)
        assert result.status == ExecutionStatus.DRY_RUN

    def test_dry_run_shows_command(self):
        """Dry run output shows the command."""
        executor = BtcliExecutor(network="finney")
        result = executor.execute("stake", "add", args={"amount": 10, "netuid": 1}, dry_run=True)
        assert "btcli stake add" in result.stdout
        assert "--amount" in result.stdout


class TestBtcliExecutorDemoMode:
    """Test demo mode integration."""

    @patch("taox.commands.executor.get_settings")
    def test_demo_mode_returns_demo_status(self, mock_settings):
        """Demo mode returns DEMO_MODE status."""
        mock_settings.return_value.demo_mode = True
        mock_settings.return_value.bittensor.network = "finney"

        executor = BtcliExecutor()
        result = executor.execute("wallet", "balance")

        assert result.status == ExecutionStatus.DEMO_MODE
        assert result.success is True


# =============================================================================
# Command Builder Tests
# =============================================================================


class TestCommandBuilders:
    """Test command builder helper functions."""

    def test_build_stake_add_command(self):
        """Build stake add command."""
        cmd = build_stake_add_command(
            amount=10.5, hotkey="5Abc123", netuid=1, wallet_name="default", safe_staking=True
        )
        assert cmd["group"] == "stake"
        assert cmd["subcommand"] == "add"
        assert cmd["args"]["amount"] == 10.5
        assert cmd["args"]["include-hotkeys"] == "5Abc123"
        assert cmd["args"]["netuid"] == 1
        assert cmd["args"]["wallet-name"] == "default"
        assert "safe" in cmd["flags"]

    def test_build_stake_remove_command(self):
        """Build stake remove command."""
        cmd = build_stake_remove_command(
            amount=5.0,
            hotkey="5Xyz789",
            netuid=18,
        )
        assert cmd["group"] == "stake"
        assert cmd["subcommand"] == "remove"
        assert cmd["args"]["amount"] == 5.0
        assert cmd["args"]["hotkey"] == "5Xyz789"
        assert cmd["args"]["netuid"] == 18

    def test_build_transfer_command(self):
        """Build transfer command."""
        cmd = build_transfer_command(amount=25.0, destination="5Dest456", wallet_name="mywallet")
        assert cmd["group"] == "wallet"
        assert cmd["subcommand"] == "transfer"
        assert cmd["args"]["amount"] == 25.0
        assert cmd["args"]["dest"] == "5Dest456"
        assert cmd["args"]["wallet-name"] == "mywallet"

    def test_build_balance_command(self):
        """Build balance command."""
        cmd = build_balance_command(all_wallets=True)
        assert cmd["group"] == "wallet"
        assert cmd["subcommand"] == "balance"
        assert "all" in cmd["flags"]

    def test_build_metagraph_command(self):
        """Build metagraph command."""
        cmd = build_metagraph_command(netuid=1, json_output=True)
        assert cmd["group"] == "subnets"
        assert cmd["subcommand"] == "metagraph"
        assert cmd["args"]["netuid"] == 1
        assert "json-output" in cmd["flags"]

    def test_build_register_command(self):
        """Build register command."""
        cmd = build_register_command(netuid=18, wallet_name="myvalidator", hotkey="miner1")
        assert cmd["group"] == "subnets"
        assert cmd["subcommand"] == "register"
        assert cmd["args"]["netuid"] == 18
        assert cmd["args"]["wallet-name"] == "myvalidator"
        assert cmd["args"]["hotkey"] == "miner1"


# =============================================================================
# Pattern Tests
# =============================================================================


class TestPasswordPatterns:
    """Test password detection patterns."""

    @pytest.mark.parametrize(
        "prompt",
        [
            "Enter your coldkey password:",
            "Enter the password to unlock your coldkey",
            "Unlock your coldkey:",
            "Decrypting coldkey...",
            "Enter your hotkey password:",
            "Unlock your hotkey:",
            "Enter password:",
            "Password:",
            "password:",
            "Enter the password to confirm:",
        ],
    )
    def test_password_prompt_detected(self, prompt):
        """Each password pattern matches expected prompts."""
        matched = any(re.search(pattern, prompt, re.IGNORECASE) for pattern in PASSWORD_PATTERNS)
        assert matched, f"Pattern should match: {prompt}"


class TestSuccessPatterns:
    """Test success detection patterns."""

    @pytest.mark.parametrize(
        "output",
        [
            "Transfer complete ✅",
            "Success: Transaction finalized",
            "Operation successful",
            "Successfully staked 10 TAO",
            "Finalized block #123456",
            "Transaction submitted to network",
            "Extrinsic submitted",
            "Block hash: 0xabc123",
        ],
    )
    def test_success_indicator_detected(self, output):
        """Each success pattern matches expected output."""
        matched = any(re.search(pattern, output, re.IGNORECASE) for pattern in SUCCESS_PATTERNS)
        assert matched, f"Pattern should match: {output}"


class TestFailurePatterns:
    """Test failure detection patterns."""

    @pytest.mark.parametrize(
        "output",
        [
            "Transaction failed ❌",
            "Error: Something went wrong",
            "error connecting to node",
            "Failed to submit extrinsic",
            "Failure: Invalid signature",
            "Insufficient balance",
            "Address not found",
            "Invalid netuid specified",
            "Permission denied",
            "Request rejected by validator",
            "Operation cancelled",
            "Abort: User cancelled",
        ],
    )
    def test_failure_indicator_detected(self, output):
        """Each failure pattern matches expected output."""
        matched = any(re.search(pattern, output, re.IGNORECASE) for pattern in FAILURE_PATTERNS)
        assert matched, f"Pattern should match: {output}"


class TestTxHashPattern:
    """Test transaction hash pattern."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            (
                "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
                "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            ),
            (
                "Hash: abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
                "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            ),
            (
                "Block 0xAAAABBBBCCCCDDDD1111222233334444555566667777888899990000AAAABBBB",
                "0xAAAABBBBCCCCDDDD1111222233334444555566667777888899990000AAAABBBB",
            ),
        ],
    )
    def test_tx_hash_extracted(self, text, expected):
        """TX hash pattern extracts correct hash."""
        match = TX_HASH_PATTERN.search(text)
        assert match is not None
        assert match.group(0) == expected

    def test_no_match_for_short_hex(self):
        """Short hex strings don't match."""
        match = TX_HASH_PATTERN.search("0xabcd1234")
        assert match is None


# =============================================================================
# Integration-style Mock Tests
# =============================================================================


class TestExecutorWithMockedBtcli:
    """Test executor with mocked subprocess calls.

    Note: These tests mock settings to disable demo_mode.
    """

    def _mock_settings(self):
        """Create a mock settings object with demo_mode=False."""
        mock = MagicMock()
        mock.demo_mode = False
        mock.bittensor.network = "finney"
        mock.bittensor.default_wallet = "default"
        mock.bittensor.default_hotkey = "default"
        return mock

    @patch("taox.commands.executor.get_settings")
    @patch("subprocess.run")
    def test_normal_execution_success(self, mock_run, mock_get_settings):
        """Normal execution parses successful output."""
        mock_get_settings.return_value = self._mock_settings()
        mock_run.return_value = MagicMock(stdout="Balance: 100.5 TAO ✅", stderr="", returncode=0)

        executor = BtcliExecutor()
        result = executor.execute("wallet", "balance", mode=ExecutionMode.NORMAL)

        assert result.status == ExecutionStatus.SUCCESS
        assert "100.5 TAO" in result.stdout

    @patch("taox.commands.executor.get_settings")
    @patch("subprocess.run")
    def test_normal_execution_failure(self, mock_run, mock_get_settings):
        """Normal execution detects failure."""
        mock_get_settings.return_value = self._mock_settings()
        mock_run.return_value = MagicMock(stdout="", stderr="Error: Wallet not found", returncode=1)

        executor = BtcliExecutor()
        result = executor.execute("wallet", "balance", mode=ExecutionMode.NORMAL)

        assert result.status == ExecutionStatus.FAILED
        assert result.error_message is not None

    @patch("taox.commands.executor.get_settings")
    @patch("subprocess.run")
    def test_normal_execution_extracts_tx_hash(self, mock_run, mock_get_settings):
        """Normal execution extracts transaction hash."""
        mock_get_settings.return_value = self._mock_settings()
        mock_run.return_value = MagicMock(
            stdout="Transfer complete!\nBlock hash: 0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890\n✅",
            stderr="",
            returncode=0,
        )

        executor = BtcliExecutor()
        result = executor.execute(
            "wallet", "transfer", args={"amount": 10, "dest": "5Abc"}, mode=ExecutionMode.NORMAL
        )

        assert result.status == ExecutionStatus.SUCCESS
        assert (
            result.tx_hash == "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        )

    @patch("taox.commands.executor.get_settings")
    @patch("subprocess.run")
    def test_timeout_handling(self, mock_run, mock_get_settings):
        """Timeout is handled gracefully."""
        import subprocess

        mock_get_settings.return_value = self._mock_settings()
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["btcli"], timeout=120)

        executor = BtcliExecutor(timeout=120)
        result = executor.execute("wallet", "balance", mode=ExecutionMode.NORMAL)

        assert result.status == ExecutionStatus.TIMEOUT
        assert "timed out" in result.error_message.lower()

    @patch("taox.commands.executor.get_settings")
    @patch("subprocess.run")
    def test_btcli_not_found(self, mock_run, mock_get_settings):
        """Missing btcli handled gracefully."""
        mock_get_settings.return_value = self._mock_settings()
        mock_run.side_effect = FileNotFoundError("btcli not found")

        executor = BtcliExecutor()
        result = executor.execute("wallet", "balance", mode=ExecutionMode.NORMAL)

        assert result.status == ExecutionStatus.FAILED
        assert "not found" in result.error_message.lower()
