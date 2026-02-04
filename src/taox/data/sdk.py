"""Bittensor SDK wrapper for taox."""

import logging
from typing import Optional
from dataclasses import dataclass
from pathlib import Path

from taox.config.settings import get_settings


logger = logging.getLogger(__name__)


# Try to import bittensor - may not be installed
try:
    import bittensor as bt
    from bittensor.core.subtensor import Subtensor
    from bittensor.core.async_subtensor import AsyncSubtensor
    from bittensor.core.metagraph import Metagraph
    from bittensor_wallet import Wallet
    from bittensor.utils.balance import Balance, tao, rao

    BITTENSOR_AVAILABLE = True
except ImportError:
    BITTENSOR_AVAILABLE = False
    logger.warning("Bittensor SDK not installed. Some features will be unavailable.")


@dataclass
class WalletInfo:
    """Information about a wallet."""

    name: str
    coldkey_ss58: str
    hotkeys: list[str]
    path: str


@dataclass
class BalanceInfo:
    """Balance information for an address."""

    free: float
    staked: float
    total: float


@dataclass
class NeuronInfo:
    """Information about a neuron in a subnet."""

    uid: int
    hotkey: str
    coldkey: str
    stake: float
    rank: float
    trust: float
    consensus: float
    incentive: float
    dividends: float
    emission: float
    vpermit: bool
    active: bool


# Mock data for demo mode
MOCK_BALANCE = BalanceInfo(free=100.0, staked=500.0, total=600.0)

MOCK_WALLETS = [
    WalletInfo(
        name="default",
        coldkey_ss58="5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v",
        hotkeys=["default", "miner1"],
        path="~/.bittensor/wallets/default",
    ),
    WalletInfo(
        name="validator",
        coldkey_ss58="5HK5tp6t2S59DywmHRWPBVJeJ86T61KjurYqeooqj8sREpeN",
        hotkeys=["main"],
        path="~/.bittensor/wallets/validator",
    ),
]


class BittensorSDK:
    """Wrapper for Bittensor SDK operations."""

    def __init__(self, network: Optional[str] = None):
        """Initialize the SDK wrapper.

        Args:
            network: Network to connect to (finney, test, local)
        """
        self.settings = get_settings()
        self.network = network or self.settings.bittensor.network
        self._subtensor: Optional["Subtensor"] = None
        self._async_subtensor: Optional["AsyncSubtensor"] = None

    @property
    def is_available(self) -> bool:
        """Check if Bittensor SDK is available."""
        return BITTENSOR_AVAILABLE and not self.settings.demo_mode

    def _get_subtensor(self) -> "Subtensor":
        """Get or create the sync Subtensor instance."""
        if not BITTENSOR_AVAILABLE:
            raise RuntimeError("Bittensor SDK not installed")
        if self._subtensor is None:
            self._subtensor = Subtensor(network=self.network)
        return self._subtensor

    async def _get_async_subtensor(self) -> "AsyncSubtensor":
        """Get or create the async Subtensor instance."""
        if not BITTENSOR_AVAILABLE:
            raise RuntimeError("Bittensor SDK not installed")
        if self._async_subtensor is None:
            self._async_subtensor = AsyncSubtensor(network=self.network)
        return self._async_subtensor

    def list_wallets(self) -> list[WalletInfo]:
        """List all wallets in the wallet path.

        Returns:
            List of WalletInfo objects
        """
        if not self.is_available:
            return MOCK_WALLETS

        wallet_path = Path(self.settings.bittensor.wallet_path).expanduser()
        wallets = []

        if not wallet_path.exists():
            return wallets

        for wallet_dir in wallet_path.iterdir():
            if not wallet_dir.is_dir():
                continue

            try:
                wallet = Wallet(name=wallet_dir.name, path=str(wallet_path))

                # Get hotkeys
                hotkeys_dir = wallet_dir / "hotkeys"
                hotkeys = []
                if hotkeys_dir.exists():
                    hotkeys = [h.name for h in hotkeys_dir.iterdir() if h.is_file()]

                # Get coldkey SS58
                coldkey_pub = wallet_dir / "coldkeypub.txt"
                coldkey_ss58 = ""
                if coldkey_pub.exists():
                    coldkey_ss58 = coldkey_pub.read_text().strip()

                wallets.append(
                    WalletInfo(
                        name=wallet_dir.name,
                        coldkey_ss58=coldkey_ss58,
                        hotkeys=hotkeys,
                        path=str(wallet_dir),
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to load wallet {wallet_dir.name}: {e}")

        return wallets

    def get_wallet(self, name: Optional[str] = None, hotkey: Optional[str] = None) -> Optional["Wallet"]:
        """Get a wallet by name.

        Args:
            name: Wallet name (uses default if not provided)
            hotkey: Hotkey name (uses default if not provided)

        Returns:
            Wallet instance or None
        """
        if not BITTENSOR_AVAILABLE:
            return None

        name = name or self.settings.bittensor.default_wallet
        hotkey = hotkey or self.settings.bittensor.default_hotkey
        wallet_path = Path(self.settings.bittensor.wallet_path).expanduser()

        try:
            return Wallet(name=name, hotkey=hotkey, path=str(wallet_path))
        except Exception as e:
            logger.error(f"Failed to get wallet {name}: {e}")
            return None

    def get_balance(self, address: str) -> BalanceInfo:
        """Get balance for an SS58 address.

        Args:
            address: SS58 address

        Returns:
            BalanceInfo with free/staked/total balances
        """
        if not self.is_available:
            return MOCK_BALANCE

        try:
            subtensor = self._get_subtensor()
            balance = subtensor.get_balance(address)
            # Note: getting total staked requires additional queries
            return BalanceInfo(
                free=float(balance.tao),
                staked=0.0,  # Would need separate stake query
                total=float(balance.tao),
            )
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return BalanceInfo(free=0.0, staked=0.0, total=0.0)

    async def get_balance_async(self, address: str) -> BalanceInfo:
        """Async version of get_balance.

        Args:
            address: SS58 address

        Returns:
            BalanceInfo
        """
        if not self.is_available:
            return MOCK_BALANCE

        try:
            async with AsyncSubtensor(network=self.network) as subtensor:
                balance = await subtensor.get_balance(address)
                return BalanceInfo(
                    free=float(balance.tao),
                    staked=0.0,
                    total=float(balance.tao),
                )
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return BalanceInfo(free=0.0, staked=0.0, total=0.0)

    def get_metagraph(self, netuid: int) -> list[NeuronInfo]:
        """Get metagraph data for a subnet.

        Args:
            netuid: Subnet ID

        Returns:
            List of NeuronInfo objects
        """
        if not self.is_available:
            # Return mock metagraph data
            return [
                NeuronInfo(
                    uid=i,
                    hotkey=f"5Mock{i:03d}{'x' * 43}",
                    coldkey=f"5Cold{i:03d}{'x' * 43}",
                    stake=1000.0 - i * 100,
                    rank=float(i + 1),
                    trust=0.9 - i * 0.1,
                    consensus=0.95 - i * 0.05,
                    incentive=0.1 - i * 0.01,
                    dividends=0.05 - i * 0.005,
                    emission=10.0 - i,
                    vpermit=i < 5,
                    active=True,
                )
                for i in range(10)
            ]

        try:
            metagraph = Metagraph(netuid=netuid, network=self.network, sync=True)
            neurons = []

            for uid in range(metagraph.n.item()):
                neurons.append(
                    NeuronInfo(
                        uid=uid,
                        hotkey=metagraph.hotkeys[uid],
                        coldkey=metagraph.coldkeys[uid],
                        stake=float(metagraph.S[uid]),
                        rank=float(metagraph.R[uid]),
                        trust=float(metagraph.T[uid]),
                        consensus=float(metagraph.C[uid]),
                        incentive=float(metagraph.I[uid]),
                        dividends=float(metagraph.D[uid]),
                        emission=float(metagraph.E[uid]),
                        vpermit=bool(metagraph.validator_permit[uid]),
                        active=bool(metagraph.active[uid]),
                    )
                )

            return neurons

        except Exception as e:
            logger.error(f"Failed to get metagraph: {e}")
            return []

    async def get_subnets_async(self) -> list[dict]:
        """Get list of all subnets.

        Returns:
            List of subnet info dicts
        """
        if not self.is_available:
            return [
                {"netuid": 0, "name": "Root"},
                {"netuid": 1, "name": "Text Prompting"},
                {"netuid": 18, "name": "Cortex.t"},
            ]

        try:
            async with AsyncSubtensor(network=self.network) as subtensor:
                subnets = await subtensor.all_subnets()
                return [
                    {
                        "netuid": s.netuid,
                        "name": getattr(s, "name", None),
                        "emission": getattr(s, "tao_in_emission", 0),
                    }
                    for s in subnets
                ]
        except Exception as e:
            logger.error(f"Failed to get subnets: {e}")
            return []

    def get_burn_cost(self, netuid: int) -> float:
        """Get the registration burn cost for a subnet.

        Args:
            netuid: Subnet ID

        Returns:
            Burn cost in TAO
        """
        if not self.is_available:
            return 1.0  # Mock burn cost

        try:
            subtensor = self._get_subtensor()
            burn = subtensor.burn(netuid=netuid)
            return float(burn.tao)
        except Exception as e:
            logger.error(f"Failed to get burn cost: {e}")
            return 0.0

    def close(self) -> None:
        """Close any open connections."""
        # Subtensor doesn't have an explicit close method for sync
        self._subtensor = None
        self._async_subtensor = None
