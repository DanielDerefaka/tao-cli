#!/usr/bin/env bash
set -euo pipefail

# taox installer
# Usage: curl -fsSL https://raw.githubusercontent.com/DanielDerefaka/tao-cli/main/install.sh | bash

REPO="https://github.com/DanielDerefaka/tao-cli.git"
MIN_PYTHON="3.9"
BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
RESET="\033[0m"

info()  { echo -e "${CYAN}→${RESET} $*"; }
ok()    { echo -e "${GREEN}✓${RESET} $*"; }
warn()  { echo -e "${YELLOW}!${RESET} $*"; }
fail()  { echo -e "${RED}✗${RESET} $*"; exit 1; }

echo ""
echo -e "${BOLD}  ╔════════════════════════════════════╗${RESET}"
echo -e "${BOLD}  ║         ${CYAN}taox${RESET}${BOLD} installer              ║${RESET}"
echo -e "${BOLD}  ║  AI-powered CLI for Bittensor      ║${RESET}"
echo -e "${BOLD}  ╚════════════════════════════════════╝${RESET}"
echo ""

# ── Check Python ──────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        if [ -n "$ver" ]; then
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 9 ]; then
                PYTHON="$cmd"
                break
            fi
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python ${MIN_PYTHON}+ is required but not found. Install it from https://python.org"
fi
ok "Found $PYTHON ($ver)"

# ── Check pip ─────────────────────────────────────────────────
if ! "$PYTHON" -m pip --version &>/dev/null; then
    fail "pip not found. Install it: $PYTHON -m ensurepip --upgrade"
fi
ok "pip available"

# ── Check btcli (optional) ───────────────────────────────────
if command -v btcli &>/dev/null; then
    ok "btcli found"
else
    warn "btcli not found — install it for full functionality:"
    echo "    pip install bittensor-cli"
fi

# ── Install taox ──────────────────────────────────────────────
echo ""
info "Installing taox..."
if "$PYTHON" -m pip install git+"${REPO}" 2>&1 | tail -3; then
    ok "taox installed"
else
    fail "Installation failed. Try manually: pip install git+${REPO}"
fi

# ── Verify install ────────────────────────────────────────────
if ! command -v taox &>/dev/null; then
    # Might be in user-local bin not on PATH
    LOCAL_BIN="$("$PYTHON" -m site --user-base 2>/dev/null)/bin"
    if [ -f "$LOCAL_BIN/taox" ]; then
        warn "taox installed to $LOCAL_BIN which is not on your PATH"
        echo "    Add this to your shell profile:"
        echo "    export PATH=\"$LOCAL_BIN:\$PATH\""
        echo ""
    else
        warn "taox installed but not found on PATH. You may need to restart your shell."
    fi
fi

# ── First-run setup ──────────────────────────────────────────
echo ""
echo -e "${BOLD}────────────────────────────────────────${RESET}"
echo -e "${BOLD}  Quick Setup${RESET}"
echo -e "${BOLD}────────────────────────────────────────${RESET}"
echo ""

# Chutes API key (for AI features)
echo -e "${BOLD}Chutes AI API key${RESET} (powers natural language chat)"
echo "  Get one free at: https://chutes.ai"
echo ""
read -rp "  Chutes API key (Enter to skip): " chutes_key

if [ -n "$chutes_key" ]; then
    "$PYTHON" -c "
import keyring
keyring.set_password('taox', 'chutes_api_key', '$chutes_key')
print('  ✓ Saved to system keyring')
" 2>/dev/null || {
        # Fallback: save via taox config
        warn "Keyring unavailable — you can set it later with: taox setup"
    }
else
    info "Skipped — taox will use pattern matching (no AI chat)"
fi

echo ""

# Taostats API key (for network data)
echo -e "${BOLD}Taostats API key${RESET} (real-time network data)"
echo "  Get one at: https://dash.taostats.io"
echo ""
read -rp "  Taostats API key (Enter to skip): " taostats_key

if [ -n "$taostats_key" ]; then
    "$PYTHON" -c "
import keyring
keyring.set_password('taox', 'taostats_api_key', '$taostats_key')
print('  ✓ Saved to system keyring')
" 2>/dev/null || {
        warn "Keyring unavailable — you can set it later with: taox setup"
    }
else
    info "Skipped — taox will use limited/cached data"
fi

# ── Done ──────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}────────────────────────────────────────${RESET}"
echo -e "${GREEN}${BOLD}  taox is ready!${RESET}"
echo -e "${BOLD}────────────────────────────────────────${RESET}"
echo ""
echo "  Get started:"
echo "    taox              # wallet setup + overview"
echo "    taox chat         # start chatting"
echo "    taox doctor       # verify your environment"
echo "    taox --demo chat  # try without real transactions"
echo ""
echo "  Reconfigure anytime:"
echo "    taox setup        # API keys"
echo "    taox welcome      # wallet selection"
echo ""
