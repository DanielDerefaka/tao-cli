"""Pytest configuration and fixtures for taox tests."""

import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

# Set demo mode for tests
os.environ["TAOX_DEMO_MODE"] = "true"


@pytest.fixture
def mock_taostats_client():
    """Mock TaostatsClient for testing."""
    from taox.data.taostats import Validator, Subnet, PriceInfo

    client = MagicMock()
    client.is_available = False

    # Mock validators
    mock_validators = [
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
    ]

    # Mock subnets
    mock_subnets = [
        Subnet(netuid=1, name="Text Prompting", emission=0.15, tempo=360,
               difficulty=1000000, burn_cost=1.5, total_stake=5000000, validators=256),
        Subnet(netuid=18, name="Cortex.t", emission=0.10, tempo=360,
               difficulty=800000, burn_cost=1.2, total_stake=3000000, validators=200),
    ]

    # Mock price
    mock_price = PriceInfo(usd=450.0, change_24h=2.5)

    # Set up async methods
    client.get_validators = AsyncMock(return_value=mock_validators)
    client.search_validator = AsyncMock(return_value=mock_validators[0])
    client.search_validators = AsyncMock(return_value=mock_validators)
    client.get_subnets = AsyncMock(return_value=mock_subnets)
    client.get_subnet = AsyncMock(return_value=mock_subnets[0])
    client.get_price = AsyncMock(return_value=mock_price)
    client.get_stake_balance = AsyncMock(return_value={
        "total_stake": 500.0,
        "positions": [{"netuid": 1, "hotkey": mock_validators[0].hotkey, "stake": 500.0}]
    })
    client.close = AsyncMock()

    return client


@pytest.fixture
def mock_sdk():
    """Mock BittensorSDK for testing."""
    sdk = MagicMock()
    sdk.is_available = False

    # Mock wallet
    mock_wallet = MagicMock()
    mock_wallet.name = "default"
    mock_wallet.coldkey.ss58_address = "5DemoAddress123456789012345678901234567890"
    mock_wallet.hotkey.ss58_address = "5DemoHotkey1234567890123456789012345678901"

    sdk.get_wallet = MagicMock(return_value=mock_wallet)
    sdk.list_wallets = MagicMock(return_value=[
        MagicMock(name="default", coldkey_ss58="5DemoAddress123456789012345678901234567890")
    ])

    # Mock balance
    mock_balance = MagicMock()
    mock_balance.free = 100.0
    mock_balance.staked = 500.0
    mock_balance.total = 600.0

    sdk.get_balance_async = AsyncMock(return_value=mock_balance)

    return sdk


@pytest.fixture
def mock_executor():
    """Mock BtcliExecutor for testing."""
    from taox.commands.executor import CommandResult, ExecutionStatus

    executor = MagicMock()
    executor.run = MagicMock(return_value=CommandResult(
        status=ExecutionStatus.SUCCESS,
        stdout="Command executed successfully",
        stderr="",
        return_code=0,
        command=["btcli", "test"],
    ))
    executor.run_interactive = MagicMock(return_value=CommandResult(
        status=ExecutionStatus.SUCCESS,
        stdout="Command executed successfully",
        stderr="",
        return_code=0,
        command=["btcli", "test"],
    ))
    executor.execute = MagicMock(return_value=CommandResult(
        status=ExecutionStatus.SUCCESS,
        stdout="Command executed successfully",
        stderr="",
        return_code=0,
        command=["btcli", "test"],
    ))
    executor.get_command_string = MagicMock(return_value="btcli test command")

    return executor


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Create a temporary cache directory."""
    cache_dir = tmp_path / ".taox" / "cache"
    cache_dir.mkdir(parents=True)
    return cache_dir


@pytest.fixture
def temp_history_dir(tmp_path):
    """Create a temporary history directory."""
    history_dir = tmp_path / ".taox" / "history"
    history_dir.mkdir(parents=True)
    return history_dir
