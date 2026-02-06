"""Taostats API client for taox with source tracking.

This module provides the Taostats API client with:
- Automatic source attribution for all data
- Caching with TTL and stale fallback
- Exponential backoff on failures
- Graceful degradation to mock data
"""

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from taox.config.settings import get_settings
from taox.data.cache import (
    backoff_manager,
    persistent_price_cache,
    persistent_validator_cache,
    price_cache,
    validator_cache,
)
from taox.data.sources import (
    DataSource,
    GroundedData,
    get_data_grounder,
)
from taox.security.credentials import CredentialManager

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
class SubnetPool:
    """Subnet pool / alpha token pricing info."""

    netuid: int
    alpha_in_pool: float  # Alpha tokens in pool
    tao_in_pool: float  # TAO in pool
    alpha_price_in_tao: float  # Price of 1 alpha in TAO
    alpha_price_in_usd: float  # Price of 1 alpha in USD (needs TAO price)


@dataclass
class PriceInfo:
    """TAO price information."""

    usd: float
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
    Subnet(
        netuid=0,
        name="Root",
        emission=0.0,
        tempo=100,
        difficulty=0,
        burn_cost=0,
        total_stake=10000000,
        validators=64,
    ),
    Subnet(
        netuid=1,
        name="Text Prompting",
        emission=0.15,
        tempo=360,
        difficulty=1000000,
        burn_cost=1.5,
        total_stake=5000000,
        validators=256,
    ),
    Subnet(
        netuid=3,
        name="Data Scraping",
        emission=0.08,
        tempo=360,
        difficulty=500000,
        burn_cost=0.8,
        total_stake=2000000,
        validators=128,
    ),
    Subnet(
        netuid=8,
        name="Time Series",
        emission=0.05,
        tempo=360,
        difficulty=300000,
        burn_cost=0.5,
        total_stake=1500000,
        validators=96,
    ),
    Subnet(
        netuid=18,
        name="Cortex.t",
        emission=0.10,
        tempo=360,
        difficulty=800000,
        burn_cost=1.2,
        total_stake=3000000,
        validators=200,
    ),
    Subnet(
        netuid=19,
        name="Vision",
        emission=0.07,
        tempo=360,
        difficulty=600000,
        burn_cost=0.9,
        total_stake=2500000,
        validators=150,
    ),
    Subnet(
        netuid=64,
        name="Chutes",
        emission=0.12,
        tempo=360,
        difficulty=900000,
        burn_cost=1.4,
        total_stake=4000000,
        validators=180,
    ),
]

MOCK_PRICE = PriceInfo(usd=450.0, change_24h=2.5)


class TaostatsClient:
    """Client for Taostats API with source tracking.

    All data returned includes source attribution for transparency.
    Implements caching with stale-while-revalidate and exponential backoff.
    """

    # Cache keys
    CACHE_VALIDATORS = "validators"
    CACHE_SUBNETS = "subnets"
    CACHE_PRICE = "price"

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Taostats client.

        Args:
            api_key: Taostats API key (if not provided, will try to get from keyring)
        """
        self.settings = get_settings()
        self._api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None
        self._grounder = get_data_grounder()

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

    def get_availability_message(self) -> str:
        """Get a message about API availability."""
        if self.settings.demo_mode:
            return "Running in demo mode with sample data"
        if not self.api_key:
            return "Taostats API key not configured - run 'taox setup'"
        return "Connected to Taostats API"

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
        grounded = await self.get_validators_grounded(netuid, limit)
        return grounded.value

    async def get_validators_grounded(
        self, netuid: Optional[int] = None, limit: int = 10
    ) -> GroundedData[list[Validator]]:
        """Get top validators with source attribution.

        Args:
            netuid: Subnet ID to filter by (None for all)
            limit: Maximum number of validators to return

        Returns:
            GroundedData containing list of Validators
        """
        cache_key = f"{self.CACHE_VALIDATORS}:{netuid}:{limit}"

        # Demo mode
        if self.settings.demo_mode:
            validators = MOCK_VALIDATORS
            if netuid is not None:
                validators = [v for v in validators if v.netuid == netuid]
            return self._grounder.ground(validators[:limit], DataSource.MOCK_DATA)

        # Check API availability
        if not self.is_available:
            cache_result = persistent_validator_cache.get_with_metadata(cache_key)
            if cache_result.value is not None:
                source = DataSource.CACHE_FRESH if cache_result.is_fresh else DataSource.CACHE_STALE
                return self._grounder.ground(
                    cache_result.value,
                    source,
                    cache_age=cache_result.age_seconds,
                    is_fallback=cache_result.is_stale,
                )
            validators = MOCK_VALIDATORS
            if netuid is not None:
                validators = [v for v in validators if v.netuid == netuid]
            result = self._grounder.ground(
                validators[:limit], DataSource.MOCK_DATA, is_fallback=True
            )
            result.add_assumption("Using sample data - no API key configured")
            return result

        # Check backoff
        if not backoff_manager.should_retry(cache_key):
            cache_result = persistent_validator_cache.get_with_metadata(cache_key)
            if cache_result.value is not None:
                return self._grounder.ground(
                    cache_result.value,
                    DataSource.CACHE_STALE,
                    cache_age=cache_result.age_seconds,
                    is_fallback=True,
                )

        try:
            client = await self._get_client()
            params = {"limit": limit}
            if netuid is not None:
                params["netuid"] = netuid

            response = await client.get("/dtao/validator/latest/v1", params=params)
            response.raise_for_status()
            data = response.json()

            validators = []
            for item in data.get("data", []):
                hotkey_data = item.get("hotkey", {})
                hotkey = (
                    hotkey_data.get("ss58", "")
                    if isinstance(hotkey_data, dict)
                    else str(hotkey_data)
                )

                stake_rao = float(item.get("global_weighted_stake", item.get("stake", 0)))
                stake_tao = stake_rao / 1e9 if stake_rao > 1e12 else stake_rao

                take_str = item.get("take", "0")
                take = float(take_str) / 100 if float(take_str) > 1 else float(take_str)

                validators.append(
                    Validator(
                        hotkey=hotkey,
                        name=item.get("name"),
                        stake=stake_tao,
                        vpermit=True,
                        netuid=0,
                        uid=0,
                        rank=item.get("rank", item.get("root_rank", 0)),
                        take=take,
                    )
                )

            # Update caches
            validator_cache.set(cache_key, validators)
            persistent_validator_cache.set_with_source(cache_key, validators, "taostats_api")
            backoff_manager.record_success(cache_key)

            return self._grounder.ground(
                validators,
                DataSource.TAOSTATS_API,
                endpoint="/dtao/validator/latest/v1",
            )

        except Exception as e:
            logger.error(f"Failed to fetch validators: {e}")
            backoff_manager.record_failure(cache_key)

            # Cache fallback
            cache_result = persistent_validator_cache.get_with_metadata(cache_key)
            if cache_result.value is not None:
                return self._grounder.ground(
                    cache_result.value,
                    DataSource.CACHE_STALE,
                    cache_age=cache_result.age_seconds,
                    is_fallback=True,
                    error=str(e),
                )

            # Mock fallback
            validators = MOCK_VALIDATORS
            if netuid is not None:
                validators = [v for v in validators if v.netuid == netuid]
            result = self._grounder.ground(
                validators[:limit],
                DataSource.MOCK_DATA,
                is_fallback=True,
                error=str(e),
            )
            result.add_assumption("API request failed - showing sample validators")
            return result

    async def search_validator(
        self, name: str, netuid: Optional[int] = None
    ) -> Optional[Validator]:
        """Search for a validator by name using fuzzy matching.

        Args:
            name: Validator name to search for
            netuid: Subnet ID to filter by (optional)

        Returns:
            Validator if found, None otherwise
        """
        validators = await self.get_validators(netuid=netuid, limit=100)
        name_lower = name.lower()

        # Exact match first
        for v in validators:
            if v.name and v.name.lower() == name_lower:
                return v

        # Substring match
        for v in validators:
            if v.name and name_lower in v.name.lower():
                return v

        # Fuzzy match - check if query words appear in name
        query_words = name_lower.split()
        best_match = None
        best_score = 0

        for v in validators:
            if not v.name:
                continue
            validator_lower = v.name.lower()
            score = sum(1 for word in query_words if word in validator_lower)
            if score > best_score:
                best_score = score
                best_match = v

        return best_match if best_score > 0 else None

    async def search_validators(
        self, query: str, netuid: Optional[int] = None, limit: int = 5
    ) -> list[Validator]:
        """Search for validators by name with fuzzy matching.

        Args:
            query: Search query
            netuid: Subnet ID to filter by (optional)
            limit: Maximum results to return

        Returns:
            List of matching validators sorted by relevance
        """
        validators = await self.get_validators(netuid=netuid, limit=100)
        query_lower = query.lower()
        query_words = query_lower.split()

        scored = []
        for v in validators:
            if not v.name:
                continue

            name_lower = v.name.lower()
            score = 0

            # Exact match bonus
            if name_lower == query_lower:
                score += 100

            # Starts with bonus
            if name_lower.startswith(query_lower):
                score += 50

            # Contains bonus
            if query_lower in name_lower:
                score += 25

            # Word match bonus
            for word in query_words:
                if word in name_lower:
                    score += 10

            if score > 0:
                scored.append((score, v))

        # Sort by score descending, then by stake descending
        scored.sort(key=lambda x: (-x[0], -x[1].stake))
        return [v for _, v in scored[:limit]]

    async def get_subnets(self) -> list[Subnet]:
        """Get list of all subnets.

        Returns:
            List of Subnet objects
        """
        if not self.is_available:
            return MOCK_SUBNETS

        try:
            client = await self._get_client()

            # Fetch subnet data and identity (names) in parallel
            subnet_response = await client.get("/subnet/latest/v1")
            identity_response = await client.get("/subnet/identity/v1")

            subnet_response.raise_for_status()
            subnet_data = subnet_response.json()

            # Build name lookup from identity endpoint
            subnet_names = {}
            if identity_response.status_code == 200:
                identity_data = identity_response.json()
                for item in identity_data.get("data", []):
                    netuid = item.get("netuid")
                    name = item.get("name") or item.get("subnet_name")
                    if netuid is not None and name:
                        subnet_names[netuid] = name

            subnets = []
            for item in subnet_data.get("data", []):
                # Parse emission - convert from string/scientific notation
                emission_str = item.get("emission", "0")
                try:
                    emission = float(emission_str)
                    # Normalize if needed (emission should be 0-1 range)
                    if emission > 1:
                        emission = emission / 1e18
                except (ValueError, TypeError):
                    emission = 0.0

                # Parse burn cost - use neuron_registration_cost (actual cost to register)
                # Values are in rao, convert to TAO (1 TAO = 1e9 rao)
                burn_rao = float(item.get("neuron_registration_cost", item.get("min_burn", 0)))
                burn_tao = burn_rao / 1e9

                netuid = item.get("netuid", 0)
                subnets.append(
                    Subnet(
                        netuid=netuid,
                        name=subnet_names.get(netuid),  # Get real name from identity API
                        emission=emission,
                        tempo=item.get("tempo", 360),
                        difficulty=float(item.get("difficulty", 0)),
                        burn_cost=burn_tao,
                        total_stake=0,  # Not directly available
                        validators=item.get("validators", item.get("active_validators", 0)),
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

    async def get_subnet_pool(self, netuid: int) -> Optional[SubnetPool]:
        """Get subnet pool data (alpha token pricing).

        Args:
            netuid: Subnet ID

        Returns:
            SubnetPool with pricing info, or None
        """
        if self.settings.demo_mode or not self.is_available:
            # Mock pool data for known subnets
            mock_pools = {
                0: SubnetPool(0, 1000000, 5000000, 5.0, 0),
                1: SubnetPool(1, 800000, 2400000, 3.0, 0),
                18: SubnetPool(18, 500000, 750000, 1.5, 0),
                64: SubnetPool(64, 300000, 660000, 2.2, 0),
            }
            pool = mock_pools.get(netuid)
            if pool:
                # Fill in USD price from TAO price
                try:
                    tao_price = await self.get_price()
                    pool.alpha_price_in_usd = pool.alpha_price_in_tao * tao_price.usd
                except Exception:
                    pass
            return pool

        try:
            client = await self._get_client()
            response = await client.get(
                "/dtao/pool/latest/v1", params={"netuid": netuid}
            )
            response.raise_for_status()
            data = response.json()

            items = data.get("data", [])
            if isinstance(items, list) and len(items) > 0:
                item = items[0]
            elif isinstance(items, dict):
                item = items
            else:
                return None

            # Parse pool amounts (may be in rao)
            alpha_raw = float(item.get("alpha_in", item.get("alpha_in_pool", 0)))
            tao_raw = float(item.get("tao_in", item.get("tao_in_pool", item.get("total_tao", 0))))

            # Convert from rao if values are very large
            # Rao values are 1e9x larger than TAO — no pool has 1B+ TAO
            alpha_in = alpha_raw / 1e9 if alpha_raw > 1e9 else alpha_raw
            tao_in = tao_raw / 1e9 if tao_raw > 1e9 else tao_raw

            # Alpha price = tao_in_pool / alpha_in_pool
            alpha_price = tao_in / alpha_in if alpha_in > 0 else 0

            # Get TAO price for USD conversion
            tao_price = await self.get_price()
            usd_price = alpha_price * tao_price.usd

            return SubnetPool(
                netuid=netuid,
                alpha_in_pool=alpha_in,
                tao_in_pool=tao_in,
                alpha_price_in_tao=alpha_price,
                alpha_price_in_usd=usd_price,
            )

        except Exception as e:
            logger.debug(f"Failed to fetch subnet pool for netuid {netuid}: {e}")
            return None

    async def get_price(self) -> PriceInfo:
        """Get current TAO price.

        Returns:
            PriceInfo with USD price and 24h change
        """
        grounded = await self.get_price_grounded()
        return grounded.value

    async def get_price_grounded(self) -> GroundedData[PriceInfo]:
        """Get current TAO price with source attribution.

        Returns:
            GroundedData containing PriceInfo and source info
        """
        cache_key = self.CACHE_PRICE

        # Check if in demo mode
        if self.settings.demo_mode:
            return self._grounder.ground(
                MOCK_PRICE,
                DataSource.MOCK_DATA,
            )

        # Check if API available
        if not self.is_available:
            # Try cache
            cache_result = persistent_price_cache.get_with_metadata(cache_key)
            if cache_result.value is not None:
                source = DataSource.CACHE_FRESH if cache_result.is_fresh else DataSource.CACHE_STALE
                return self._grounder.ground(
                    (
                        PriceInfo(**cache_result.value)
                        if isinstance(cache_result.value, dict)
                        else cache_result.value
                    ),
                    source,
                    cache_age=cache_result.age_seconds,
                    is_fallback=cache_result.is_stale,
                )

            # No cache, return mock with warning
            result = self._grounder.ground(MOCK_PRICE, DataSource.MOCK_DATA, is_fallback=True)
            result.add_assumption("Using sample data - no API key configured")
            return result

        # Check backoff
        if not backoff_manager.should_retry(cache_key):
            # In backoff, try cache
            cache_result = persistent_price_cache.get_with_metadata(cache_key)
            if cache_result.value is not None:
                return self._grounder.ground(
                    (
                        PriceInfo(**cache_result.value)
                        if isinstance(cache_result.value, dict)
                        else cache_result.value
                    ),
                    DataSource.CACHE_STALE,
                    cache_age=cache_result.age_seconds,
                    is_fallback=True,
                )

        # Try live fetch
        try:
            client = await self._get_client()
            response = await client.get("/price/latest/v1", params={"asset": "tao"})
            response.raise_for_status()
            data = response.json()

            items = data.get("data", [])
            if isinstance(items, list) and len(items) > 0:
                item = items[0]
            else:
                item = items if isinstance(items, dict) else {}

            price_info = PriceInfo(
                usd=float(item.get("price", 0)),
                change_24h=float(item.get("percent_change_24h", 0)),
            )

            # Update caches
            price_cache.set(cache_key, price_info)
            persistent_price_cache.set_with_source(
                cache_key,
                {"usd": price_info.usd, "change_24h": price_info.change_24h},
                "taostats_api",
            )
            backoff_manager.record_success(cache_key)

            return self._grounder.ground(
                price_info,
                DataSource.TAOSTATS_API,
                endpoint="/price/latest/v1",
            )

        except Exception as e:
            logger.error(f"Failed to fetch price: {e}")
            backoff_manager.record_failure(cache_key)

            # Try cache fallback
            cache_result = persistent_price_cache.get_with_metadata(cache_key)
            if cache_result.value is not None:
                return self._grounder.ground(
                    (
                        PriceInfo(**cache_result.value)
                        if isinstance(cache_result.value, dict)
                        else cache_result.value
                    ),
                    DataSource.CACHE_STALE,
                    cache_age=cache_result.age_seconds,
                    is_fallback=True,
                    error=str(e),
                )

            # Final fallback to mock
            result = self._grounder.ground(
                MOCK_PRICE,
                DataSource.MOCK_DATA,
                is_fallback=True,
                error=str(e),
            )
            result.add_assumption("API request failed - showing sample price")
            return result

    async def get_stake_balance(self, coldkey: str) -> dict:
        """Get stake balances for a coldkey including alpha tokens.

        Args:
            coldkey: SS58 address of the coldkey

        Returns:
            Dict with stake information including alpha tokens
        """
        if not self.is_available:
            return {
                "total_stake": 500.0,
                "positions": [
                    {
                        "netuid": 1,
                        "hotkey": MOCK_VALIDATORS[0].hotkey,
                        "stake": 200.0,
                        "alpha_balance": 180.5,
                    },
                    {
                        "netuid": 18,
                        "hotkey": MOCK_VALIDATORS[1].hotkey,
                        "stake": 150.0,
                        "alpha_balance": 145.2,
                    },
                    {
                        "netuid": 64,
                        "hotkey": MOCK_VALIDATORS[2].hotkey,
                        "stake": 150.0,
                        "alpha_balance": 160.8,
                    },
                ],
            }

        try:
            client = await self._get_client()
            # Use the dTao stake balance endpoint with coldkey filter
            response = await client.get(
                "/dtao/stake_balance/latest/v1", params={"coldkey": coldkey}
            )
            response.raise_for_status()
            data = response.json()

            # Parse the response into our format
            positions = []
            total_stake = 0.0

            items = data.get("data", [])
            if isinstance(items, dict):
                items = [items]

            for item in items:
                # balance = alpha token amount in rao
                alpha_rao = float(item.get("balance", 0))
                alpha_amount = alpha_rao / 1e9

                # balance_as_tao = TAO equivalent value of those alpha tokens (in rao)
                tao_value_rao = float(item.get("balance_as_tao", alpha_rao))
                tao_value = tao_value_rao / 1e9

                # Get hotkey info
                hotkey_data = item.get("hotkey", {})
                hotkey_ss58 = (
                    hotkey_data.get("ss58", "")
                    if isinstance(hotkey_data, dict)
                    else str(hotkey_data)
                )

                position = {
                    "netuid": item.get("netuid", 0),
                    "hotkey": hotkey_ss58,
                    "stake": tao_value,  # TAO equivalent value (what you get when unstaking)
                    "alpha_balance": alpha_amount,  # Actual alpha tokens held
                    "hotkey_name": item.get("hotkey_name"),
                    "subnet_rank": item.get("subnet_rank"),
                }
                positions.append(position)
                total_stake += tao_value

            return {
                "total_stake": total_stake,
                "positions": positions,
            }

        except Exception as e:
            logger.error(f"Failed to fetch stake balance: {e}")
            return {"total_stake": 0, "positions": []}
