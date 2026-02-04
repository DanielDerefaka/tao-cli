"""Caching utilities for taox."""

from typing import TypeVar, Optional, Callable, Any
from functools import wraps
import time

from cachetools import TTLCache


T = TypeVar("T")


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
