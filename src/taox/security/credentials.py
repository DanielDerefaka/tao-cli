"""Credential management using system keyring."""

import logging
from typing import Optional

try:
    import keyring

    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False


logger = logging.getLogger(__name__)


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

    @classmethod
    def _check_keyring(cls) -> None:
        """Check if keyring is available."""
        if not KEYRING_AVAILABLE:
            raise RuntimeError("keyring package not installed. Install with: pip install keyring")

    @classmethod
    def store(cls, key_name: str, value: str) -> bool:
        """Store a credential in the system keyring.

        Args:
            key_name: Name/identifier for the credential
            value: The credential value to store

        Returns:
            True if successful, False otherwise
        """
        cls._check_keyring()
        try:
            keyring.set_password(cls.SERVICE_NAME, key_name, value)
            logger.info(f"Stored credential: {key_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to store credential {key_name}: {e}")
            return False

    @classmethod
    def get(cls, key_name: str) -> Optional[str]:
        """Retrieve a credential from the system keyring.

        Args:
            key_name: Name/identifier for the credential

        Returns:
            The credential value or None if not found
        """
        cls._check_keyring()
        try:
            value = keyring.get_password(cls.SERVICE_NAME, key_name)
            return value
        except Exception as e:
            logger.error(f"Failed to retrieve credential {key_name}: {e}")
            return None

    @classmethod
    def delete(cls, key_name: str) -> bool:
        """Delete a credential from the system keyring.

        Args:
            key_name: Name/identifier for the credential

        Returns:
            True if successful, False otherwise
        """
        cls._check_keyring()
        try:
            keyring.delete_password(cls.SERVICE_NAME, key_name)
            logger.info(f"Deleted credential: {key_name}")
            return True
        except keyring.errors.PasswordDeleteError:
            logger.warning(f"Credential not found: {key_name}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete credential {key_name}: {e}")
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
