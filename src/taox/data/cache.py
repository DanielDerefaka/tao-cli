"""Caching utilities for taox with source tracking and backoff.

This module provides:
- TTL-based caching with age tracking
- Stale-while-revalidate pattern
- Exponential backoff for failed requests
- Source attribution integration
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TypeVar, Optional, Callable, Any, Tuple
from functools import wraps
from dataclasses import dataclass, asdict, field
from enum import Enum

from cachetools import TTLCache


logger = logging.getLogger(__name__)
T = TypeVar("T")


class CacheStatus(str, Enum):
    """Status of a cache lookup."""
    HIT_FRESH = "hit_fresh"  # Cache hit within TTL
    HIT_STALE = "hit_stale"  # Cache hit but past TTL (usable as fallback)
    MISS = "miss"  # Cache miss
    ERROR = "error"  # Error accessing cache


# Persistent cache directory
CACHE_DIR = Path.home() / ".taox" / "cache"


@dataclass
class CacheEntry:
    """A cached entry with timestamp and TTL."""
    value: Any
    created_at: str
    ttl: int
    source: str = "unknown"  # Data source for attribution

    def is_expired(self) -> bool:
        """Check if this entry has expired."""
        created = datetime.fromisoformat(self.created_at)
        age = (datetime.now() - created).total_seconds()
        return age > self.ttl

    def age_seconds(self) -> float:
        """Get the age of this entry in seconds."""
        created = datetime.fromisoformat(self.created_at)
        return (datetime.now() - created).total_seconds()

    def get_status(self) -> CacheStatus:
        """Get the status of this cache entry."""
        if self.is_expired():
            return CacheStatus.HIT_STALE
        return CacheStatus.HIT_FRESH


@dataclass
class CacheResult:
    """Result of a cache lookup with metadata."""
    value: Any
    status: CacheStatus
    age_seconds: Optional[float] = None
    source: str = "cache"

    @property
    def is_fresh(self) -> bool:
        """Check if this is a fresh cache hit."""
        return self.status == CacheStatus.HIT_FRESH

    @property
    def is_stale(self) -> bool:
        """Check if this is a stale cache hit."""
        return self.status == CacheStatus.HIT_STALE

    @property
    def is_miss(self) -> bool:
        """Check if this was a cache miss."""
        return self.status == CacheStatus.MISS


class PersistentCache:
    """File-backed persistent cache for offline mode."""

    def __init__(self, name: str, ttl: int = 3600):
        """Initialize persistent cache.

        Args:
            name: Cache name (used as filename)
            ttl: Time-to-live in seconds (default 1 hour)
        """
        self.name = name
        self.ttl = ttl
        self.cache_file = CACHE_DIR / f"{name}.json"
        self._memory_cache: dict[str, CacheEntry] = {}
        self._load()

    def _ensure_dir(self) -> None:
        """Ensure cache directory exists."""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        """Load cache from disk."""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, "r") as f:
                    data = json.load(f)
                    for key, entry_data in data.items():
                        entry = CacheEntry(**entry_data)
                        if not entry.is_expired():
                            self._memory_cache[key] = entry
                logger.debug(f"Loaded {len(self._memory_cache)} entries from {self.name} cache")
        except Exception as e:
            logger.warning(f"Failed to load cache {self.name}: {e}")
            self._memory_cache = {}

    def _save(self) -> None:
        """Save cache to disk."""
        try:
            self._ensure_dir()
            # Filter expired entries before saving
            valid_entries = {
                k: asdict(v) for k, v in self._memory_cache.items()
                if not v.is_expired()
            }
            with open(self.cache_file, "w") as f:
                json.dump(valid_entries, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cache {self.name}: {e}")

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        entry = self._memory_cache.get(key)
        if entry is None:
            return None
        if entry.is_expired():
            # Don't delete - keep for get_stale() fallback
            return None
        return entry.value

    def set(self, key: str, value: Any) -> None:
        """Set value in cache."""
        self._memory_cache[key] = CacheEntry(
            value=value,
            created_at=datetime.now().isoformat(),
            ttl=self.ttl,
        )
        self._save()

    def get_stale(self, key: str) -> Optional[Any]:
        """Get value even if expired (for offline fallback)."""
        entry = self._memory_cache.get(key)
        if entry is None:
            return None
        return entry.value

    def get_with_metadata(self, key: str) -> CacheResult:
        """Get value with full metadata about cache status.

        Args:
            key: Cache key

        Returns:
            CacheResult with value, status, and age
        """
        entry = self._memory_cache.get(key)

        if entry is None:
            return CacheResult(value=None, status=CacheStatus.MISS)

        return CacheResult(
            value=entry.value,
            status=entry.get_status(),
            age_seconds=entry.age_seconds(),
            source=entry.source,
        )

    def set_with_source(self, key: str, value: Any, source: str = "unknown") -> None:
        """Set value with source attribution.

        Args:
            key: Cache key
            value: Value to cache
            source: Data source for attribution
        """
        self._memory_cache[key] = CacheEntry(
            value=value,
            created_at=datetime.now().isoformat(),
            ttl=self.ttl,
            source=source,
        )
        self._save()

    def clear(self) -> None:
        """Clear all cached values."""
        self._memory_cache = {}
        if self.cache_file.exists():
            self.cache_file.unlink()

    def __contains__(self, key: str) -> bool:
        entry = self._memory_cache.get(key)
        return entry is not None and not entry.is_expired()


class OfflineManager:
    """Manages offline mode detection and fallback behavior."""

    _instance: Optional["OfflineManager"] = None
    _is_offline: bool = False
    _last_check: Optional[datetime] = None
    _check_interval: int = 30  # seconds

    def __new__(cls) -> "OfflineManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def is_offline(self) -> bool:
        """Check if we're in offline mode."""
        return self._is_offline

    def set_offline(self, offline: bool = True) -> None:
        """Set offline mode."""
        if offline != self._is_offline:
            self._is_offline = offline
            status = "offline" if offline else "online"
            logger.info(f"Network status changed to: {status}")

    def should_check_network(self) -> bool:
        """Check if we should test network connectivity."""
        if self._last_check is None:
            return True
        age = (datetime.now() - self._last_check).total_seconds()
        return age > self._check_interval

    def mark_network_checked(self) -> None:
        """Mark that we checked network connectivity."""
        self._last_check = datetime.now()

    async def check_connectivity(self) -> bool:
        """Check if network is available.

        Returns:
            True if online, False if offline
        """
        import httpx

        if not self.should_check_network():
            return not self._is_offline

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Try to reach a reliable endpoint
                response = await client.get("https://api.taostats.io/api/health")
                self.set_offline(False)
                self.mark_network_checked()
                return True
        except Exception:
            self.set_offline(True)
            self.mark_network_checked()
            return False


# Global offline manager
offline_manager = OfflineManager()


class BackoffManager:
    """Manages exponential backoff for failed API requests.

    Tracks failure counts per endpoint and calculates appropriate
    wait times before retrying.
    """

    def __init__(
        self,
        initial_delay: float = 1.0,
        max_delay: float = 300.0,
        multiplier: float = 2.0,
    ):
        """Initialize the backoff manager.

        Args:
            initial_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds
            multiplier: Multiplier for exponential backoff
        """
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self._failures: dict[str, int] = {}
        self._last_failure: dict[str, datetime] = {}

    def record_failure(self, key: str) -> None:
        """Record a failure for a key."""
        self._failures[key] = self._failures.get(key, 0) + 1
        self._last_failure[key] = datetime.now()
        logger.debug(f"Recorded failure for {key}, count: {self._failures[key]}")

    def record_success(self, key: str) -> None:
        """Record a success, resetting the failure count."""
        if key in self._failures:
            del self._failures[key]
        if key in self._last_failure:
            del self._last_failure[key]

    def get_delay(self, key: str) -> float:
        """Get the current delay for a key.

        Args:
            key: The key to check

        Returns:
            Delay in seconds (0 if no delay needed)
        """
        failures = self._failures.get(key, 0)
        if failures == 0:
            return 0.0

        delay = self.initial_delay * (self.multiplier ** (failures - 1))
        return min(delay, self.max_delay)

    def should_retry(self, key: str) -> bool:
        """Check if enough time has passed to retry.

        Args:
            key: The key to check

        Returns:
            True if retry is allowed
        """
        if key not in self._last_failure:
            return True

        delay = self.get_delay(key)
        elapsed = (datetime.now() - self._last_failure[key]).total_seconds()
        return elapsed >= delay

    def get_retry_after(self, key: str) -> Optional[float]:
        """Get seconds until retry is allowed.

        Args:
            key: The key to check

        Returns:
            Seconds until retry, or None if retry is allowed now
        """
        if self.should_retry(key):
            return None

        delay = self.get_delay(key)
        elapsed = (datetime.now() - self._last_failure[key]).total_seconds()
        return max(0, delay - elapsed)


# Global backoff manager
backoff_manager = BackoffManager()

# Persistent caches for offline mode
persistent_validator_cache = PersistentCache("validators", ttl=3600)
persistent_subnet_cache = PersistentCache("subnets", ttl=3600)
persistent_price_cache = PersistentCache("price", ttl=1800)


class Cache:
    """Simple TTL cache wrapper for API responses."""

    def __init__(self, maxsize: int = 100, ttl: int = 300):
        """Initialize the cache.

        Args:
            maxsize: Maximum number of items to cache
            ttl: Time-to-live in seconds (default 5 minutes)
        """
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)

    def get(self, key: str) -> Optional[Any]:
        """Get a value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        return self._cache.get(key)

    def set(self, key: str, value: Any) -> None:
        """Set a value in cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        self._cache[key] = value

    def delete(self, key: str) -> None:
        """Delete a value from cache.

        Args:
            key: Cache key
        """
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached values."""
        self._cache.clear()

    def __contains__(self, key: str) -> bool:
        """Check if key is in cache."""
        return key in self._cache


def cached(cache: Cache, key_func: Optional[Callable[..., str]] = None):
    """Decorator for caching function results.

    Args:
        cache: Cache instance to use
        key_func: Function to generate cache key from args (default uses str of args)

    Returns:
        Decorated function
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # Generate cache key
            if key_func:
                key = key_func(*args, **kwargs)
            else:
                key = f"{func.__name__}:{args}:{kwargs}"

            # Try to get from cache
            result = cache.get(key)
            if result is not None:
                return result

            # Call function and cache result
            result = func(*args, **kwargs)
            cache.set(key, result)
            return result

        return wrapper

    return decorator


def async_cached(cache: Cache, key_func: Optional[Callable[..., str]] = None):
    """Decorator for caching async function results.

    Args:
        cache: Cache instance to use
        key_func: Function to generate cache key from args

    Returns:
        Decorated async function
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            if key_func:
                key = key_func(*args, **kwargs)
            else:
                key = f"{func.__name__}:{args}:{kwargs}"

            result = cache.get(key)
            if result is not None:
                return result

            result = await func(*args, **kwargs)
            cache.set(key, result)
            return result

        return wrapper

    return decorator


# Global caches for different data types
validator_cache = Cache(maxsize=200, ttl=300)  # 5 minutes
subnet_cache = Cache(maxsize=100, ttl=300)
balance_cache = Cache(maxsize=50, ttl=60)  # 1 minute
metagraph_cache = Cache(maxsize=50, ttl=120)  # 2 minutes
price_cache = Cache(maxsize=10, ttl=60)  # 1 minute
