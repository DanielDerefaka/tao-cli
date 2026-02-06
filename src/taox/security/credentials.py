"""Credential management using system keyring."""

import logging
import os
from pathlib import Path
from typing import Optional

try:
    import keyring

    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False


logger = logging.getLogger(__name__)

# Fallback file for environments where keyring is broken (e.g. WSL)
_FALLBACK_DIR = Path.home() / ".taox"
_FALLBACK_FILE = _FALLBACK_DIR / ".credentials"


class SensitiveDataFilter(logging.Filter):
    """Filter to prevent logging of sensitive data."""

    SENSITIVE_KEYWORDS = [
        "private_key",
        "mnemonic",
        "seed",
        "password",
        "api_key",
        "secret",
        "token",
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter out log records containing sensitive data."""
        msg = str(record.msg).lower()
        args = str(record.args).lower() if record.args else ""
        combined = msg + args

        if any(keyword in combined for keyword in self.SENSITIVE_KEYWORDS):
            record.msg = "[REDACTED - sensitive data]"
            record.args = None
        return True


class CredentialManager:
    """Manages secure storage and retrieval of credentials using system keyring."""

    SERVICE_NAME = "taox"

    # Known credential keys
    CHUTES_API_KEY = "chutes_api_key"
    TAOSTATS_API_KEY = "taostats_api_key"

    # Track whether keyring is known-broken so we only warn once
    _keyring_broken = False
    _keyring_warned = False

    @classmethod
    def _check_keyring(cls) -> None:
        """Check if keyring is available."""
        if not KEYRING_AVAILABLE:
            raise RuntimeError("keyring package not installed. Install with: pip install keyring")

    @classmethod
    def _fallback_get(cls, key_name: str) -> Optional[str]:
        """Read a credential from the fallback file or environment."""
        # Check environment variables first (TAOX_CHUTES_API_KEY, etc.)
        env_key = f"TAOX_{key_name.upper()}"
        env_val = os.environ.get(env_key)
        if env_val:
            return env_val

        # Check fallback file
        if _FALLBACK_FILE.exists():
            try:
                for line in _FALLBACK_FILE.read_text().splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip() == key_name:
                            return v.strip()
            except Exception:
                pass
        return None

    @classmethod
    def _fallback_store(cls, key_name: str, value: str) -> bool:
        """Write a credential to the fallback file."""
        try:
            _FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
            # Read existing entries
            entries: dict[str, str] = {}
            if _FALLBACK_FILE.exists():
                for line in _FALLBACK_FILE.read_text().splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        entries[k.strip()] = v.strip()
            entries[key_name] = value
            _FALLBACK_FILE.write_text("\n".join(f"{k}={v}" for k, v in entries.items()) + "\n")
            _FALLBACK_FILE.chmod(0o600)
            return True
        except Exception as e:
            logger.error(f"Fallback store failed for {key_name}: {e}")
            return False

    @classmethod
    def store(cls, key_name: str, value: str) -> bool:
        """Store a credential in the system keyring (with fallback).

        Args:
            key_name: Name/identifier for the credential
            value: The credential value to store

        Returns:
            True if successful, False otherwise
        """
        if not KEYRING_AVAILABLE or cls._keyring_broken:
            return cls._fallback_store(key_name, value)
        try:
            keyring.set_password(cls.SERVICE_NAME, key_name, value)
            return True
        except BaseException:
            cls._keyring_broken = True
            if not cls._keyring_warned:
                cls._keyring_warned = True
                logger.debug("System keyring unavailable, using file storage")
            return cls._fallback_store(key_name, value)

    @classmethod
    def get(cls, key_name: str) -> Optional[str]:
        """Retrieve a credential from the system keyring (with fallback).

        Args:
            key_name: Name/identifier for the credential

        Returns:
            The credential value or None if not found
        """
        if not KEYRING_AVAILABLE or cls._keyring_broken:
            return cls._fallback_get(key_name)
        try:
            value = keyring.get_password(cls.SERVICE_NAME, key_name)
            if value is not None:
                return value
        except BaseException:
            cls._keyring_broken = True
            if not cls._keyring_warned:
                cls._keyring_warned = True
                logger.debug("System keyring unavailable, using file storage")
        return cls._fallback_get(key_name)

    @classmethod
    def delete(cls, key_name: str) -> bool:
        """Delete a credential from the system keyring.

        Args:
            key_name: Name/identifier for the credential

        Returns:
            True if successful, False otherwise
        """
        if not KEYRING_AVAILABLE or cls._keyring_broken:
            return False
        try:
            keyring.delete_password(cls.SERVICE_NAME, key_name)
            return True
        except BaseException:
            cls._keyring_broken = True
            return False

    @classmethod
    def exists(cls, key_name: str) -> bool:
        """Check if a credential exists in the keyring.

        Args:
            key_name: Name/identifier for the credential

        Returns:
            True if credential exists, False otherwise
        """
        return cls.get(key_name) is not None

    @classmethod
    def get_chutes_key(cls) -> Optional[str]:
        """Get the Chutes API key."""
        return cls.get(cls.CHUTES_API_KEY)

    @classmethod
    def set_chutes_key(cls, key: str) -> bool:
        """Set the Chutes API key."""
        return cls.store(cls.CHUTES_API_KEY, key)

    @classmethod
    def get_taostats_key(cls) -> Optional[str]:
        """Get the Taostats API key."""
        return cls.get(cls.TAOSTATS_API_KEY)

    @classmethod
    def set_taostats_key(cls, key: str) -> bool:
        """Set the Taostats API key."""
        return cls.store(cls.TAOSTATS_API_KEY, key)


def setup_secure_logging() -> None:
    """Configure logging to filter sensitive data."""
    sensitive_filter = SensitiveDataFilter()

    # Add filter to root logger
    root_logger = logging.getLogger()
    root_logger.addFilter(sensitive_filter)

    # Add filter to taox logger
    taox_logger = logging.getLogger("taox")
    taox_logger.addFilter(sensitive_filter)
