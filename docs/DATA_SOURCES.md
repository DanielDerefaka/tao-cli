# Data Sources and Grounding

This document explains how taox ensures all responses are grounded in real data with clear source attribution.

## Design Principles

1. **Never state a balance without fetching it** - Every data point comes from a tracked source
2. **Facts vs Assumptions** - Clearly separate retrieved facts from inferred information
3. **Honest Degradation** - When data is unavailable, say so clearly
4. **Source Attribution** - Every response can show where its data came from

## Data Sources

### Live Sources

| Source | Description | Data Types | TTL |
|--------|-------------|------------|-----|
| `BITTENSOR_SDK` | Direct chain queries via Bittensor SDK | Balance, Metagraph | Real-time |
| `TAOSTATS_API` | Taostats REST API | Validators, Subnets, Price | 1-5 min |
| `BTCLI_OUTPUT` | Parsed btcli command output | Transaction results | Real-time |

### Cached Sources

| Source | Description | Use Case |
|--------|-------------|----------|
| `CACHE_FRESH` | Cached data within TTL | Normal operation |
| `CACHE_STALE` | Cached data past TTL | Fallback when API fails |

### Fallback Sources

| Source | Description | When Used |
|--------|-------------|-----------|
| `MOCK_DATA` | Static sample data | Demo mode, no API keys |
| `USER_INPUT` | Values provided by user | Manual entry |
| `UNAVAILABLE` | Data could not be fetched | All sources failed |

## Cache Configuration

### TTL Settings

| Cache | TTL | Rationale |
|-------|-----|-----------|
| Price | 60s | Prices change frequently |
| Balance | 60s | Users expect current balance |
| Validators | 5 min | Validator list is relatively stable |
| Subnets | 5 min | Subnet metadata changes rarely |
| Metagraph | 2 min | Metagraph updates each tempo |

### Persistent Caches

For offline fallback, taox maintains persistent caches in `~/.taox/cache/`:

```
~/.taox/cache/
├── validators.json  (TTL: 1 hour)
├── subnets.json     (TTL: 1 hour)
└── price.json       (TTL: 30 min)
```

These are used when:
- API is temporarily unavailable
- Network is offline
- In backoff due to repeated failures

## Source Attribution

### GroundedData

Every data fetch returns a `GroundedData` object:

```python
@dataclass
class GroundedData(Generic[T]):
    value: T                      # The actual data
    attribution: SourceAttribution # Where it came from
    assumptions: list[str]        # Any assumptions made
```

### Source Labels

When displaying data, sources are shown with human-readable labels:

| Source | Label |
|--------|-------|
| `BITTENSOR_SDK` | "from Bittensor chain" |
| `TAOSTATS_API` | "from Taostats API" |
| `BTCLI_OUTPUT` | "from btcli" |
| `CACHE_FRESH` | "from cache" |
| `CACHE_STALE` | "from cache (stale)" |
| `MOCK_DATA` | "demo data" |

### Example Display

```
Balance: 100.5000 τ (from Bittensor chain)
TAO Price: $450.00 (from cache, 45s ago)
```

## Graceful Degradation

### Degradation Levels

1. **Full Functionality**
   - All API keys configured
   - Network available
   - Data from live sources

2. **Partial Functionality**
   - Missing Taostats key: No validator search, price shows "unavailable"
   - Missing SDK: No direct chain queries, use btcli fallback

3. **Limited Mode**
   - No API keys: Pattern matching only, sample data for display
   - Shows: "Running in limited mode: using pattern matching + no live price"

4. **Offline Mode**
   - Network unavailable: Use cached data with stale markers
   - Shows: "Offline: showing cached data from X minutes ago"

### User Messaging

When data is limited, taox shows clear messages:

```
# No Taostats API key
⚠️ Running in limited mode - run 'taox setup' to configure API keys

# API request failed
⚠️ Could not fetch current price (API error) - showing cached value from 5m ago

# Complete failure
❌ Balance unavailable - check network connection or try 'taox balance --refresh'
```

## Backoff Strategy

When API requests fail, taox uses exponential backoff:

| Failure Count | Delay Before Retry |
|---------------|-------------------|
| 1 | 1 second |
| 2 | 2 seconds |
| 3 | 4 seconds |
| 4 | 8 seconds |
| 5+ | 16 seconds (max 5 min) |

During backoff:
- Cached data is returned with `CACHE_STALE` source
- A note is added: "API in cooldown, using cached data"

## Implementation

### Checking Data Availability

```python
from taox.data.sources import check_data_available

# Check if live data is available
available, message = check_data_available(require_live=True)
if not available:
    console.print(f"[warning]{message}[/warning]")
```

### Getting Grounded Data

```python
from taox.data.taostats import TaostatsClient

client = TaostatsClient()

# Get price with source tracking
grounded_price = await client.get_price_grounded()

if grounded_price.is_available:
    price = grounded_price.value
    source = grounded_price.attribution.to_label()
    console.print(f"Price: ${price.usd} ({source})")
else:
    console.print(f"Price unavailable: {grounded_price.attribution.error_message}")
```

### Formatting Responses with Sources

```python
from taox.data.sources import GroundedResponse

response = GroundedResponse(message="Your balance is 100.5 τ")
response.add_data(grounded_balance)

if grounded_balance.attribution.is_mock:
    response.add_limitation("Showing sample data - configure API for real balance")
    response.add_suggestion("Run 'taox setup' to configure API keys")

# Format with source labels
console.print(response.format(show_sources=True))
```

## Verification

### Never Guess Balances

The system enforces that balances are never stated without fetching:

```python
# ❌ This is NOT allowed
print(f"Your balance is 100 TAO")

# ✅ This IS required
balance_data = await sdk.get_balance_grounded(address)
if balance_data.is_available:
    print(f"Your balance is {balance_data.value.total} τ ({balance_data.attribution.to_label()})")
else:
    print(f"Could not fetch balance: {balance_data.attribution.error_message}")
```

### Testing Data Grounding

```python
# Verify source attribution is present
assert grounded_data.attribution is not None
assert grounded_data.attribution.source != DataSource.UNKNOWN

# Verify assumptions are tracked
if grounded_data.attribution.is_fallback:
    assert len(grounded_data.assumptions) > 0
```

## Configuration

### Enabling/Disabling Source Labels

In `~/.taox/config.yml`:

```yaml
ui:
  show_data_sources: true  # Show "(from Taostats API)" labels
  verbose_sources: false   # Show timestamps in source labels
```

### Demo Mode

When `demo_mode: true` or `--demo` flag:
- All data returns `MOCK_DATA` source
- Clear messaging: "Running in demo mode with sample data"
- No real API calls or transactions
