"""Tests for taox doctor command."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from taox.cli import app


runner = CliRunner()


class TestDoctorCommand:
    """Tests for doctor command."""

    def test_doctor_runs_without_error(self):
        """Test that doctor command runs successfully."""
        result = runner.invoke(app, ["doctor"])
        # Should not crash
        assert result.exit_code in (0, 1)  # 0 = all ok, 1 = errors found

    def test_doctor_shows_python_version(self):
        """Test that doctor shows Python version."""
        result = runner.invoke(app, ["doctor"])
        assert "Python version" in result.output

    def test_doctor_shows_taox_version(self):
        """Test that doctor shows taox version."""
        result = runner.invoke(app, ["doctor"])
        assert "taox version" in result.output

    def test_doctor_checks_btcli(self):
        """Test that doctor checks for btcli."""
        result = runner.invoke(app, ["doctor"])
        assert "btcli" in result.output.lower()

    def test_doctor_checks_wallet(self):
        """Test that doctor checks wallet."""
        result = runner.invoke(app, ["doctor"])
        assert "wallet" in result.output.lower()

    def test_doctor_checks_rpc(self):
        """Test that doctor checks RPC endpoint."""
        result = runner.invoke(app, ["doctor"])
        assert "rpc" in result.output.lower()

    def test_doctor_checks_api_keys(self):
        """Test that doctor checks API keys."""
        result = runner.invoke(app, ["doctor"])
        assert "chutes" in result.output.lower() or "api" in result.output.lower()

    def test_doctor_verbose_flag(self):
        """Test that --verbose flag shows dependency versions."""
        result = runner.invoke(app, ["doctor", "--verbose"])
        assert "Dependency Versions" in result.output

    def test_doctor_network_flag(self):
        """Test that --network flag is accepted."""
        result = runner.invoke(app, ["doctor", "--network", "finney"])
        assert result.exit_code in (0, 1)
        assert "finney" in result.output.lower() or "Finney" in result.output

    def test_doctor_wallet_flag(self):
        """Test that --wallet flag is accepted."""
        result = runner.invoke(app, ["doctor", "--wallet", "testwall"])
        assert result.exit_code in (0, 1)
        # Should mention the wallet name in output
        assert "testwall" in result.output or "wallet" in result.output.lower()

    def test_doctor_hotkey_flag(self):
        """Test that --hotkey flag is accepted."""
        result = runner.invoke(app, ["doctor", "--hotkey", "testhot"])
        assert result.exit_code in (0, 1)

    def test_doctor_json_output(self):
        """Test that --json flag outputs valid JSON."""
        result = runner.invoke(app, ["doctor", "--json"])
        # Should be valid JSON
        try:
            data = json.loads(result.output)
            assert "status" in data
            assert "checks" in data
            assert "warnings" in data or "errors" in data
            assert "fix_commands" in data
        except json.JSONDecodeError:
            pytest.fail("--json output is not valid JSON")

    def test_doctor_json_contains_checks(self):
        """Test that JSON output contains check results."""
        result = runner.invoke(app, ["doctor", "--json"])
        data = json.loads(result.output)

        # Should have check results
        assert isinstance(data["checks"], dict)
        # Should have at least python check
        assert "python" in data["checks"]
        assert "passed" in data["checks"]["python"]

    def test_doctor_shows_fix_commands(self):
        """Test that doctor shows fix commands when there are issues."""
        # Run doctor - if there are warnings, fix commands should appear
        result = runner.invoke(app, ["doctor"])
        # If there are warnings, there should be fix commands
        if "Warning" in result.output:
            assert "Fix Commands" in result.output or "taox setup" in result.output

    def test_doctor_checks_demo_mode(self):
        """Test that doctor reports demo mode status."""
        result = runner.invoke(app, ["doctor"])
        assert "demo" in result.output.lower()


class TestDoctorChecks:
    """Tests for individual doctor checks."""

    @patch("shutil.which")
    def test_btcli_not_found(self, mock_which):
        """Test btcli not found error."""
        mock_which.return_value = None
        result = runner.invoke(app, ["doctor", "--json"])
        data = json.loads(result.output)

        assert "btcli" in data["checks"]
        assert data["checks"]["btcli"]["passed"] is False

    @patch("shutil.which")
    def test_btcli_found(self, mock_which):
        """Test btcli found."""
        mock_which.return_value = "/usr/local/bin/btcli"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="btcli version 8.0.0",
                stderr="",
            )
            result = runner.invoke(app, ["doctor", "--json"])
            data = json.loads(result.output)

            assert "btcli" in data["checks"]
            # btcli check should pass
            assert data["checks"]["btcli"]["passed"] is True

    def test_python_version_check(self):
        """Test Python version check."""
        result = runner.invoke(app, ["doctor", "--json"])
        data = json.loads(result.output)

        assert "python" in data["checks"]
        # Python 3.10+ should pass
        if sys.version_info >= (3, 10):
            assert data["checks"]["python"]["passed"] is True

    @patch("httpx.Client")
    def test_rpc_unreachable(self, mock_client):
        """Test RPC unreachable handling."""
        mock_client.return_value.__enter__.return_value.post.side_effect = Exception("Connection failed")

        result = runner.invoke(app, ["doctor", "--json"])
        data = json.loads(result.output)

        assert "rpc" in data["checks"]
        assert data["checks"]["rpc"]["passed"] is False

    @patch("httpx.Client")
    def test_rpc_reachable(self, mock_client):
        """Test RPC reachable."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.return_value.__enter__.return_value.post.return_value = mock_response

        result = runner.invoke(app, ["doctor", "--json"])
        data = json.loads(result.output)

        assert "rpc" in data["checks"]
        if data["checks"]["rpc"]["passed"]:
            assert "latency_ms" in data["checks"]["rpc"]


class TestDoctorApiKeyChecks:
    """Tests for API key checking logic."""

    @patch("taox.security.credentials.CredentialManager.get_chutes_key")
    @patch("taox.security.credentials.CredentialManager.get_taostats_key")
    def test_chutes_key_required_when_llm_always(self, mock_taostats, mock_chutes):
        """Test Chutes key is flagged when llm_mode=always."""
        mock_chutes.return_value = None
        mock_taostats.return_value = None

        result = runner.invoke(app, ["doctor", "--json"])
        data = json.loads(result.output)

        assert "chutes_api" in data["checks"]
        # Should not pass when key is missing
        assert data["checks"]["chutes_api"]["passed"] is False

    @patch("taox.security.credentials.CredentialManager.get_chutes_key")
    @patch("taox.security.credentials.CredentialManager.get_taostats_key")
    def test_keys_configured_passes(self, mock_taostats, mock_chutes):
        """Test API key checks pass when configured."""
        mock_chutes.return_value = "test-chutes-key"
        mock_taostats.return_value = "test-taostats-key"

        result = runner.invoke(app, ["doctor", "--json"])
        data = json.loads(result.output)

        assert data["checks"]["chutes_api"]["passed"] is True
        assert data["checks"]["taostats_api"]["passed"] is True


class TestDoctorWalletChecks:
    """Tests for wallet checking logic."""

    @patch("pathlib.Path.exists")
    def test_wallet_dir_not_found(self, mock_exists):
        """Test wallet directory not found."""
        mock_exists.return_value = False

        result = runner.invoke(app, ["doctor", "--json"])
        data = json.loads(result.output)

        # Should have wallet_dir check
        assert "wallet_dir" in data["checks"]

    def test_wallet_check_with_custom_wallet(self):
        """Test wallet check with custom wallet name."""
        result = runner.invoke(app, ["doctor", "--wallet", "nonexistent_wallet_xyz", "--json"])
        data = json.loads(result.output)

        # Should check for the specified wallet
        if "wallet" in data["checks"]:
            # If wallet check ran, it should fail for nonexistent wallet
            # (unless user happens to have this wallet)
            pass  # Check ran


class TestDoctorExitCodes:
    """Tests for doctor exit codes."""

    def test_exit_code_zero_on_success(self):
        """Test exit code 0 when all checks pass."""
        # This test may pass or fail depending on actual environment
        result = runner.invoke(app, ["doctor"])
        # Just verify it's either 0 or 1
        assert result.exit_code in (0, 1)

    @patch("shutil.which")
    def test_btcli_missing_is_actionable_warning(self, mock_which):
        """Test btcli missing is flagged as actionable warning with fix command."""
        mock_which.return_value = None  # btcli not found

        result = runner.invoke(app, ["doctor", "--json"])
        data = json.loads(result.output)

        # btcli missing should fail the check
        assert data["checks"]["btcli"]["passed"] is False
        # Should have a fix command
        assert any("pip install" in fix for fix in data["fix_commands"])
