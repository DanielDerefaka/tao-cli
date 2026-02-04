"""Configuration management for taox using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseModel):
    """LLM configuration."""

    model_config = ConfigDict(extra="ignore")

    provider: str = "chutes"
    model: str = "unsloth/Mistral-Nemo-Instruct-2407"  # 12B, natural conversational style
    temperature: float = 0.7
    max_tokens: int = 1000
    base_url: str = "https://llm.chutes.ai/v1"


class BittensorSettings(BaseModel):
    """Bittensor network configuration."""

    model_config = ConfigDict(extra="ignore")

    network: str = "finney"
    wallet_path: str = "~/.bittensor/wallets"
    default_wallet: str = "default"
    default_hotkey: str = "default"
    multi_wallet_mode: bool = False
    available_wallets: list[str] = Field(default_factory=list)


class TaostatsSettings(BaseModel):
    """Taostats API configuration."""

    model_config = ConfigDict(extra="ignore")

    base_url: str = "https://api.taostats.io/api"


class UISettings(BaseModel):
    """UI configuration."""

    model_config = ConfigDict(extra="ignore")

    theme: str = "dark"
    confirm_large_tx: bool = True
    large_tx_threshold: float = 10.0


class SecuritySettings(BaseModel):
    """Security configuration."""

    model_config = ConfigDict(extra="ignore")

    require_confirmation: bool = True
    mask_addresses: bool = False


class Settings(BaseSettings):
    """Main taox configuration.

    Configuration is loaded from:
    1. Environment variables (TAOX_* prefix)
    2. Config file (~/.taox/config.yml)
    3. Default values
    """

    model_config = SettingsConfigDict(
        env_prefix="TAOX_",
        env_nested_delimiter="__",
        extra="ignore",  # Ignore extra fields in config file
    )

    # Feature flags
    demo_mode: bool = Field(default=False, description="Run in demo mode without real API calls")
    onboarding_complete: bool = Field(
        default=False, description="Whether onboarding has been completed"
    )

    # Nested settings
    llm: LLMSettings = Field(default_factory=LLMSettings)
    bittensor: BittensorSettings = Field(default_factory=BittensorSettings)
    taostats: TaostatsSettings = Field(default_factory=TaostatsSettings)
    ui: UISettings = Field(default_factory=UISettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)


def get_config_path() -> Path:
    """Get the config file path."""
    return Path.home() / ".taox" / "config.yml"


def load_config_file() -> dict:
    """Load configuration from YAML file if it exists."""
    config_path = get_config_path()
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


def save_config_file(config: dict) -> None:
    """Save configuration to YAML file."""
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, default_flow_style=False)


def create_default_config() -> None:
    """Create a default config file if it doesn't exist."""
    config_path = get_config_path()
    if not config_path.exists():
        default_config = {
            "demo_mode": False,
            "llm": {
                "provider": "chutes",
                "model": "unsloth/Mistral-Nemo-Instruct-2407",
                "temperature": 0.7,
                "max_tokens": 1000,
                "base_url": "https://llm.chutes.ai/v1",
            },
            "bittensor": {
                "network": "finney",
                "wallet_path": "~/.bittensor/wallets",
                "default_wallet": "default",
                "default_hotkey": "default",
            },
            "taostats": {
                "base_url": "https://api.taostats.io/api",
            },
            "ui": {
                "theme": "dark",
                "confirm_large_tx": True,
                "large_tx_threshold": 10.0,
            },
            "security": {
                "require_confirmation": True,
                "mask_addresses": False,
            },
        }
        save_config_file(default_config)


@lru_cache
def get_settings() -> Settings:
    """Get the application settings (cached).

    Loads from environment variables and config file.
    """
    # Load file config first
    file_config = load_config_file()

    # Create settings with file config as initial values
    # Environment variables will override
    return Settings(**file_config)


def reset_settings_cache() -> None:
    """Clear the settings cache to reload configuration."""
    get_settings.cache_clear()
