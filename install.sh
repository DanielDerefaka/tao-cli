#!/usr/bin/env bash
set -euo pipefail

# taox installer
# Usage: curl -fsSL https://raw.githubusercontent.com/DanielDerefaka/tao-cli/main/install.sh | bash

REPO="https://github.com/DanielDerefaka/tao-cli.git"
MIN_PYTHON="3.9"
TAOX_DIR="$HOME/.taox"
VENV_DIR="$TAOX_DIR/venv"
CRED_FILE="$TAOX_DIR/.credentials"

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

# ── Check venv module ────────────────────────────────────────
if ! "$PYTHON" -m venv --help &>/dev/null 2>&1; then
    warn "Python venv module missing. Installing..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y "python${ver}-venv" 2>/dev/null || sudo apt-get install -y python3-venv 2>/dev/null || true
    fi
fi

# ── Create venv ──────────────────────────────────────────────
echo ""
info "Setting up taox environment..."
mkdir -p "$TAOX_DIR"

if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON" -m venv "$VENV_DIR" 2>/dev/null || {
        # If venv fails, fall back to --user install
        warn "Could not create virtual environment, using --user install"
        VENV_DIR=""
    }
fi

if [ -n "$VENV_DIR" ]; then
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    PIP="$VENV_DIR/bin/pip"
    ok "Virtual environment ready"
else
    PIP="$PYTHON -m pip"
fi

# ── Install taox ──────────────────────────────────────────────
info "Installing taox..."
if [ -n "$VENV_DIR" ]; then
    if $PIP install "git+${REPO}" 2>&1 | tail -3; then
        ok "taox installed"
    else
        fail "Installation failed. Try manually: pip install git+${REPO}"
    fi
else
    if $PIP install --user "git+${REPO}" 2>&1 | tail -3; then
        ok "taox installed"
    else
        fail "Installation failed. Try manually: pip install --user git+${REPO}"
    fi
fi

# ── Install cffi (fixes WSL/Linux keyring issues) ────────────
if [ -n "$VENV_DIR" ]; then
    $PIP install cffi cryptography 2>/dev/null | tail -1 || true
else
    $PIP install --user cffi cryptography 2>/dev/null | tail -1 || true
fi

# ── Create wrapper script ───────────────────────────────────
# If installed in a venv, create a wrapper so `taox` works globally
if [ -n "$VENV_DIR" ]; then
    WRAPPER="$HOME/.local/bin/taox"
    mkdir -p "$HOME/.local/bin"
    cat > "$WRAPPER" << 'WRAPPER_EOF'
#!/usr/bin/env bash
source "$HOME/.taox/venv/bin/activate" 2>/dev/null
exec "$HOME/.taox/venv/bin/taox" "$@"
WRAPPER_EOF
    chmod +x "$WRAPPER"
    ok "Created taox command"
fi

# ── Verify install ────────────────────────────────────────────
TAOX_BIN=""
if command -v taox &>/dev/null; then
    TAOX_BIN="taox"
elif [ -f "$HOME/.local/bin/taox" ]; then
    TAOX_BIN="$HOME/.local/bin/taox"
fi

if [ -z "$TAOX_BIN" ]; then
    warn "taox installed but not on PATH. Add this to your shell profile:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
    echo "  Then restart your shell or run:"
    echo "    source ~/.bashrc"
fi

# ── First-run setup ──────────────────────────────────────────
echo ""
echo -e "${BOLD}────────────────────────────────────────${RESET}"
echo -e "${BOLD}  Quick Setup${RESET}"
echo -e "${BOLD}────────────────────────────────────────${RESET}"
echo ""

save_credential() {
    local key="$1"
    local value="$2"
    mkdir -p "$TAOX_DIR"
    # Remove old entry if exists, then append
    if [ -f "$CRED_FILE" ]; then
        grep -v "^${key}=" "$CRED_FILE" > "$CRED_FILE.tmp" 2>/dev/null || true
        mv "$CRED_FILE.tmp" "$CRED_FILE"
    fi
    echo "${key}=${value}" >> "$CRED_FILE"
    chmod 600 "$CRED_FILE"
}

# Chutes API key
echo -e "${BOLD}Chutes AI API key${RESET} (powers natural language chat)"
echo "  Get one free at: https://chutes.ai"
echo ""
read -rp "  Chutes API key (Enter to skip): " chutes_key

if [ -n "$chutes_key" ]; then
    save_credential "chutes_api_key" "$chutes_key"
    ok "Saved Chutes API key"
else
    info "Skipped — taox will use pattern matching (no AI chat)"
fi

echo ""

# Taostats API key
echo -e "${BOLD}Taostats API key${RESET} (real-time network data)"
echo "  Get one at: https://dash.taostats.io"
echo ""
read -rp "  Taostats API key (Enter to skip): " taostats_key

if [ -n "$taostats_key" ]; then
    save_credential "taostats_api_key" "$taostats_key"
    ok "Saved Taostats API key"
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
if [ -z "$TAOX_BIN" ]; then
    echo -e "  ${YELLOW}Don't forget to add ~/.local/bin to your PATH first!${RESET}"
    echo ""
fi
