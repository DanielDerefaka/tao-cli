"""Router - Orchestrates intent execution.

Maps LLM intents to actual API calls and btcli commands.
This is the deterministic executor - it takes structured intents
and executes them safely using allowlisted command templates.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from taox.chat.llm_interpreter import IntentType, LLMResponse, Slots, get_interpreter
from taox.commands.executor import BtcliExecutor
from taox.config.settings import get_settings
from taox.data.sdk import BittensorSDK
from taox.data.taostats import TaostatsClient
from taox.ui.console import format_tao

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of executing an intent."""

    success: bool
    message: str  # User-friendly message
    data: Optional[Any] = None  # Raw data if needed
    error: Optional[str] = None


class Router:
    """Routes intents to appropriate handlers."""

    def __init__(
        self,
        taostats: TaostatsClient,
        sdk: BittensorSDK,
        executor: BtcliExecutor,
    ):
        """Initialize router with required clients."""
        self.taostats = taostats
        self.sdk = sdk
        self.executor = executor
        self.settings = get_settings()
        self.interpreter = get_interpreter()

        # Pending confirmation state
        self._pending_confirmation: Optional[LLMResponse] = None

    async def process(self, user_input: str) -> str:
        """Process user input and return response.

        This is the main entry point. It:
        1. Gets LLM interpretation
        2. Executes if ready
        3. Returns natural language response

        Args:
            user_input: What the user typed

        Returns:
            Response to show the user
        """
        # Check if user is confirming a pending action
        if self._pending_confirmation:
            return await self._handle_confirmation(user_input)

        # Get current preferences (may have been updated by SET_CONFIG)
        from taox.chat.state_machine import UserPreferences

        prefs = UserPreferences.load()
        current_wallet = prefs.default_wallet or self.settings.bittensor.default_wallet
        current_hotkey = prefs.default_hotkey or self.settings.bittensor.default_hotkey

        # Get LLM interpretation
        response = self.interpreter.interpret(
            user_input,
            wallet=current_wallet,
            hotkey=current_hotkey,
            network=self.settings.bittensor.network,
        )

        # If needs confirmation, store and return
        if response.needs_confirmation and response.ready_to_execute:
            self._pending_confirmation = response
            return response.reply

        # If not ready to execute (missing info), just return reply
        if not response.ready_to_execute:
            return response.reply

        # Execute the intent
        result = await self._execute(response)

        if result.success:
            return result.message
        else:
            return f"Error: {result.error or result.message}"

    async def _handle_confirmation(self, user_input: str) -> str:
        """Handle user response to confirmation prompt."""
        text = user_input.strip().lower()

        # Check for positive confirmation
        if text in ("yes", "y", "ok", "okay", "confirm", "sure", "go", "do it", "proceed"):
            response = self._pending_confirmation
            self._pending_confirmation = None

            result = await self._execute(response)
            if result.success:
                return result.message
            else:
                return f"Error: {result.error or result.message}"

        # Check for negative
        if text in ("no", "n", "cancel", "stop", "nevermind", "abort"):
            self._pending_confirmation = None
            return "Cancelled. What else can I help with?"

        # Unclear - ask again
        return "Please confirm with 'yes' or 'no'."

    async def _execute(self, response: LLMResponse) -> ExecutionResult:
        """Execute an intent and return result."""
        from taox.chat.state_machine import UserPreferences

        intent = response.intent
        slots = response.slots

        # Resolve wallet/hotkey from user preferences if not in slots
        prefs = UserPreferences.load()
        if not slots.wallet_name:
            slots.wallet_name = prefs.default_wallet or self.settings.bittensor.default_wallet
        if not slots.hotkey_name:
            slots.hotkey_name = prefs.default_hotkey or self.settings.bittensor.default_hotkey

        try:
            if intent == IntentType.BALANCE:
                return await self._exec_balance(slots)

            elif intent == IntentType.PORTFOLIO:
                return await self._exec_portfolio(slots)

            elif intent == IntentType.PRICE:
                return await self._exec_price()

            elif intent == IntentType.VALIDATORS:
                return await self._exec_validators(slots)

            elif intent == IntentType.SUBNETS:
                return await self._exec_subnets()

            elif intent == IntentType.SUBNET_INFO:
                return await self._exec_subnet_info(slots)

            elif intent == IntentType.STAKE:
                return await self._exec_stake(slots)

            elif intent == IntentType.UNSTAKE:
                return await self._exec_unstake(slots)

            elif intent == IntentType.TRANSFER:
                return await self._exec_transfer(slots)

            elif intent == IntentType.REGISTER:
                return await self._exec_register(slots)

            elif intent == IntentType.METAGRAPH:
                return await self._exec_metagraph(slots)

            elif intent == IntentType.HISTORY:
                return await self._exec_history()

            elif intent == IntentType.SET_CONFIG:
                return self._exec_set_config(slots)

            elif intent == IntentType.DOCTOR:
                return await self._exec_doctor()

            elif intent == IntentType.PORTFOLIO_DELTA:
                return await self._exec_portfolio_delta(slots)

            elif intent == IntentType.RECOMMEND:
                return await self._exec_recommend(slots)

            elif intent == IntentType.WATCH:
                return self._exec_watch()

            elif intent == IntentType.REBALANCE:
                return await self._exec_rebalance(slots)

            elif intent == IntentType.HELP:
                return ExecutionResult(success=True, message=self._get_help())

            elif intent == IntentType.GREETING or intent == IntentType.CONVERSATION:
                return ExecutionResult(success=True, message=response.reply)

            else:
                return ExecutionResult(
                    success=True,
                    message=response.reply or "I'm not sure how to help with that.",
                )

        except Exception as e:
            logger.debug(f"Execution failed: {e}", exc_info=True)

            # Give user-friendly error messages
            err = str(e)
            if "does not exist" in err and "coldkey" in err.lower():
                wallet = slots.wallet_name or "default"
                msg = f"Wallet '{wallet}' not found. Check with 'taox wallets' or set your wallet: 'my wallet is <name>'"
            elif "does not exist" in err and "hotkey" in err.lower():
                msg = "Hotkey not found. Set it with: 'my hotkey is <name>'"
            elif "Insufficient" in err or "NotEnoughBalance" in err:
                msg = "Insufficient balance for this operation."
            elif "rate" in err.lower() and "limit" in err.lower():
                msg = "Rate limited. Wait a moment and try again."
            else:
                msg = f"Something went wrong: {err.split(chr(10))[0][:100]}"

            return ExecutionResult(
                success=False,
                message=msg,
                error=err,
            )

    async def _exec_balance(self, slots: Slots) -> ExecutionResult:
        """Execute balance check."""
        wallet_name = slots.wallet_name or self.settings.bittensor.default_wallet
        wallet = self.sdk.get_wallet(name=wallet_name)

        if not wallet:
            return ExecutionResult(
                success=False,
                message=f"Wallet '{wallet_name}' not found.",
            )

        balance = await self.sdk.get_balance_async(wallet.coldkey.ss58_address)

        return ExecutionResult(
            success=True,
            message=f"Balance: {format_tao(balance.free)} free, {format_tao(balance.staked)} staked",
            data=balance,
        )

    async def _exec_portfolio(self, slots: Slots) -> ExecutionResult:
        """Execute portfolio check."""
        from taox.commands.stake import show_portfolio

        wallet_name = slots.wallet_name or self.settings.bittensor.default_wallet
        await show_portfolio(self.taostats, self.sdk, wallet_name=wallet_name)

        return ExecutionResult(success=True, message="Portfolio displayed above.")

    async def _exec_price(self) -> ExecutionResult:
        """Get TAO price."""
        price = await self.taostats.get_price()
        change = "+" if price.change_24h >= 0 else ""

        return ExecutionResult(
            success=True,
            message=f"TAO: ${price.usd:.2f} ({change}{price.change_24h:.1f}% 24h)",
            data=price,
        )

    async def _exec_validators(self, slots: Slots) -> ExecutionResult:
        """List validators."""
        from taox.commands.stake import show_validators

        await show_validators(self.taostats, netuid=slots.netuid)

        return ExecutionResult(success=True, message="Validators displayed above.")

    async def _exec_subnets(self) -> ExecutionResult:
        """List subnets."""
        from taox.commands.subnet import list_subnets

        await list_subnets(self.taostats)

        return ExecutionResult(success=True, message="Subnets displayed above.")

    async def _exec_subnet_info(self, slots: Slots) -> ExecutionResult:
        """Show individual subnet info with token price."""
        from taox.commands.subnet import get_subnet_info_text

        if not slots.netuid:
            return ExecutionResult(
                success=False,
                message="Which subnet? (e.g. 'sn 1' or 'subnet 64')",
            )

        text = await get_subnet_info_text(self.taostats, slots.netuid, brief=slots.price_only)
        return ExecutionResult(success=True, message=text)

    async def _exec_stake(self, slots: Slots) -> ExecutionResult:
        """Execute stake operation."""
        from taox.commands.stake import stake_tao

        if not slots.amount and not slots.amount_all:
            return ExecutionResult(success=False, message="Amount required for staking.")

        await stake_tao(
            executor=self.executor,
            sdk=self.sdk,
            taostats=self.taostats,
            amount=slots.amount or 0,
            validator_name=slots.validator_name,
            validator_ss58=slots.validator_hotkey,
            netuid=slots.netuid or 1,
            wallet_name=slots.wallet_name,
            dry_run=self.settings.demo_mode,
        )

        amount_str = "all" if slots.amount_all else f"{slots.amount} τ"
        return ExecutionResult(
            success=True,
            message=f"Staked {amount_str} to {slots.validator_name or 'validator'}.",
        )

    async def _exec_unstake(self, slots: Slots) -> ExecutionResult:
        """Execute unstake operation."""
        # TODO: Implement full unstake
        return ExecutionResult(
            success=False,
            message="Unstake requires specifying the validator hotkey. Use: 'unstake X TAO from <hotkey>'",
        )

    async def _exec_transfer(self, slots: Slots) -> ExecutionResult:
        """Execute transfer operation."""
        from taox.commands.wallet import transfer_tao

        if not slots.amount:
            return ExecutionResult(success=False, message="Amount required for transfer.")

        if not slots.destination:
            return ExecutionResult(success=False, message="Destination address required.")

        await transfer_tao(
            executor=self.executor,
            sdk=self.sdk,
            amount=slots.amount,
            destination=slots.destination,
            wallet_name=slots.wallet_name,
            dry_run=self.settings.demo_mode,
        )

        return ExecutionResult(
            success=True,
            message=f"Transferred {slots.amount} τ to {slots.destination[:8]}...{slots.destination[-6:]}",
        )

    async def _exec_register(self, slots: Slots) -> ExecutionResult:
        """Execute registration."""
        from taox.commands.register import register_burned

        if not slots.netuid:
            return ExecutionResult(success=False, message="Subnet ID required.")

        success = await register_burned(
            executor=self.executor,
            sdk=self.sdk,
            taostats=self.taostats,
            netuid=slots.netuid,
            wallet_name=slots.wallet_name,
            hotkey_name=slots.hotkey_name,
            dry_run=self.settings.demo_mode,
        )

        if success:
            return ExecutionResult(success=True, message=f"Registered on subnet {slots.netuid}!")
        else:
            return ExecutionResult(success=False, message="Registration cancelled or failed.")

    async def _exec_metagraph(self, slots: Slots) -> ExecutionResult:
        """Show metagraph."""
        from taox.commands.subnet import show_metagraph

        netuid = slots.netuid or 1
        await show_metagraph(self.sdk, self.executor, netuid)

        return ExecutionResult(success=True, message=f"Metagraph for SN{netuid} displayed above.")

    async def _exec_history(self) -> ExecutionResult:
        """Show transaction history."""
        from taox.data.history import show_history

        show_history(limit=20)

        return ExecutionResult(success=True, message="History displayed above.")

    async def _exec_doctor(self) -> ExecutionResult:
        """Run environment health check and return summary."""
        import shutil
        from pathlib import Path

        from taox.security.credentials import CredentialManager

        checks_ok = []
        issues = []

        # Python
        py_ver = f"{__import__('sys').version_info.major}.{__import__('sys').version_info.minor}"
        checks_ok.append(f"Python {py_ver}")

        # btcli
        if shutil.which("btcli"):
            checks_ok.append("btcli installed")
        else:
            issues.append("btcli not found — install with: pip install bittensor-cli")

        # Wallets
        wallet_path = Path.home() / ".bittensor" / "wallets"
        if wallet_path.exists():
            wallets = [w.name for w in wallet_path.iterdir() if w.is_dir()]
            if wallets:
                checks_ok.append(f"{len(wallets)} wallet(s): {', '.join(wallets[:3])}")
            else:
                issues.append("No wallets found")
        else:
            issues.append("No wallet directory found")

        # API keys
        if CredentialManager.get_chutes_key():
            checks_ok.append("Chutes API key configured")
        else:
            issues.append("Chutes API key missing — run 'taox setup'")

        if CredentialManager.get_taostats_key():
            checks_ok.append("Taostats API key configured")
        else:
            issues.append("Taostats API key missing — run 'taox setup'")

        # Network
        try:
            import httpx

            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    "https://entrypoint-finney.opentensor.ai:443",
                    json={"jsonrpc": "2.0", "method": "system_health", "params": [], "id": 1},
                )
                if resp.status_code == 200:
                    checks_ok.append("Finney RPC reachable")
                else:
                    issues.append("Finney RPC returned error")
        except Exception:
            issues.append("Cannot reach Finney RPC")

        # Build response
        parts = []
        if checks_ok:
            parts.append("**Passing:** " + " | ".join(checks_ok))
        if issues:
            parts.append("**Issues:** " + " | ".join(issues))
        else:
            parts.append("All checks passed! Your setup looks good.")

        return ExecutionResult(success=True, message="\n".join(parts))

    async def _exec_portfolio_delta(self, slots: Slots) -> ExecutionResult:
        """Show portfolio change over N days."""
        from taox.data.snapshots import PortfolioSnapshot, PositionSnapshot, get_snapshot_store

        days = slots.days or 7
        wallet_name = slots.wallet_name or self.settings.bittensor.default_wallet

        # Get current portfolio data
        from taox.commands.stake import show_portfolio

        result = await show_portfolio(
            self.taostats,
            self.sdk,
            wallet_name=wallet_name,
            suppress_output=True,
        )

        if not result:
            return ExecutionResult(
                success=False,
                message=f"Could not load portfolio for wallet '{wallet_name}'.",
            )

        # Build and save snapshot
        store = get_snapshot_store()
        from datetime import datetime

        positions = [
            PositionSnapshot(
                netuid=p.get("netuid", 0),
                hotkey=p.get("hotkey", ""),
                validator_name=p.get("hotkey_name"),
                stake=p.get("stake", 0),
                alpha_balance=p.get("alpha_balance", 0),
            )
            for p in result.get("positions", [])
        ]

        snapshot = PortfolioSnapshot(
            timestamp=datetime.now().isoformat(),
            coldkey=result.get("coldkey", ""),
            free_balance=result.get("free_balance", 0),
            total_staked=result.get("staked_total", 0),
            total_value=result.get("total_balance", 0),
            tao_price_usd=result.get("usd_price", 0),
            usd_value=result.get("usd_value", 0),
            positions=positions,
        )

        if snapshot.coldkey:
            store.save_snapshot(snapshot)

        # Compute delta
        delta = store.compute_delta(snapshot.coldkey, days, snapshot)
        if not delta:
            return ExecutionResult(
                success=True,
                message=f"No historical data for {days}d comparison yet. "
                f"Run 'taox portfolio' daily to build history. "
                f"Current value: {result.get('total_balance', 0):,.4f} τ "
                f"(${result.get('usd_value', 0):,.2f})",
            )

        # Build natural language summary
        change_symbol = "+" if delta.total_value_change >= 0 else ""
        parts = [
            f"**Portfolio Change ({days}d):** {change_symbol}{delta.total_value_change:,.4f} τ "
            f"({change_symbol}{delta.total_value_change_percent:.1f}%)",
            f"Free balance: {'+' if delta.free_balance_change >= 0 else ''}{delta.free_balance_change:,.4f} τ",
            f"Staked: {'+' if delta.total_staked_change >= 0 else ''}{delta.total_staked_change:,.4f} τ",
            f"USD: {'+' if delta.usd_value_change >= 0 else ''}${delta.usd_value_change:,.2f}",
        ]

        if delta.best_performer:
            bp = delta.best_performer
            name = bp.validator_name or f"SN{bp.netuid}"
            parts.append(f"Best: {name} (+{bp.stake_change:,.4f} τ)")

        if delta.estimated_rewards > 0:
            parts.append(f"Est. rewards: +{delta.estimated_rewards:,.4f} τ")

        return ExecutionResult(success=True, message="\n".join(parts))

    async def _exec_recommend(self, slots: Slots) -> ExecutionResult:
        """Get staking recommendations."""
        from taox.commands.recommend import stake_recommend

        if not slots.amount:
            return ExecutionResult(
                success=False,
                message="How much TAO would you like recommendations for?",
            )

        await stake_recommend(
            taostats=self.taostats,
            amount=slots.amount,
            netuid=slots.netuid or 1,
        )

        return ExecutionResult(
            success=True,
            message=f"Recommendations for {slots.amount} τ displayed above.",
        )

    def _exec_watch(self) -> ExecutionResult:
        """Show watch/alert info."""
        return ExecutionResult(
            success=True,
            message="Use `taox watch` to set up monitoring:\n"
            '• `taox watch --price ">500"` — TAO price alert\n'
            "• `taox watch --validator taostats` — validator tracking\n"
            "• `taox watch --registration 0.5 --netuid 1` — cheap registration alert\n"
            "• `taox watch --list` — show active alerts",
        )

    async def _exec_rebalance(self, slots: Slots) -> ExecutionResult:
        """Execute batch rebalance."""
        from taox.commands.batch import stake_rebalance

        if not slots.amount:
            return ExecutionResult(
                success=False,
                message="How much TAO to rebalance?",
            )

        await stake_rebalance(
            executor=self.executor,
            sdk=self.sdk,
            taostats=self.taostats,
            amount=slots.amount,
            netuid=slots.netuid or 1,
            wallet_name=slots.wallet_name,
            dry_run=self.settings.demo_mode,
        )

        return ExecutionResult(
            success=True,
            message=f"Rebalanced {slots.amount} τ across top validators.",
        )

    def _exec_set_config(self, slots: Slots) -> ExecutionResult:
        """Update configuration."""
        from taox.chat.state_machine import UserPreferences

        prefs = UserPreferences.load()

        if slots.config_key == "hotkey" and slots.config_value:
            prefs.default_hotkey = slots.config_value
            prefs.save()
            return ExecutionResult(
                success=True,
                message=f"Updated hotkey to **{slots.config_value}**.",
            )

        elif slots.config_key == "wallet" and slots.config_value:
            prefs.default_wallet = slots.config_value
            prefs.save()
            return ExecutionResult(
                success=True,
                message=f"Updated wallet to **{slots.config_value}**.",
            )

        elif slots.netuid:
            prefs.default_netuid = slots.netuid
            prefs.save()
            return ExecutionResult(
                success=True,
                message=f"Updated default subnet to **{slots.netuid}**.",
            )

        return ExecutionResult(
            success=False,
            message="Couldn't update config. Try: 'my hotkey is name' or 'use wallet name'",
        )

    def _get_help(self) -> str:
        """Return help text."""
        return """**What I can do:**

• "what's my balance?" - Check your TAO
• "show my portfolio" - See stake positions
• "my portfolio last 7 days" - See earnings over time
• "how's my setup?" - Run environment check
• "stake 10 TAO to taostats on subnet 1" - Stake
• "where should I stake 100 TAO?" - Get recommendations
• "split 200 TAO across top validators" - Batch stake
• "transfer 5 TAO to 5xxx..." - Send TAO
• "show validators on subnet 1" - List validators
• "list subnets" - Show all subnets
• "register on subnet 24" - Register
• "watch tao price" - Set up alerts
• "my hotkey is dx_hot" - Update settings

Just ask naturally - I'll figure out what you need!"""

    def clear(self):
        """Clear all pending state."""
        self._pending_confirmation = None
        self.interpreter.clear_pending()
