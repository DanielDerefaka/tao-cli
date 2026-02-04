"""Subnet operations for taox."""

from typing import Optional
from rich.table import Table
from rich import box

from taox.ui.console import console, format_tao, print_error
from taox.ui.theme import TaoxColors
from taox.data.sdk import BittensorSDK, NeuronInfo
from taox.data.taostats import TaostatsClient, Subnet
from taox.commands.executor import BtcliExecutor, build_metagraph_command


async def list_subnets(taostats: TaostatsClient) -> list[Subnet]:
    """List all subnets.

    Args:
        taostats: TaostatsClient instance

    Returns:
        List of Subnet objects
    """
    with console.status("[bold green]Fetching subnets..."):
        subnets = await taostats.get_subnets()

    if not subnets:
        console.print("[muted]No subnets found.[/muted]")
        return []

    table = Table(
        title="[primary]Subnets[/primary]",
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
    )
    table.add_column("ID", justify="right", style="subnet")
    table.add_column("Name", style="primary")
    table.add_column("Emission", justify="right", style="tao")
    table.add_column("Validators", justify="right", style="muted")
    table.add_column("Burn Cost", justify="right", style="warning")

    for subnet in sorted(subnets, key=lambda s: s.netuid):
        name = subnet.name or "[muted]Unknown[/muted]"
        emission_pct = f"{subnet.emission * 100:.1f}%" if subnet.emission else "0%"

        table.add_row(
            str(subnet.netuid),
            name,
            emission_pct,
            str(subnet.validators),
            format_tao(subnet.burn_cost, symbol=False) if subnet.burn_cost else "-",
        )

    console.print(table)
    return subnets


async def show_subnet_info(
    taostats: TaostatsClient,
    sdk: BittensorSDK,
    netuid: int,
) -> Optional[Subnet]:
    """Show detailed information about a subnet.

    Args:
        taostats: TaostatsClient instance
        sdk: BittensorSDK instance
        netuid: Subnet ID

    Returns:
        Subnet info or None
    """
    with console.status(f"[bold green]Fetching subnet {netuid} info..."):
        subnet = await taostats.get_subnet(netuid)

    if not subnet:
        print_error(f"Subnet {netuid} not found")
        return None

    console.print()
    console.print(f"[primary]Subnet {netuid}[/primary]")
    console.print(f"[bold]Name:[/bold] {subnet.name or 'Unknown'}")
    console.print(f"[bold]Emission:[/bold] {subnet.emission * 100:.2f}%")
    console.print(f"[bold]Tempo:[/bold] {subnet.tempo} blocks")
    console.print(f"[bold]Difficulty:[/bold] {subnet.difficulty:,.0f}")
    console.print(f"[bold]Burn Cost:[/bold] {format_tao(subnet.burn_cost)}")
    console.print(f"[bold]Total Stake:[/bold] {format_tao(subnet.total_stake)}")
    console.print(f"[bold]Validators:[/bold] {subnet.validators}")
    console.print()

    return subnet


async def show_metagraph(
    sdk: BittensorSDK,
    executor: BtcliExecutor,
    netuid: int,
    limit: int = 20,
    use_btcli: bool = False,
) -> list[NeuronInfo]:
    """Show metagraph for a subnet.

    Args:
        sdk: BittensorSDK instance
        executor: BtcliExecutor instance
        netuid: Subnet ID
        limit: Maximum neurons to show
        use_btcli: Use btcli command instead of SDK

    Returns:
        List of NeuronInfo objects
    """
    if use_btcli:
        # Use btcli for metagraph
        cmd_info = build_metagraph_command(netuid=netuid)
        result = executor.run(**cmd_info)
        if result.success:
            console.print(result.stdout)
        else:
            print_error(f"Failed to get metagraph: {result.stderr}")
        return []

    with console.status(f"[bold green]Fetching metagraph for subnet {netuid}..."):
        neurons = sdk.get_metagraph(netuid)

    if not neurons:
        console.print(f"[muted]No neurons found in subnet {netuid}.[/muted]")
        return []

    # Sort by stake descending
    neurons = sorted(neurons, key=lambda n: n.stake, reverse=True)[:limit]

    table = Table(
        title=f"[primary]Metagraph - Subnet {netuid}[/primary]",
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
    )
    table.add_column("UID", justify="right", style="muted")
    table.add_column("Hotkey", style="address")
    table.add_column("Stake", justify="right", style="tao")
    table.add_column("Trust", justify="right", style="info")
    table.add_column("Incentive", justify="right", style="success")
    table.add_column("VPermit", justify="center", style="warning")

    for n in neurons:
        vpermit = "[success]✓[/success]" if n.vpermit else "[muted]✗[/muted]"
        table.add_row(
            str(n.uid),
            f"{n.hotkey[:8]}...{n.hotkey[-8:]}",
            f"{n.stake:,.2f}",
            f"{n.trust:.4f}",
            f"{n.incentive:.4f}",
            vpermit,
        )

    console.print(table)
    console.print(f"\n[muted]Showing top {len(neurons)} neurons by stake[/muted]")

    return neurons


async def get_burn_cost(sdk: BittensorSDK, netuid: int) -> float:
    """Get the registration burn cost for a subnet.

    Args:
        sdk: BittensorSDK instance
        netuid: Subnet ID

    Returns:
        Burn cost in TAO
    """
    with console.status(f"[bold green]Fetching burn cost for subnet {netuid}..."):
        cost = sdk.get_burn_cost(netuid)

    console.print(f"[primary]Subnet {netuid} Registration Cost:[/primary] {format_tao(cost)}")
    return cost
