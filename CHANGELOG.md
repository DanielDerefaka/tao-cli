# Changelog

All notable changes to taox will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Data source attribution for all responses
- Caching with TTL and exponential backoff
- Graceful degradation when APIs unavailable
- Conversation state machine with slot-filling
- User preferences persistence
- `taox doctor` command for environment diagnostics
- Demo mode for safe experimentation
- Comprehensive test suite

### Changed
- Improved error messages with actionable suggestions
- Enhanced transaction confirmation flow
- Better handling of network failures

### Fixed
- Password handling for btcli commands
- Cache expiration timing
- Validator search accuracy

## [0.1.0] - 2024-01-XX

### Added
- Initial release of taox
- Natural language interface for Bittensor
- Support for core operations:
  - Balance checking
  - Staking and unstaking
  - Validator discovery
  - Subnet information
  - Wallet management
- Integration with Taostats API
- Integration with Chutes AI for LLM
- Rich terminal UI with colors and tables
- Secure credential storage via keyring
- Demo mode for safe testing
- btcli passthrough mode

### Security
- Secure subprocess execution (no shell=True)
- Credential storage in system keyring
- Input validation and sanitization
- Transaction confirmation prompts

[Unreleased]: https://github.com/yourusername/taox/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yourusername/taox/releases/tag/v0.1.0
