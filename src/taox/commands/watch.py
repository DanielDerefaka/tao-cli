"""Watch and alerts for taox.

Provides long-running monitoring with alerts for:
- Price changes
- Validator status
- Registration windows
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

from rich import box
from rich.panel import Panel
from rich.table import Table

from taox.data.taostats import TaostatsClient
from taox.ui.console import console
from taox.ui.theme import Symbols, TaoxColors


class AlertType(Enum):
    """Types of alerts."""

    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    VALIDATOR_RANK_CHANGE = "validator_rank_change"
    REGISTRATION_OPEN = "registration_open"


@dataclass
class AlertRule:
    """An alert rule configuration."""

    id: str
    type: AlertType
    name: str
    threshold: float
    netuid: Optional[int] = None
    validator_hotkey: Optional[str] = None
    validator_name: Optional[str] = None
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_triggered: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dict for storage."""
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "threshold": self.threshold,
            "netuid": self.netuid,
            "validator_hotkey": self.validator_hotkey,
            "validator_name": self.validator_name,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_triggered": self.last_triggered,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AlertRule":
        """Create from dict."""
        return cls(
            id=data["id"],
            type=AlertType(data["type"]),
            name=data["name"],
            threshold=data["threshold"],
            netuid=data.get("netuid"),
            validator_hotkey=data.get("validator_hotkey"),
            validator_name=data.get("validator_name"),
            enabled=data.get("enabled", True),
            created_at=data.get("created_at", datetime.now().isoformat()),
            last_triggered=data.get("last_triggered"),
        )


@dataclass
class Alert:
    """A triggered alert."""

    rule: AlertRule
    message: str
    value: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class AlertStore:
    """Storage for alert rules."""

    def __init__(self, storage_path: Optional[Path] = None):
        """Initialize alert store."""
        if storage_path is None:
            storage_path = Path.home() / ".taox" / "alerts.json"

        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[AlertRule]:
        """Load alert rules."""
        if not self.storage_path.exists():
            return []

        try:
            with open(self.storage_path) as f:
                data = json.load(f)
            return [AlertRule.from_dict(r) for r in data.get("rules", [])]
        except (json.JSONDecodeError, KeyError):
            return []

    def _save(self, rules: list[AlertRule]) -> None:
        """Save alert rules."""
        data = {
            "last_updated": datetime.now().isoformat(),
            "rules": [r.to_dict() for r in rules],
        }
        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2)

    def add_rule(self, rule: AlertRule) -> None:
        """Add an alert rule."""
        rules = self._load()
        rules.append(rule)
        self._save(rules)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove an alert rule."""
        rules = self._load()
        original_len = len(rules)
        rules = [r for r in rules if r.id != rule_id]
        if len(rules) < original_len:
            self._save(rules)
            return True
        return False

    def get_rules(self, enabled_only: bool = True) -> list[AlertRule]:
        """Get all rules."""
        rules = self._load()
        if enabled_only:
            return [r for r in rules if r.enabled]
        return rules

    def update_triggered(self, rule_id: str) -> None:
        """Mark a rule as triggered."""
        rules = self._load()
        for rule in rules:
            if rule.id == rule_id:
                rule.last_triggered = datetime.now().isoformat()
                break
        self._save(rules)


class WatchRunner:
    """Long-running watch process."""

    def __init__(
        self,
        taostats: TaostatsClient,
        alert_store: AlertStore,
        poll_interval: int = 30,
        alert_cooldown: int = 300,  # 5 minutes between same alerts
    ):
        """Initialize watch runner."""
        self.taostats = taostats
        self.alert_store = alert_store
        self.poll_interval = poll_interval
        self.alert_cooldown = alert_cooldown
        self.running = False
        self.alerts_triggered: list[Alert] = []
        self._last_price: Optional[float] = None
        self._last_check: Optional[datetime] = None

    def _can_trigger(self, rule: AlertRule) -> bool:
        """Check if rule can trigger (cooldown check)."""
        if not rule.last_triggered:
            return True

        last = datetime.fromisoformat(rule.last_triggered)
        cooldown = timedelta(seconds=self.alert_cooldown)
        return datetime.now() - last > cooldown

    async def check_price_alerts(self, rules: list[AlertRule]) -> list[Alert]:
        """Check price alert rules."""
        alerts = []

        price_rules = [r for r in rules if r.type in (AlertType.PRICE_ABOVE, AlertType.PRICE_BELOW)]
        if not price_rules:
            return alerts

        price_info = await self.taostats.get_price()
        current_price = price_info.usd
        self._last_price = current_price

        for rule in price_rules:
            if not self._can_trigger(rule):
                continue

            triggered = False
            if rule.type == AlertType.PRICE_ABOVE and current_price >= rule.threshold:
                triggered = True
                message = f"TAO price ${current_price:.2f} >= ${rule.threshold:.2f}"
            elif rule.type == AlertType.PRICE_BELOW and current_price <= rule.threshold:
                triggered = True
                message = f"TAO price ${current_price:.2f} <= ${rule.threshold:.2f}"

            if triggered:
                alerts.append(Alert(rule=rule, message=message, value=current_price))
                self.alert_store.update_triggered(rule.id)

        return alerts

    async def check_validator_alerts(self, rules: list[AlertRule]) -> list[Alert]:
        """Check validator alert rules."""
        alerts = []

        validator_rules = [r for r in rules if r.type == AlertType.VALIDATOR_RANK_CHANGE]
        if not validator_rules:
            return alerts

        # Group by netuid
        by_netuid: dict[int, list[AlertRule]] = {}
        for rule in validator_rules:
            netuid = rule.netuid or 1
            by_netuid.setdefault(netuid, []).append(rule)

        for netuid, netuid_rules in by_netuid.items():
            validators = await self.taostats.get_validators(netuid=netuid, limit=50)
            validator_map = {v.hotkey: v for v in validators}

            for rule in netuid_rules:
                if not self._can_trigger(rule):
                    continue

                if rule.validator_hotkey in validator_map:
                    v = validator_map[rule.validator_hotkey]
                    # Check if rank changed significantly (more than threshold)
                    # For simplicity, we just report current rank
                    # In production, we'd track historical rank
                    message = f"{v.name or 'Validator'} on SN{netuid}: rank #{v.rank}, stake {v.stake:,.0f} τ"
                    alerts.append(Alert(rule=rule, message=message, value=v.rank))
                    self.alert_store.update_triggered(rule.id)

        return alerts

    async def check_registration_alerts(self, rules: list[AlertRule]) -> list[Alert]:
        """Check registration window alerts."""
        alerts = []

        reg_rules = [r for r in rules if r.type == AlertType.REGISTRATION_OPEN]
        if not reg_rules:
            return alerts

        # Group by netuid
        by_netuid: dict[int, list[AlertRule]] = {}
        for rule in reg_rules:
            netuid = rule.netuid or 1
            by_netuid.setdefault(netuid, []).append(rule)

        for netuid, netuid_rules in by_netuid.items():
            subnet = await self.taostats.get_subnet(netuid)
            if not subnet:
                continue

            burn_cost = subnet.burn_cost

            for rule in netuid_rules:
                if not self._can_trigger(rule):
                    continue

                # Alert if burn cost is below threshold
                if burn_cost <= rule.threshold:
                    message = f"SN{netuid} registration open: burn cost {burn_cost:.4f} τ <= {rule.threshold:.4f} τ"
                    alerts.append(Alert(rule=rule, message=message, value=burn_cost))
                    self.alert_store.update_triggered(rule.id)

        return alerts

    async def check_all_rules(self) -> list[Alert]:
        """Check all enabled rules and return triggered alerts."""
        rules = self.alert_store.get_rules(enabled_only=True)
        if not rules:
            return []

        all_alerts = []

        try:
            price_alerts = await self.check_price_alerts(rules)
            all_alerts.extend(price_alerts)
        except Exception as e:
            console.print(f"[error]Error checking price alerts: {e}[/error]")

        try:
            validator_alerts = await self.check_validator_alerts(rules)
            all_alerts.extend(validator_alerts)
        except Exception as e:
            console.print(f"[error]Error checking validator alerts: {e}[/error]")

        try:
            reg_alerts = await self.check_registration_alerts(rules)
            all_alerts.extend(reg_alerts)
        except Exception as e:
            console.print(f"[error]Error checking registration alerts: {e}[/error]")

        self._last_check = datetime.now()
        return all_alerts

    def display_alert(self, alert: Alert) -> None:
        """Display a triggered alert."""
        timestamp = datetime.fromisoformat(alert.timestamp).strftime("%H:%M:%S")
        console.print(f"[warning]{Symbols.WARN} [{timestamp}] {alert.message}[/warning]")

    def build_status_table(self) -> Table:
        """Build status table for live display."""
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("Key", style="muted")
        table.add_column("Value", style="info")

        # Last check time
        if self._last_check:
            last_str = self._last_check.strftime("%H:%M:%S")
            table.add_row("Last check", last_str)

        # Current price
        if self._last_price:
            table.add_row("TAO Price", f"${self._last_price:,.2f}")

        # Active rules
        rules = self.alert_store.get_rules(enabled_only=True)
        table.add_row("Active rules", str(len(rules)))

        # Alerts triggered this session
        table.add_row("Alerts triggered", str(len(self.alerts_triggered)))

        return table

    async def run(self, duration: Optional[int] = None) -> None:
        """Run the watch loop.

        Args:
            duration: Run for this many seconds (None = indefinitely)
        """
        self.running = True
        start_time = datetime.now()

        console.print(
            Panel(
                "[bold]taox Watch Mode[/bold]\n"
                f"Checking every {self.poll_interval}s | Press Ctrl+C to stop",
                box=box.ROUNDED,
                border_style="primary",
            )
        )
        console.print()

        # Initial check
        rules = self.alert_store.get_rules(enabled_only=True)
        if not rules:
            console.print("[warning]No alert rules configured.[/warning]")
            console.print("[muted]Use 'taox watch --price TAO:500' to add a price alert[/muted]")
            console.print()

        try:
            while self.running:
                # Check duration limit
                if duration and (datetime.now() - start_time).total_seconds() > duration:
                    break

                # Check rules
                alerts = await self.check_all_rules()

                # Display any triggered alerts
                for alert in alerts:
                    self.alerts_triggered.append(alert)
                    self.display_alert(alert)

                # Show status
                status_table = self.build_status_table()
                console.print(status_table)
                console.print(f"[muted]Next check in {self.poll_interval}s...[/muted]", end="\r")

                # Wait for next poll
                await asyncio.sleep(self.poll_interval)

                # Clear status line
                console.print(" " * 50, end="\r")

        except asyncio.CancelledError:
            pass
        finally:
            self.running = False
            console.print("\n[muted]Watch stopped.[/muted]")

    def stop(self) -> None:
        """Stop the watch loop."""
        self.running = False


def create_price_alert(threshold: float, above: bool = True) -> AlertRule:
    """Create a price alert rule."""
    import uuid

    alert_type = AlertType.PRICE_ABOVE if above else AlertType.PRICE_BELOW
    direction = "above" if above else "below"

    return AlertRule(
        id=str(uuid.uuid4())[:8],
        type=alert_type,
        name=f"TAO price {direction} ${threshold}",
        threshold=threshold,
    )


def create_validator_alert(
    hotkey: str,
    name: Optional[str] = None,
    netuid: int = 1,
) -> AlertRule:
    """Create a validator alert rule."""
    import uuid

    display_name = name or hotkey[:12] + "..."

    return AlertRule(
        id=str(uuid.uuid4())[:8],
        type=AlertType.VALIDATOR_RANK_CHANGE,
        name=f"Validator {display_name} on SN{netuid}",
        threshold=0,  # Not used for validator alerts currently
        netuid=netuid,
        validator_hotkey=hotkey,
        validator_name=name,
    )


def create_registration_alert(netuid: int, max_burn: float = 1.0) -> AlertRule:
    """Create a registration window alert."""
    import uuid

    return AlertRule(
        id=str(uuid.uuid4())[:8],
        type=AlertType.REGISTRATION_OPEN,
        name=f"SN{netuid} registration <= {max_burn} τ",
        threshold=max_burn,
        netuid=netuid,
    )


async def watch(
    taostats: TaostatsClient,
    price_alert: Optional[str] = None,
    validator_alert: Optional[str] = None,
    registration_alert: Optional[int] = None,
    netuid: int = 1,
    poll_interval: int = 30,
    duration: Optional[int] = None,
    json_output: bool = False,
) -> None:
    """Run watch mode with optional alert configuration.

    Args:
        taostats: TaostatsClient instance
        price_alert: Price alert in format "TAO:500" or ">500" or "<400"
        validator_alert: Validator name or hotkey to watch
        registration_alert: Max burn cost to alert for registration
        netuid: Subnet ID for validator/registration alerts
        poll_interval: Seconds between checks
        duration: Run for this many seconds (None = indefinitely)
        json_output: Output alerts as JSON
    """
    alert_store = AlertStore()

    # Add any new alerts specified
    if price_alert:
        # Parse price alert: "TAO:500", ">500", "<400"
        price_alert = price_alert.upper().replace("TAO:", "")
        above = True
        if price_alert.startswith("<"):
            above = False
            price_alert = price_alert[1:]
        elif price_alert.startswith(">"):
            price_alert = price_alert[1:]

        try:
            threshold = float(price_alert)
            rule = create_price_alert(threshold, above=above)
            alert_store.add_rule(rule)
            console.print(f"[success]Added price alert: {rule.name}[/success]")
        except ValueError:
            console.print(f"[error]Invalid price format: {price_alert}[/error]")
            return

    if validator_alert:
        # Try to find validator by name
        validator = await taostats.search_validator(validator_alert, netuid=netuid)
        if validator:
            rule = create_validator_alert(
                hotkey=validator.hotkey,
                name=validator.name,
                netuid=netuid,
            )
            alert_store.add_rule(rule)
            console.print(f"[success]Added validator alert: {rule.name}[/success]")
        else:
            # Assume it's a hotkey
            rule = create_validator_alert(
                hotkey=validator_alert,
                netuid=netuid,
            )
            alert_store.add_rule(rule)
            console.print(f"[success]Added validator alert: {rule.name}[/success]")

    if registration_alert is not None:
        rule = create_registration_alert(netuid, max_burn=registration_alert)
        alert_store.add_rule(rule)
        console.print(f"[success]Added registration alert: {rule.name}[/success]")

    console.print()

    # Create and run the watch
    runner = WatchRunner(
        taostats=taostats,
        alert_store=alert_store,
        poll_interval=poll_interval,
    )

    try:
        await runner.run(duration=duration)
    except KeyboardInterrupt:
        runner.stop()

    # Final summary
    if json_output:
        output = {
            "alerts_triggered": [
                {
                    "rule_name": a.rule.name,
                    "message": a.message,
                    "value": a.value,
                    "timestamp": a.timestamp,
                }
                for a in runner.alerts_triggered
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        if runner.alerts_triggered:
            console.print(f"\n[info]Total alerts triggered: {len(runner.alerts_triggered)}[/info]")


def list_alerts(json_output: bool = False) -> None:
    """List all configured alerts."""
    alert_store = AlertStore()
    rules = alert_store.get_rules(enabled_only=False)

    if json_output:
        output = [r.to_dict() for r in rules]
        print(json.dumps(output, indent=2))
        return

    if not rules:
        console.print("[muted]No alert rules configured.[/muted]")
        console.print("[muted]Use 'taox watch --price TAO:500' to add a price alert[/muted]")
        return

    table = Table(
        title="[primary]Alert Rules[/primary]",
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
    )
    table.add_column("ID", style="muted")
    table.add_column("Name", style="info")
    table.add_column("Type", style="secondary")
    table.add_column("Threshold", justify="right")
    table.add_column("Status", justify="center")

    for rule in rules:
        status = "[success]Enabled[/success]" if rule.enabled else "[muted]Disabled[/muted]"
        threshold_str = f"{rule.threshold}"
        if rule.type in (AlertType.PRICE_ABOVE, AlertType.PRICE_BELOW):
            threshold_str = f"${rule.threshold:.2f}"
        elif rule.type == AlertType.REGISTRATION_OPEN:
            threshold_str = f"{rule.threshold:.4f} τ"

        table.add_row(
            rule.id,
            rule.name,
            rule.type.value,
            threshold_str,
            status,
        )

    console.print(table)


def clear_alerts() -> int:
    """Clear all alert rules. Returns number of rules cleared."""
    alert_store = AlertStore()
    rules = alert_store.get_rules(enabled_only=False)
    count = len(rules)

    if alert_store.storage_path.exists():
        alert_store.storage_path.unlink()

    return count
