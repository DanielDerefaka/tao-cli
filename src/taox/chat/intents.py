"""Intent classification and entity extraction for taox."""

import contextlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class IntentType(str, Enum):
    """Types of user intents that taox can handle."""

    STAKE = "stake"
    UNSTAKE = "unstake"
    TRANSFER = "transfer"
    BALANCE = "balance"
    PORTFOLIO = "portfolio"
    METAGRAPH = "metagraph"
    REGISTER = "register"
    INFO = "info"
    VALIDATORS = "validators"
    SUBNETS = "subnets"
    SUBNET_INFO = "subnet_info"  # Individual subnet lookup (price, details)
    PRICE = "price"  # TAO price check
    HISTORY = "history"  # Transaction history
    SET_CONFIG = "set_config"  # Update settings like hotkey, wallet
    DOCTOR = "doctor"  # Environment health check
    PORTFOLIO_DELTA = "portfolio_delta"  # Portfolio change over time
    RECOMMEND = "recommend"  # Staking recommendations
    WATCH = "watch"  # Price/validator alerts
    REBALANCE = "rebalance"  # Batch stake across validators
    CREATE_WALLET = "create_wallet"  # Create new coldkey/hotkey
    HELP = "help"
    CONFIRM = "confirm"  # User confirming something
    GREETING = "greeting"  # Hello, hi, etc.
    UNKNOWN = "unknown"


@dataclass
class Intent:
    """Represents a parsed user intent with extracted entities."""

    type: IntentType
    raw_input: str
    confidence: float = 1.0

    # Extracted entities
    amount: Optional[float] = None
    amount_all: bool = False  # True if user said "all" for amount
    validator_name: Optional[str] = None
    validator_ss58: Optional[str] = None
    netuid: Optional[int] = None
    destination: Optional[str] = None
    wallet_name: Optional[str] = None
    hotkey_name: Optional[str] = None

    # Additional context
    extra: dict = field(default_factory=dict)

    def __str__(self) -> str:
        parts = [f"Intent({self.type.value}"]
        if self.amount is not None:
            parts.append(f", amount={self.amount}")
        if self.amount_all:
            parts.append(", amount=ALL")
        if self.validator_name:
            parts.append(f", validator={self.validator_name}")
        if self.netuid is not None:
            parts.append(f", netuid={self.netuid}")
        if self.destination:
            parts.append(f", dest={self.destination[:16]}...")
        parts.append(")")
        return "".join(parts)


class MockIntentParser:
    """Pattern-based intent parser for demo/mock mode.

    Uses regex to extract intents without requiring an LLM.
    """

    # Patterns for intent detection (ORDER MATTERS — checked top to bottom)
    PATTERNS = {
        # CREATE_WALLET MUST be before SET_CONFIG
        # (prevents "create wallet jeff" from matching set_config)
        IntentType.CREATE_WALLET: [
            # "create wallet jeff", "create a wallet named jeff"
            r"(?:create|make|add|new)\s+(?:a\s+)?(?:new\s+)?(?:wallet|coldkey)\s+(?:named?\s+)?(\w+)",
            # "create wallet jeff hotkey jeff_hot"
            r"(?:create|make|add|new)\s+(?:a\s+)?(?:new\s+)?(?:wallet|coldkey)\s+(?:named?\s+)?(\w+)\s+(?:and\s+)?hotkey\s+(\w+)",
            # "create another wallet coldkey name jeff hotkey jeff_hot"
            r"(?:create|make|add|new)\s+(?:another\s+)?(?:wallet|coldkey).*?(?:name|named?)\s+(\w+).*?hotkey\s+(\w+)",
            # "create coldkey jeff and hotkey jeff_hot"
            r"(?:create|make|add|new)\s+(?:a\s+)?(?:new\s+)?coldkey\s+(\w+)\s+(?:and\s+)?(?:a\s+)?(?:new\s+)?hotkey\s+(\w+)",
            # "new wallet jeff"
            r"new\s+(?:wallet|coldkey)\s+(\w+)",
            # "create hotkey jeff_hot" (hotkey only, for existing wallet)
            r"(?:create|make|add|new)\s+(?:a\s+)?(?:new\s+)?hotkey\s+(\w+)",
        ],
        # Config MUST be before VALIDATORS (prevents "set wallet to validator" misfire)
        IntentType.SET_CONFIG: [
            # Wallet/coldkey patterns — require explicit set/change/is verbs
            r"(?:my |the )?(?:wallet|coldkey)\s+(?:is|should be|=)\s+(\w+)",
            r"(?:set|use|change)\s+(?:my\s+)?(?:wallet|coldkey)\s+(?:to\s+)?(\w+)",
            # Hotkey patterns — require explicit set/change/is verbs
            r"(?:my |the )?hotkey\s+(?:is|should be|=)\s+(\w+)",
            r"(?:set|use|change)\s+(?:my\s+)?hotkey\s+(?:to\s+)?(\w+)",
            # Generic "using" pattern
            r"(?:i(?:'m| am)\s+)?using\s+(?:hotkey|wallet|coldkey)\s+(\w+)",
        ],
        IntentType.STAKE: [
            r"stake\s+(\d+(?:\.\d+)?)\s*(?:tao)?\s*(?:to\s+)?(.+?)(?:\s+on\s+(?:subnet\s*)?(\d+))?$",
            r"add\s+stake\s+(\d+(?:\.\d+)?)",
            r"delegate\s+(\d+(?:\.\d+)?)",
        ],
        IntentType.UNSTAKE: [
            r"unstake\s+(\d+(?:\.\d+)?)\s*(?:tao)?",
            r"remove\s+stake\s+(\d+(?:\.\d+)?)",
            r"withdraw\s+(\d+(?:\.\d+)?)",
        ],
        IntentType.TRANSFER: [
            r"transfer\s+(\d+(?:\.\d+)?)\s*(?:tao)?",
            r"send\s+(\d+(?:\.\d+)?)\s*(?:tao)?",
            r"(?:can you |please )?(?:send|transfer)\s+(\d+(?:\.\d+)?)",
        ],
        IntentType.BALANCE: [
            r"balance",
            r"how much (?:tao )?(?:do i have|balance)",
            r"what(?:'s| is) my balance",
            r"check balance",
            r"show balance",
            r"how many tao",
            r"my tao",
            r"tao balance",
            r"what do i have",
            r"show me (?:my )?(?:tao|balance)",
        ],
        IntentType.PORTFOLIO: [
            r"portfolio",
            r"show (?:my )?(?:stake|positions)",
            r"what(?:'s| is| are) my (?:stake|positions)",
            r"list (?:my )?stakes?",
        ],
        IntentType.METAGRAPH: [
            r"metagraph\s*(?:for\s+)?(?:subnet\s*)?(\d+)?",
            r"show metagraph",
        ],
        IntentType.VALIDATORS: [
            r"(?:show |list |top )?validators?\s*(?:on\s+)?(?:subnet\s*)?(\d+)?",
            r"who (?:are|is) the (?:top |best )?validators?",
        ],
        IntentType.REGISTER: [
            r"register\s+(?:me\s+)?(?:on\s+)?(?:subnet\s*|sn\s*)(\d+)",
            r"register\s*(?:on\s+)?(?:subnet\s*|sn\s*)(\d+)",
            r"register\s+(?:me\s+)?(?:on\s+)?(\d+)",
            r"(?:i\s+)?(?:want\s+to\s+)?register(?:\s+(?:me\s+)?(?:on\s+)?(?:a\s+)?subnet)?",
            r"join\s+(?:a\s+)?(?:subnet|sn)",
        ],
        # SUBNET_INFO must be before SUBNETS and PRICE
        # (catches "sn 100 price" as subnet info, not TAO price)
        IntentType.SUBNET_INFO: [
            # "what's sn 100", "whats subnet 64", "what is sn 1"
            r"what(?:'?s| is)\s+(?:subnet\s*|sn\s*)(\d+)",
            # "sn 100 price", "subnet 64 price", "price of sn 100"
            r"(?:subnet\s*|sn\s*)(\d+)\s+(?:price|cost|value|token)",
            r"(?:the\s+)?price\s+(?:of\s+)?(?:subnet\s*|sn\s*)(\d+)",
            # "whats the price of sn 100"
            r"what(?:'?s| is)\s+(?:the\s+)?price\s+(?:of\s+)?(?:subnet\s*|sn\s*)(\d+)",
            # "tell me about subnet 1", "info on sn 64"
            r"(?:tell me |info |details? )?(?:about|on|for)\s+(?:subnet\s*|sn\s*)(\d+)",
            # "subnet 100 info", "sn 64 details"
            r"(?:subnet\s*|sn\s*)(\d+)\s+(?:info|details?|data|stats)",
            # "show subnet 1" (specific ID = info, not list)
            r"(?:show|check|get|look up)\s+(?:subnet\s*|sn\s*)(\d+)",
            # Bare "sn 100" or "subnet 64" (just a number after sn/subnet)
            r"^(?:subnet\s*|sn\s*)(\d+)$",
        ],
        IntentType.SUBNETS: [
            r"(?:show |list )(?:\w+\s+)*subnets?",
            r"^subnets?$",
            r"what subnets",
        ],
        IntentType.PRICE: [
            r"(?:what(?:'s| is) (?:the )?)?(?:tao |bittensor )?price",
            r"(?:how much (?:is|does) )?tao (?:cost|worth|price)",
            r"(?:tao|bittensor) (?:price|value|cost)",
            r"price (?:of )?(?:tao|bittensor)",
            r"^price$",
        ],
        IntentType.HISTORY: [
            r"(?:view |show |list |get )?(?:my )?(?:transaction |tx )?history",
            r"(?:recent |past |my )?transactions?",
            r"what (?:have i|did i) (?:done|sent|transferred|staked)",
            r"(?:show |list )?(?:my )?(?:recent )?(?:activity|actions)",
        ],
        IntentType.DOCTOR: [
            r"doctor",
            r"(?:check|diagnose|verify)\s+(?:my\s+)?(?:setup|environment|env|config)",
            r"(?:how(?:'?s| is) )?(?:my )?(?:setup|environment|taox|config)",
            r"(?:is )?(?:everything|my setup)\s+(?:ok|good|working|fine|ready)",
            r"health\s*check",
            r"what(?:'?s| is) (?:the )?(?:state|status) of (?:my )?(?:taox|setup|environment)",
            r"am i (?:set up|ready|configured)",
        ],
        IntentType.PORTFOLIO_DELTA: [
            r"portfolio\s+(?:last|past|in the last)\s+(\d+)\s*(?:d|day)",
            r"(?:my )?portfolio\s+(?:change|delta|diff)\s*(?:(\d+)\s*d)?",
            r"(?:how(?:'?s| is|'s) )?(?:my )?portfolio\s+(?:doing|changed|looking)\s+(?:(?:in |over )?(?:the\s+)?(?:last|past)\s+)?(\d+)\s*(?:d|day)",
            r"(?:show |get )?(?:my )?(?:portfolio |stake )?(?:change|delta|performance)\s+(?:(?:last|past|over)\s+)?(\d+)\s*(?:d|day)",
            r"(?:how much )?(?:have i |did i )?(?:earn|gain|lose|made)\s+(?:(?:in |over )?(?:the\s+)?(?:last|past)\s+)?(\d+)\s*(?:d|day)",
            r"(?:what(?:'?s| is|'s) )?(?:my )?(?:7|30)\s*(?:d|day)\s+(?:change|delta|performance|returns?)",
        ],
        IntentType.RECOMMEND: [
            r"recommend\s+(\d+(?:\.\d+)?)",
            r"(?:where|how) should i (?:stake|put|invest)\s+(\d+(?:\.\d+)?)",
            r"(?:best|top|good) validators?\s+(?:for|to stake)\s+(\d+(?:\.\d+)?)",
            r"(?:suggest|advise|pick)\s+(?:a\s+)?validators?\s+(?:for\s+)?(\d+(?:\.\d+)?)?",
            r"(?:stake|staking)\s+(?:recommendation|advice|suggestion)",
            r"who should i (?:stake|delegate)\s+(?:to|with)",
        ],
        IntentType.WATCH: [
            r"watch\s+(?:tao\s+)?price",
            r"(?:alert|notify|tell)\s+(?:me\s+)?(?:when|if)\s+(?:tao\s+)?(?:price|tao)",
            r"watch\s+(?:a\s+)?validator",
            r"(?:monitor|watch|track)\s+(?:my\s+)?(?:price|portfolio|validators?|registration)",
            r"set\s+(?:a\s+)?(?:price\s+)?alert",
        ],
        IntentType.REBALANCE: [
            r"rebalance\s+(\d+(?:\.\d+)?)",
            r"(?:batch|split|spread|distribute)\s+(?:stake\s+)?(\d+(?:\.\d+)?)\s*(?:tao)?",
            r"stake\s+(\d+(?:\.\d+)?)\s*(?:tao)?\s+(?:across|to|between)\s+(?:multiple|top|several)\s+validators?",
            r"(?:auto|smart)\s*(?:stake|rebalance)\s+(\d+(?:\.\d+)?)",
        ],
        IntentType.HELP: [
            r"help",
            r"what (?:else )?can you do",
            r"what (?:are )?(?:the |your )?(?:commands?|options|features|capabilities)",
            r"how do i",
            r"show me (?:what you can|how to)",
            r"what do you (?:do|support)",
            r"how (?:does|do) (?:this|taox) work",
            r"getting started",
            r"tutorial",
            r"usage",
        ],
        IntentType.CONFIRM: [
            r"^yes$",
            r"^ok$",
            r"^okay$",
            r"^confirm$",
            r"^sure$",
            r"^y$",
            r"^go ahead$",
            r"^do it$",
        ],
        IntentType.GREETING: [
            r"^hi+$",
            r"^hello+$",
            r"^hey+(?:\s|$)",
            r"^sup$",
            r"^yo+$",
            r"what'?s?\s*(up|good)",
            r"how'?s?\s*it\s*going",
            r"^good\s*(morning|afternoon|evening)",
            r"^gm$",
            r"^greetings",
            r"^hey+\s+.*(up|good|going)",
        ],
    }

    # Pattern for extracting "all" amount
    ALL_PATTERN = re.compile(r"\ball\b", re.IGNORECASE)

    # Pattern for extracting SS58 addresses
    SS58_PATTERN = re.compile(r"5[A-HJ-NP-Za-km-z1-9]{47}")

    # Pattern for extracting subnet IDs
    SUBNET_PATTERN = re.compile(r"(?:subnet\s*|sn\s*)(\d+)", re.IGNORECASE)

    @classmethod
    def parse(cls, user_input: str) -> Intent:
        """Parse user input into an Intent using pattern matching.

        Args:
            user_input: Raw user input string

        Returns:
            Parsed Intent object
        """
        text = user_input.lower().strip()

        # Check for "all" amount
        amount_all = bool(cls.ALL_PATTERN.search(text))

        # Try to extract SS58 address
        ss58_match = cls.SS58_PATTERN.search(user_input)  # Case-sensitive
        destination = ss58_match.group(0) if ss58_match else None

        # Try to extract subnet ID
        subnet_match = cls.SUBNET_PATTERN.search(text)
        netuid = int(subnet_match.group(1)) if subnet_match else None

        # Try each intent type's patterns
        for intent_type, patterns in cls.PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    intent = Intent(
                        type=intent_type,
                        raw_input=user_input,
                        confidence=0.8,  # Mock parser has lower confidence
                        amount_all=amount_all,
                        destination=destination,
                        netuid=netuid,
                    )

                    # Extract groups based on intent type
                    groups = match.groups()

                    if intent_type == IntentType.CREATE_WALLET and groups:
                        # First group = wallet name, second group = hotkey name
                        if groups[0]:
                            intent.wallet_name = groups[0].strip()
                        if len(groups) > 1 and groups[1]:
                            intent.hotkey_name = groups[1].strip()
                        # Check if it's hotkey-only creation
                        if not intent.wallet_name and "hotkey" in text:
                            intent.hotkey_name = groups[0].strip()

                    elif intent_type == IntentType.STAKE and groups:
                        if groups[0]:
                            with contextlib.suppress(ValueError):
                                intent.amount = float(groups[0])
                        if len(groups) > 1 and groups[1]:
                            intent.validator_name = groups[1].strip()
                        if len(groups) > 2 and groups[2]:
                            intent.netuid = int(groups[2])

                    elif (
                        intent_type == IntentType.UNSTAKE
                        and groups
                        or intent_type == IntentType.TRANSFER
                        and groups
                    ):
                        if groups[0]:
                            with contextlib.suppress(ValueError):
                                intent.amount = float(groups[0])
                        # destination already extracted from SS58_PATTERN above

                    elif intent_type == IntentType.SUBNET_INFO:
                        if groups and groups[0]:
                            intent.netuid = int(groups[0])
                        # Flag price-only queries
                        if any(w in text for w in ("price", "cost", "value", "token")):
                            intent.extra["price_only"] = True

                    elif (
                        intent_type in (IntentType.METAGRAPH, IntentType.VALIDATORS)
                        or intent_type == IntentType.REGISTER
                    ):
                        if groups and groups[0]:
                            intent.netuid = int(groups[0])

                    elif intent_type == IntentType.SET_CONFIG and groups:
                        # Extract the value being set
                        value = groups[0] if groups[0] else None
                        # Determine if it's hotkey or wallet from the matched text
                        # Check for wallet/coldkey FIRST (more specific)
                        if "wallet" in text or "coldkey" in text:
                            intent.wallet_name = value
                            intent.extra["config_key"] = "wallet"
                        elif "hotkey" in text:
                            intent.hotkey_name = value
                            intent.extra["config_key"] = "hotkey"
                        intent.extra["config_value"] = value

                    elif intent_type == IntentType.PORTFOLIO_DELTA:
                        # Extract number of days from capture groups
                        for g in (groups if groups else []):
                            if g:
                                with contextlib.suppress(ValueError):
                                    intent.extra["days"] = int(g)
                                    break
                        if "days" not in intent.extra:
                            intent.extra["days"] = 7  # Default

                    elif intent_type in (
                        IntentType.RECOMMEND,
                        IntentType.REBALANCE,
                    ):
                        # Extract amount from first capture group
                        if groups:
                            for g in groups:
                                if g:
                                    with contextlib.suppress(ValueError):
                                        intent.amount = float(g)
                                        break

                    return intent

        # No pattern matched - unknown intent
        return Intent(
            type=IntentType.UNKNOWN,
            raw_input=user_input,
            confidence=0.0,
        )


def parse_intent(user_input: str, use_llm: bool = False) -> Intent:
    """Parse user input into an Intent.

    Args:
        user_input: Raw user input string
        use_llm: Whether to use LLM for parsing (requires API key)

    Returns:
        Parsed Intent object
    """
    # For now, always use mock parser
    # LLM parsing will be implemented in llm.py
    return MockIntentParser.parse(user_input)
