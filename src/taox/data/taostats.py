"""Taostats API client for taox."""

import logging
from typing import Optional
from dataclasses import dataclass

import httpx

from taox.config.settings import get_settings
from taox.security.credentials import CredentialManager
from taox.data.cache import validator_cache, subnet_cache, price_cache, cached


logger = logging.getLogger(__name__)


@dataclass
class Validator:
    """Validator information from Taostats."""

    hotkey: str
    name: Optional[str]
    stake: float
    vpermit: bool
    netuid: int
    uid: int
    rank: int = 0
    take: float = 0.0


@dataclass
class Subnet:
    """Subnet information from Taostats."""

    netuid: int
    name: Optional[str]
    emission: float
    tempo: int
    difficulty: float
    burn_cost: float
    total_stake: float
    validators: int


@dataclass
class PriceInfo:
    """TAO price information."""

    usd: float
    btc: float
    change_24h: float


# Mock data for demo mode
MOCK_VALIDATORS = [
    Validator(
        hotkey="5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v",
        name="Taostats",
        stake=1500000.0,
        vpermit=True,
        netuid=1,
        uid=0,
        rank=1,
        take=0.09,
    ),
    Validator(
        hotkey="5HK5tp6t2S59DywmHRWPBVJeJ86T61KjurYqeooqj8sREpeN",
        name="OpenTensor Foundation",
        stake=1200000.0,
        vpermit=True,
        netuid=1,
        uid=1,
        rank=2,
        take=0.10,
    ),
    Validator(
        hotkey="5Hddm3iBFD2GLT5ik7LZnT3XJUnRnN8PoeCFgGQYawFqw4qK",
        name="RoundTable21",
        stake=800000.0,
        vpermit=True,
        netuid=1,
        uid=2,
        rank=3,
        take=0.08,
    ),
    Validator(
        hotkey="5DvTpiniW9s3APmHRYn8FroUWyfnLtrsid5Mtn5EwMXHN2ed",
        name="Manifold Labs",
        stake=600000.0,
        vpermit=True,
        netuid=1,
        uid=3,
        rank=4,
        take=0.10,
    ),
    Validator(
        hotkey="5CXRfP2ekFhe62r7q3vppRajJmGhTi7vwvb2yr79jveZ282w",
        name="Rizzo",
        stake=500000.0,
        vpermit=True,
        netuid=1,
        uid=4,
        rank=5,
        take=0.05,
    ),
]

MOCK_SUBNETS = [
    Subnet(netuid=0, name="Root", emission=0.0, tempo=100, difficulty=0, burn_cost=0, total_stake=10000000, validators=64),
    Subnet(netuid=1, name="Text Prompting", emission=0.15, tempo=360, difficulty=1000000, burn_cost=1.5, total_stake=5000000, validators=256),
    Subnet(netuid=3, name="Data Scraping", emission=0.08, tempo=360, difficulty=500000, burn_cost=0.8, total_stake=2000000, validators=128),
    Subnet(netuid=8, name="Time Series", emission=0.05, tempo=360, difficulty=300000, burn_cost=0.5, total_stake=1500000, validators=96),
    Subnet(netuid=18, name="Cortex.t", emission=0.10, tempo=360, difficulty=800000, burn_cost=1.2, total_stake=3000000, validators=200),
    Subnet(netuid=19, name="Vision", emission=0.07, tempo=360, difficulty=600000, burn_cost=0.9, total_stake=2500000, validators=150),
    Subnet(netuid=64, name="Chutes", emission=0.12, tempo=360, difficulty=900000, burn_cost=1.4, total_stake=4000000, validators=180),
]

MOCK_PRICE = PriceInfo(usd=450.0, btc=0.0045, change_24h=2.5)


class TaostatsClient:
    """Client for Taostats API."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Taostats client.

        Args:
            api_key: Taostats API key (if not provided, will try to get from keyring)
        """
        self.settings = get_settings()
        self._api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def api_key(self) -> Optional[str]:
        """Get the API key."""
        if self._api_key:
            return self._api_key
        return CredentialManager.get_taostats_key()

    @property
    def is_available(self) -> bool:
        """Check if Taostats API is available."""
        return self.api_key is not None and not self.settings.demo_mode

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.taostats.base_url,
                headers={"Authorization": self.api_key} if self.api_key else {},
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_validators(
        self, netuid: Optional[int] = None, limit: int = 10
    ) -> list[Validator]:
        """Get top validators, optionally filtered by subnet.

        Args:
            netuid: Subnet ID to filter by (None for all)
            limit: Maximum number of validators to return

        Returns:
            List of Validator objects
        """
        if not self.is_available:
            validators = MOCK_VALIDATORS
            if netuid is not None:
                validators = [v for v in validators if v.netuid == netuid]
            return validators[:limit]

        try:
            client = await self._get_client()
            params = {"limit": limit}
            if netuid is not None:
                params["netuid"] = netuid

            response = await client.get("/validator/v1", params=params)
            response.raise_for_status()
            data = response.json()

            validators = []
            for item in data.get("data", []):
                validators.append(
                    Validator(
                        hotkey=item.get("hotkey", ""),
                        name=item.get("name"),
                        stake=float(item.get("stake", 0)),
                        vpermit=item.get("vpermit", False),
                        netuid=item.get("netuid", 0),
                        uid=item.get("uid", 0),
                        rank=item.get("rank", 0),
                        take=float(item.get("take", 0)),
                    )
                )
            return validators

        except Exception as e:
            logger.error(f"Failed to fetch validators: {e}")
            return MOCK_VALIDATORS[:limit]

    async def search_validator(self, name: str, netuid: Optional[int] = None) -> Optional[Validator]:
        """Search for a validator by name.

        Args:
            name: Validator name to search for
            netuid: Subnet ID to filter by (optional)

        Returns:
            Validator if found, None otherwise
        """
        validators = await self.get_validators(netuid=netuid, limit=100)
        name_lower = name.lower()

        for v in validators:
            if v.name and name_lower in v.name.lower():
                return v

        return None

    async def get_subnets(self) -> list[Subnet]:
        """Get list of all subnets.

        Returns:
            List of Subnet objects
        """
        if not self.is_available:
            return MOCK_SUBNETS

        try:
            client = await self._get_client()
            response = await client.get("/subnets/v1")
            response.raise_for_status()
            data = response.json()

            subnets = []
            for item in data.get("data", []):
                subnets.append(
                    Subnet(
                        netuid=item.get("netuid", 0),
                        name=item.get("name"),
                        emission=float(item.get("emission", 0)),
                        tempo=item.get("tempo", 360),
                        difficulty=float(item.get("difficulty", 0)),
                        burn_cost=float(item.get("burn", 0)),
                        total_stake=float(item.get("total_stake", 0)),
                        validators=item.get("validators", 0),
                    )
                )
            return subnets

        except Exception as e:
            logger.error(f"Failed to fetch subnets: {e}")
            return MOCK_SUBNETS

    async def get_subnet(self, netuid: int) -> Optional[Subnet]:
        """Get subnet information by ID.

        Args:
            netuid: Subnet ID

        Returns:
            Subnet if found, None otherwise
        """
        subnets = await self.get_subnets()
        for subnet in subnets:
            if subnet.netuid == netuid:
                return subnet
        return None

    async def get_price(self) -> PriceInfo:
        """Get current TAO price.

        Returns:
            PriceInfo with USD/BTC prices
        """
        if not self.is_available:
            return MOCK_PRICE

        try:
            client = await self._get_client()
            response = await client.get("/price/v1")
            response.raise_for_status()
            data = response.json()

            item = data.get("data", [{}])[0]
            return PriceInfo(
                usd=float(item.get("price", 0)),
                btc=float(item.get("price_btc", 0)),
                change_24h=float(item.get("percent_change_24h", 0)),
            )

        except Exception as e:
            logger.error(f"Failed to fetch price: {e}")
            return MOCK_PRICE

    async def get_stake_balance(self, coldkey: str) -> dict:
        """Get stake balances for a coldkey.

        Args:
            coldkey: SS58 address of the coldkey

        Returns:
            Dict with stake information
        """
        if not self.is_available:
            return {
                "total_stake": 500.0,
                "positions": [
                    {"netuid": 1, "hotkey": MOCK_VALIDATORS[0].hotkey, "stake": 200.0},
                    {"netuid": 18, "hotkey": MOCK_VALIDATORS[1].hotkey, "stake": 150.0},
                    {"netuid": 64, "hotkey": MOCK_VALIDATORS[2].hotkey, "stake": 150.0},
                ],
            }

        try:
            client = await self._get_client()
            response = await client.get(
                "/stake/balance/v1", params={"coldkey": coldkey}
            )
            response.raise_for_status()
            return response.json().get("data", {})

        except Exception as e:
            logger.error(f"Failed to fetch stake balance: {e}")
            return {"total_stake": 0, "positions": []}
