# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability in taox, please report it responsibly.

### How to Report

1. **Do NOT open a public GitHub issue** for security vulnerabilities
2. **Email the maintainers** with details of the vulnerability
3. **Include**:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### What to Expect

- **Acknowledgment**: We will acknowledge receipt within 48 hours
- **Assessment**: We will assess the vulnerability and its impact
- **Fix**: We will work on a fix and coordinate disclosure
- **Credit**: We will credit you in the release notes (unless you prefer anonymity)

## Security Best Practices for Users

### API Keys

taox stores API keys securely using your system's keyring:

- **macOS**: Keychain
- **Linux**: Secret Service (GNOME Keyring, KWallet)
- **Windows**: Windows Credential Manager

**Never**:
- Store API keys in config files
- Share your API keys
- Commit API keys to version control

### Wallet Security

taox interacts with Bittensor wallets. Always:

- Keep your wallet passwords strong and unique
- Never share your wallet mnemonics or private keys
- Use a dedicated wallet for testing
- Enable demo mode (`--demo`) when experimenting

### Transaction Safety

taox includes safety features:

1. **Confirmation prompts**: All transactions require explicit confirmation
2. **High-value warnings**: Extra confirmation for amounts >= 10 TAO
3. **Dry-run mode**: Preview commands without executing
4. **Demo mode**: Safe testing with mock data

### Network Security

- taox only communicates with official Bittensor endpoints and Taostats API
- All API communications use HTTPS
- No sensitive data is logged or transmitted unnecessarily

## Security Features

### Built-in Protections

1. **No shell injection**: Commands are executed via subprocess with proper escaping
2. **Input validation**: All user inputs are validated before use
3. **Secure credential storage**: API keys stored in system keyring, not files
4. **Sensitive data filtering**: Passwords and keys are redacted from logs

### Demo Mode

Use demo mode for safe experimentation:

```bash
taox --demo chat
```

This mode:
- Uses mock data instead of live APIs
- Never executes real transactions
- Safe for learning and testing

## Audit

See [docs/AUDIT_REPORT.md](docs/AUDIT_REPORT.md) for the security audit report.
