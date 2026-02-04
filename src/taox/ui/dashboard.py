"""Full TUI dashboard for taox using Textual."""

from datetime import datetime
from typing import Optional

from rich.panel import Panel
from rich.table import Table
from textual import work
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Footer, Header, Static

from taox.config.settings import get_settings
from taox.data.sdk import BittensorSDK
from taox.data.taostats import PriceInfo, Subnet, TaostatsClient, Validator


class PriceWidget(Static):
    """Widget displaying TAO price information."""

    price: reactive[float] = reactive(0.0)
    change: reactive[float] = reactive(0.0)

    def compose(self) -> ComposeResult:
        yield Static(id="price-content")

    def watch_price(self) -> None:
        self._update_display()

    def watch_change(self) -> None:
        self._update_display()

    def _update_display(self) -> None:
        change_color = "green" if self.change >= 0 else "red"
        change_symbol = "+" if self.change >= 0 else ""

        content = f"""[bold]TAO Price[/bold]
[cyan]${self.price:,.2f}[/cyan]
[{change_color}]{change_symbol}{self.change:.2f}%[/{change_color}]"""

        self.query_one("#price-content", Static).update(
            Panel(content, border_style="cyan", title="💰 Price")
        )

    def update_price(self, price_info: PriceInfo) -> None:
        self.price = price_info.usd
        self.change = price_info.change_24h


class BalanceWidget(Static):
    """Widget displaying wallet balance."""

    free: reactive[float] = reactive(0.0)
    staked: reactive[float] = reactive(0.0)
    usd_price: reactive[float] = reactive(0.0)

    def compose(self) -> ComposeResult:
        yield Static(id="balance-content")

    def watch_free(self) -> None:
        self._update_display()

    def watch_staked(self) -> None:
        self._update_display()

    def _update_display(self) -> None:
        total = self.free + self.staked
        usd_value = total * self.usd_price if self.usd_price > 0 else 0

        content = f"""[bold]Free:[/bold] [green]{self.free:,.4f} τ[/green]
[bold]Staked:[/bold] [yellow]{self.staked:,.4f} τ[/yellow]
[bold]Total:[/bold] [cyan]{total:,.4f} τ[/cyan]
[dim]≈ ${usd_value:,.2f} USD[/dim]"""

        self.query_one("#balance-content", Static).update(
            Panel(content, border_style="green", title="💳 Balance")
        )

    def update_balance(self, free: float, staked: float, usd_price: float) -> None:
        self.usd_price = usd_price
        self.free = free
        self.staked = staked


class StakePositionsWidget(Static):
    """Widget displaying stake positions."""

    def compose(self) -> ComposeResult:
        yield Static(id="positions-content")

    def update_positions(
        self, positions: list[dict], validators: dict[str, str], usd_price: float
    ) -> None:
        if not positions:
            self.query_one("#positions-content", Static).update(
                Panel("[dim]No stake positions[/dim]", border_style="yellow", title="📊 Positions")
            )
            return

        table = Table(box=None, expand=True, show_header=True, header_style="bold")
        table.add_column("Subnet", style="cyan")
        table.add_column("Validator", style="magenta")
        table.add_column("Stake", justify="right", style="green")
        table.add_column("Value", justify="right", style="dim")

        for pos in sorted(positions, key=lambda p: p.get("stake", 0), reverse=True)[:8]:
            netuid = pos.get("netuid", "?")
            hotkey = pos.get("hotkey", "")
            stake = pos.get("stake", 0)
            validator_name = validators.get(hotkey, hotkey[:8] + "...")
            usd_value = stake * usd_price

            table.add_row(
                f"SN{netuid}",
                validator_name[:15],
                f"{stake:,.2f} τ",
                f"${usd_value:,.0f}",
            )

        self.query_one("#positions-content", Static).update(
            Panel(table, border_style="yellow", title="📊 Stake Positions")
        )


class ValidatorsWidget(Static):
    """Widget displaying top validators."""

    def compose(self) -> ComposeResult:
        yield Static(id="validators-content")

    def update_validators(self, validators: list[Validator]) -> None:
        if not validators:
            self.query_one("#validators-content", Static).update(
                Panel(
                    "[dim]Loading validators...[/dim]",
                    border_style="magenta",
                    title="🏆 Top Validators",
                )
            )
            return

        table = Table(box=None, expand=True, show_header=True, header_style="bold")
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", style="magenta")
        table.add_column("Stake", justify="right", style="green")
        table.add_column("Take", justify="right", style="yellow")

        for i, v in enumerate(validators[:10], 1):
            name = v.name or "Unknown"
            table.add_row(
                str(i),
                name[:18],
                f"{v.stake/1000:,.0f}K τ",
                f"{v.take * 100:.1f}%",
            )

        self.query_one("#validators-content", Static).update(
            Panel(table, border_style="magenta", title="🏆 Top Validators")
        )


class SubnetsWidget(Static):
    """Widget displaying subnets overview."""

    def compose(self) -> ComposeResult:
        yield Static(id="subnets-content")

    def update_subnets(self, subnets: list[Subnet]) -> None:
        if not subnets:
            self.query_one("#subnets-content", Static).update(
                Panel("[dim]Loading subnets...[/dim]", border_style="blue", title="🌐 Subnets")
            )
            return

        # Sort by emission and take top 8
        sorted_subnets = sorted(subnets, key=lambda s: s.emission, reverse=True)[:8]

        table = Table(box=None, expand=True, show_header=True, header_style="bold")
        table.add_column("ID", style="cyan", width=4)
        table.add_column("Name", style="blue")
        table.add_column("Emission", justify="right", style="green")

        for s in sorted_subnets:
            name = s.name or f"Subnet {s.netuid}"
            table.add_row(
                f"SN{s.netuid}",
                name[:15],
                f"{s.emission * 100:.1f}%",
            )

        self.query_one("#subnets-content", Static).update(
            Panel(table, border_style="blue", title="🌐 Top Subnets")
        )


class StatusBar(Static):
    """Status bar showing connection info and last update."""

    last_update: reactive[str] = reactive("")
    network: reactive[str] = reactive("finney")
    wallet: reactive[str] = reactive("default")

    def compose(self) -> ComposeResult:
        yield Static(id="status-content")

    def watch_last_update(self) -> None:
        self._update_display()

    def _update_display(self) -> None:
        demo = "[yellow](DEMO)[/yellow] " if get_settings().demo_mode else ""
        content = f"{demo}[dim]Network:[/dim] [cyan]{self.network}[/cyan] | [dim]Wallet:[/dim] [green]{self.wallet}[/green] | [dim]Updated:[/dim] {self.last_update}"
        self.query_one("#status-content", Static).update(content)

    def set_status(self, network: str, wallet: str) -> None:
        self.network = network
        self.wallet = wallet
        self.last_update = datetime.now().strftime("%H:%M:%S")


class TaoxDashboard(App):
    """Main taox dashboard application."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 3 3;
        grid-gutter: 1;
    }

    #price-widget {
        column-span: 1;
        row-span: 1;
    }

    #balance-widget {
        column-span: 1;
        row-span: 1;
    }

    #status-widget {
        column-span: 1;
        row-span: 1;
        height: auto;
    }

    #positions-widget {
        column-span: 2;
        row-span: 2;
    }

    #validators-widget {
        column-span: 1;
        row-span: 1;
    }

    #subnets-widget {
        column-span: 1;
        row-span: 1;
    }

    StatusBar {
        dock: bottom;
        height: 1;
        background: $surface;
    }

    PriceWidget, BalanceWidget, StakePositionsWidget, ValidatorsWidget, SubnetsWidget {
        height: 100%;
        width: 100%;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("s", "stake", "Stake"),
        ("p", "portfolio", "Portfolio"),
    ]

    def __init__(
        self,
        wallet_name: Optional[str] = None,
        refresh_interval: int = 30,
    ):
        super().__init__()
        self.settings = get_settings()
        self.wallet_name = wallet_name or self.settings.bittensor.default_wallet
        self.refresh_interval = refresh_interval
        self.taostats = TaostatsClient()
        self.sdk = BittensorSDK()
        self._refresh_timer: Optional[Timer] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield PriceWidget(id="price-widget")
        yield BalanceWidget(id="balance-widget")
        yield StakePositionsWidget(id="positions-widget")
        yield ValidatorsWidget(id="validators-widget")
        yield SubnetsWidget(id="subnets-widget")
        yield StatusBar(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        """Called when app is mounted."""
        self.title = "taox Dashboard"
        self.sub_title = "Bittensor Portfolio Manager"

        # Initial data load
        self.refresh_data()

        # Set up auto-refresh
        self._refresh_timer = self.set_interval(self.refresh_interval, self.refresh_data)

    @work(exclusive=True)
    async def refresh_data(self) -> None:
        """Refresh all dashboard data."""
        try:
            # Fetch all data concurrently
            price_info = await self.taostats.get_price()
            validators = await self.taostats.get_validators(limit=50)
            subnets = await self.taostats.get_subnets()

            # Get wallet info
            wallet = self.sdk.get_wallet(name=self.wallet_name)
            if wallet:
                coldkey = wallet.coldkey.ss58_address
                balance_info = await self.sdk.get_balance_async(coldkey)
                stake_data = await self.taostats.get_stake_balance(coldkey)
            else:
                # Demo mode fallback
                coldkey = "demo"
                balance_info = type("obj", (object,), {"free": 100.0})()
                stake_data = await self.taostats.get_stake_balance("demo")

            # Build validator name lookup
            validator_names = {v.hotkey: v.name or "Unknown" for v in validators}

            # Update widgets
            self.query_one(PriceWidget).update_price(price_info)
            self.query_one(BalanceWidget).update_balance(
                free=balance_info.free,
                staked=stake_data.get("total_stake", 0),
                usd_price=price_info.usd,
            )
            self.query_one(StakePositionsWidget).update_positions(
                positions=stake_data.get("positions", []),
                validators=validator_names,
                usd_price=price_info.usd,
            )
            self.query_one(ValidatorsWidget).update_validators(validators)
            self.query_one(SubnetsWidget).update_subnets(subnets)

            # Update status bar
            self.query_one(StatusBar).set_status(
                network=self.settings.bittensor.network,
                wallet=self.wallet_name,
            )

        except Exception as e:
            self.notify(f"Error refreshing data: {e}", severity="error")

    def action_refresh(self) -> None:
        """Manual refresh action."""
        self.refresh_data()
        self.notify("Refreshing data...")

    def action_stake(self) -> None:
        """Open stake wizard."""
        self.notify("Use 'taox stake --wizard' for staking", severity="information")

    def action_portfolio(self) -> None:
        """Show detailed portfolio."""
        self.notify("Use 'taox portfolio' for details", severity="information")


def run_dashboard(wallet_name: Optional[str] = None, refresh_interval: int = 30) -> None:
    """Run the taox dashboard.

    Args:
        wallet_name: Wallet to display (optional)
        refresh_interval: Auto-refresh interval in seconds
    """
    app = TaoxDashboard(
        wallet_name=wallet_name,
        refresh_interval=refresh_interval,
    )
    app.run()
