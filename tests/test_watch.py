"""Tests for watch and alerts."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from taox.cli import app
from taox.commands.watch import (
    AlertRule,
    AlertStore,
    AlertType,
    WatchRunner,
    create_price_alert,
    create_registration_alert,
    create_validator_alert,
    list_alerts,
)
from taox.data.taostats import PriceInfo, Subnet, Validator


runner = CliRunner()


@pytest.fixture
def temp_storage():
    """Create a temporary storage directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "alerts.json"


@pytest.fixture
def alert_store(temp_storage):
    """Create an alert store with temp storage."""
    return AlertStore(storage_path=temp_storage)


class TestAlertRule:
    """Tests for AlertRule dataclass."""

    def test_create_alert_rule(self):
        """Test creating an alert rule."""
        rule = AlertRule(
            id="test123",
            type=AlertType.PRICE_ABOVE,
            name="TAO above $500",
            threshold=500.0,
        )

        assert rule.id == "test123"
        assert rule.type == AlertType.PRICE_ABOVE
        assert rule.threshold == 500.0
        assert rule.enabled is True

    def test_to_dict(self):
        """Test converting rule to dict."""
        rule = AlertRule(
            id="test123",
            type=AlertType.PRICE_ABOVE,
            name="Test",
            threshold=500.0,
        )

        data = rule.to_dict()
        assert data["id"] == "test123"
        assert data["type"] == "price_above"
        assert data["threshold"] == 500.0

    def test_from_dict(self):
        """Test creating rule from dict."""
        data = {
            "id": "test123",
            "type": "price_above",
            "name": "Test",
            "threshold": 500.0,
        }

        rule = AlertRule.from_dict(data)
        assert rule.id == "test123"
        assert rule.type == AlertType.PRICE_ABOVE


class TestAlertStore:
    """Tests for AlertStore."""

    def test_add_and_get_rules(self, alert_store):
        """Test adding and retrieving rules."""
        rule = AlertRule(
            id="test1",
            type=AlertType.PRICE_ABOVE,
            name="Test",
            threshold=500.0,
        )

        alert_store.add_rule(rule)
        rules = alert_store.get_rules()

        assert len(rules) == 1
        assert rules[0].id == "test1"

    def test_remove_rule(self, alert_store):
        """Test removing a rule."""
        rule = AlertRule(
            id="test1",
            type=AlertType.PRICE_ABOVE,
            name="Test",
            threshold=500.0,
        )

        alert_store.add_rule(rule)
        result = alert_store.remove_rule("test1")

        assert result is True
        assert len(alert_store.get_rules()) == 0

    def test_remove_nonexistent_rule(self, alert_store):
        """Test removing a nonexistent rule."""
        result = alert_store.remove_rule("nonexistent")
        assert result is False

    def test_get_enabled_only(self, alert_store):
        """Test filtering to enabled rules only."""
        rule1 = AlertRule(id="e1", type=AlertType.PRICE_ABOVE, name="Enabled", threshold=500, enabled=True)
        rule2 = AlertRule(id="d1", type=AlertType.PRICE_BELOW, name="Disabled", threshold=400, enabled=False)

        alert_store.add_rule(rule1)
        alert_store.add_rule(rule2)

        all_rules = alert_store.get_rules(enabled_only=False)
        enabled_rules = alert_store.get_rules(enabled_only=True)

        assert len(all_rules) == 2
        assert len(enabled_rules) == 1
        assert enabled_rules[0].id == "e1"

    def test_update_triggered(self, alert_store):
        """Test updating last triggered time."""
        rule = AlertRule(
            id="test1",
            type=AlertType.PRICE_ABOVE,
            name="Test",
            threshold=500.0,
        )

        alert_store.add_rule(rule)
        alert_store.update_triggered("test1")

        rules = alert_store.get_rules()
        assert rules[0].last_triggered is not None


class TestCreateAlertFunctions:
    """Tests for alert creation helper functions."""

    def test_create_price_alert_above(self):
        """Test creating price above alert."""
        rule = create_price_alert(500.0, above=True)

        assert rule.type == AlertType.PRICE_ABOVE
        assert rule.threshold == 500.0
        assert "above" in rule.name.lower()

    def test_create_price_alert_below(self):
        """Test creating price below alert."""
        rule = create_price_alert(400.0, above=False)

        assert rule.type == AlertType.PRICE_BELOW
        assert rule.threshold == 400.0
        assert "below" in rule.name.lower()

    def test_create_validator_alert(self):
        """Test creating validator alert."""
        rule = create_validator_alert(
            hotkey="5AAA111",
            name="Test Validator",
            netuid=1,
        )

        assert rule.type == AlertType.VALIDATOR_RANK_CHANGE
        assert rule.validator_hotkey == "5AAA111"
        assert rule.validator_name == "Test Validator"
        assert rule.netuid == 1

    def test_create_registration_alert(self):
        """Test creating registration alert."""
        rule = create_registration_alert(netuid=18, max_burn=1.5)

        assert rule.type == AlertType.REGISTRATION_OPEN
        assert rule.netuid == 18
        assert rule.threshold == 1.5


class TestWatchRunner:
    """Tests for WatchRunner."""

    @pytest.fixture
    def mock_taostats(self):
        """Create mock TaostatsClient."""
        mock = AsyncMock()
        mock.get_price = AsyncMock(return_value=PriceInfo(usd=450.0, change_24h=2.5))
        mock.get_validators = AsyncMock(return_value=[])
        mock.get_subnet = AsyncMock(return_value=Subnet(
            netuid=1, name="Test", emission=0.1, tempo=360,
            difficulty=1000, burn_cost=1.0, total_stake=1000, validators=64
        ))
        return mock

    @pytest.fixture
    def watch_runner(self, mock_taostats, alert_store):
        """Create watch runner with mocks."""
        return WatchRunner(
            taostats=mock_taostats,
            alert_store=alert_store,
            poll_interval=1,
            alert_cooldown=0,  # No cooldown for tests
        )

    @pytest.mark.asyncio
    async def test_check_price_alert_triggers(self, watch_runner, alert_store, mock_taostats):
        """Test price alert triggers when condition met."""
        # Add a price alert for above $400 (current price is $450)
        rule = create_price_alert(400.0, above=True)
        alert_store.add_rule(rule)

        alerts = await watch_runner.check_price_alerts(alert_store.get_rules())

        assert len(alerts) == 1
        assert "450" in alerts[0].message or "$450" in alerts[0].message

    @pytest.mark.asyncio
    async def test_check_price_alert_no_trigger(self, watch_runner, alert_store, mock_taostats):
        """Test price alert doesn't trigger when condition not met."""
        # Add a price alert for above $500 (current price is $450)
        rule = create_price_alert(500.0, above=True)
        alert_store.add_rule(rule)

        alerts = await watch_runner.check_price_alerts(alert_store.get_rules())

        assert len(alerts) == 0

    @pytest.mark.asyncio
    async def test_check_price_below_triggers(self, watch_runner, alert_store, mock_taostats):
        """Test price below alert triggers."""
        # Add a price alert for below $500 (current price is $450)
        rule = create_price_alert(500.0, above=False)
        alert_store.add_rule(rule)

        alerts = await watch_runner.check_price_alerts(alert_store.get_rules())

        assert len(alerts) == 1

    @pytest.mark.asyncio
    async def test_cooldown_prevents_repeated_alerts(self, mock_taostats, temp_storage):
        """Test cooldown prevents repeated alerts."""
        # Create store and runner with cooldown
        alert_store = AlertStore(storage_path=temp_storage)
        runner = WatchRunner(
            taostats=mock_taostats,
            alert_store=alert_store,
            poll_interval=1,
            alert_cooldown=300,  # 5 minute cooldown
        )

        rule = create_price_alert(400.0, above=True)
        alert_store.add_rule(rule)

        # First check should trigger
        alerts1 = await runner.check_price_alerts(alert_store.get_rules())
        assert len(alerts1) == 1

        # Second check should not trigger (cooldown)
        alerts2 = await runner.check_price_alerts(alert_store.get_rules())
        assert len(alerts2) == 0

    @pytest.mark.asyncio
    async def test_check_registration_alert(self, watch_runner, alert_store, mock_taostats):
        """Test registration alert."""
        rule = create_registration_alert(netuid=1, max_burn=2.0)  # Alert when burn <= 2
        alert_store.add_rule(rule)

        # Mock returns burn_cost=1.0, which is <= 2.0
        alerts = await watch_runner.check_registration_alerts(alert_store.get_rules())

        assert len(alerts) == 1

    def test_build_status_table(self, watch_runner):
        """Test building status table."""
        watch_runner._last_price = 450.0
        watch_runner._last_check = datetime.now()

        table = watch_runner.build_status_table()

        assert table is not None


class TestCLICommand:
    """Tests for CLI watch command."""

    def test_watch_command_exists(self):
        """Test that watch command exists."""
        result = runner.invoke(app, ["watch", "--help"])
        assert result.exit_code == 0
        assert "watch" in result.output.lower()

    def test_watch_list_empty(self):
        """Test listing alerts when none exist."""
        # Use a temp file that doesn't exist
        with patch("taox.commands.watch.AlertStore") as MockStore:
            MockStore.return_value.get_rules.return_value = []
            result = runner.invoke(app, ["watch", "--list"])
            assert result.exit_code == 0

    def test_watch_clear(self):
        """Test clearing alerts."""
        with patch("taox.commands.watch.clear_alerts") as mock_clear:
            mock_clear.return_value = 2
            result = runner.invoke(app, ["watch", "--clear"])
            assert result.exit_code == 0
            assert "2" in result.output


class TestAlertTypes:
    """Tests for alert type coverage."""

    def test_all_alert_types(self):
        """Test all alert types exist."""
        assert AlertType.PRICE_ABOVE
        assert AlertType.PRICE_BELOW
        assert AlertType.VALIDATOR_RANK_CHANGE
        assert AlertType.REGISTRATION_OPEN

    def test_alert_type_values(self):
        """Test alert type values are strings."""
        assert AlertType.PRICE_ABOVE.value == "price_above"
        assert AlertType.PRICE_BELOW.value == "price_below"
        assert AlertType.VALIDATOR_RANK_CHANGE.value == "validator_rank_change"
        assert AlertType.REGISTRATION_OPEN.value == "registration_open"
