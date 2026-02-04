"""Tests for caching utilities."""

import time
from datetime import datetime, timedelta

import pytest

from taox.data.cache import (
    Cache,
    CacheEntry,
    OfflineManager,
    PersistentCache,
    async_cached,
    cached,
)


class TestCache:
    """Tests for in-memory Cache."""

    def test_set_and_get(self):
        """Test basic set and get operations."""
        cache = Cache(maxsize=10, ttl=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_nonexistent(self):
        """Test getting nonexistent key."""
        cache = Cache()
        assert cache.get("nonexistent") is None

    def test_delete(self):
        """Test deleting a key."""
        cache = Cache()
        cache.set("key1", "value1")
        cache.delete("key1")
        assert cache.get("key1") is None

    def test_clear(self):
        """Test clearing all keys."""
        cache = Cache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_contains(self):
        """Test __contains__ method."""
        cache = Cache()
        cache.set("key1", "value1")
        assert "key1" in cache
        assert "key2" not in cache

    def test_ttl_expiration(self):
        """Test TTL expiration (using short TTL)."""
        cache = Cache(ttl=1)  # 1 second TTL
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        time.sleep(1.5)  # Wait for expiration
        assert cache.get("key1") is None


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_is_expired_fresh(self):
        """Test fresh entry is not expired."""
        entry = CacheEntry(
            value="test",
            created_at=datetime.now().isoformat(),
            ttl=3600,
        )
        assert not entry.is_expired()

    def test_is_expired_old(self):
        """Test old entry is expired."""
        old_time = datetime.now() - timedelta(hours=2)
        entry = CacheEntry(
            value="test",
            created_at=old_time.isoformat(),
            ttl=3600,  # 1 hour TTL
        )
        assert entry.is_expired()


class TestPersistentCache:
    """Tests for PersistentCache."""

    def test_set_and_get(self, tmp_path, monkeypatch):
        """Test persistent cache set and get."""
        # Patch cache directory
        monkeypatch.setattr("taox.data.cache.CACHE_DIR", tmp_path)

        cache = PersistentCache("test_cache", ttl=3600)
        cache.set("key1", {"data": "value1"})
        assert cache.get("key1") == {"data": "value1"}

    def test_persistence(self, tmp_path, monkeypatch):
        """Test cache persists to disk."""
        monkeypatch.setattr("taox.data.cache.CACHE_DIR", tmp_path)

        # Create and populate cache
        cache1 = PersistentCache("test_persist", ttl=3600)
        cache1.set("key1", "value1")

        # Verify file exists
        cache_file = tmp_path / "test_persist.json"
        assert cache_file.exists()

        # Create new instance and verify data loads
        cache2 = PersistentCache.__new__(PersistentCache)
        cache2.name = "test_persist"
        cache2.ttl = 3600
        cache2.cache_file = cache_file
        cache2._memory_cache = {}
        cache2._load()

        assert cache2.get("key1") == "value1"

    def test_get_stale(self, tmp_path, monkeypatch):
        """Test getting stale (expired) entries."""
        monkeypatch.setattr("taox.data.cache.CACHE_DIR", tmp_path)

        cache = PersistentCache("test_stale", ttl=1)
        cache.set("key1", "value1")

        # Manually expire the entry
        old_time = datetime.now() - timedelta(hours=1)
        cache._memory_cache["key1"].created_at = old_time.isoformat()

        # get() should return None
        assert cache.get("key1") is None

        # get_stale() should still return the value
        assert cache.get_stale("key1") == "value1"

    def test_clear(self, tmp_path, monkeypatch):
        """Test clearing persistent cache."""
        monkeypatch.setattr("taox.data.cache.CACHE_DIR", tmp_path)

        cache = PersistentCache("test_clear", ttl=3600)
        cache.set("key1", "value1")

        cache_file = tmp_path / "test_clear.json"
        assert cache_file.exists()

        cache.clear()
        assert cache.get("key1") is None
        assert not cache_file.exists()


class TestOfflineManager:
    """Tests for OfflineManager."""

    def test_singleton(self):
        """Test OfflineManager is a singleton."""
        manager1 = OfflineManager()
        manager2 = OfflineManager()
        assert manager1 is manager2

    def test_set_offline(self):
        """Test setting offline mode."""
        manager = OfflineManager()
        initial = manager.is_offline

        manager.set_offline(True)
        assert manager.is_offline is True

        manager.set_offline(False)
        assert manager.is_offline is False

        # Restore initial state
        manager.set_offline(initial)

    def test_should_check_network(self):
        """Test network check interval."""
        manager = OfflineManager()
        manager._last_check = None

        assert manager.should_check_network() is True

        manager.mark_network_checked()
        assert manager.should_check_network() is False


class TestCachedDecorator:
    """Tests for cached decorator."""

    def test_cached_function(self):
        """Test caching decorator on sync function."""
        cache = Cache(ttl=60)
        call_count = 0

        @cached(cache)
        def expensive_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        # First call - should execute function
        result1 = expensive_func(5)
        assert result1 == 10
        assert call_count == 1

        # Second call - should use cache
        result2 = expensive_func(5)
        assert result2 == 10
        assert call_count == 1  # Still 1, used cache

        # Different argument - should execute function
        result3 = expensive_func(10)
        assert result3 == 20
        assert call_count == 2


@pytest.mark.asyncio
class TestAsyncCachedDecorator:
    """Tests for async_cached decorator."""

    async def test_async_cached_function(self):
        """Test caching decorator on async function."""
        cache = Cache(ttl=60)
        call_count = 0

        @async_cached(cache)
        async def async_expensive_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        # First call - should execute function
        result1 = await async_expensive_func(5)
        assert result1 == 10
        assert call_count == 1

        # Second call - should use cache
        result2 = await async_expensive_func(5)
        assert result2 == 10
        assert call_count == 1  # Still 1, used cache
