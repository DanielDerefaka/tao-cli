"""Intent classification and entity extraction for taox."""

import re
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field


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
    HELP = "help"
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

    # Patterns for intent detection
    PATTERNS = {
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
            r"transfer\s+(\d+(?:\.\d+)?)\s*(?:tao)?\s*to\s+(\S+)",
            r"send\s+(\d+(?:\.\d+)?)\s*(?:tao)?\s*to\s+(\S+)",
        ],
        IntentType.BALANCE: [
            r"balance",
            r"how much (?:tao )?(?:do i have|balance)",
            r"what(?:'s| is) my balance",
            r"check balance",
            r"show balance",
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
        IntentType.SUBNETS: [
            r"(?:show |list )?subnets?",
            r"what subnets",
        ],
        IntentType.REGISTER: [
            r"register\s*(?:on\s+)?(?:subnet\s*)?(\d+)?",
        ],
        IntentType.HELP: [
            r"help",
            r"what can you do",
            r"commands?",
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

                    if intent_type == IntentType.STAKE and groups:
                        if groups[0]:
                            try:
                                intent.amount = float(groups[0])
                            except ValueError:
                                pass
                        if len(groups) > 1 and groups[1]:
                            intent.validator_name = groups[1].strip()
                        if len(groups) > 2 and groups[2]:
                            intent.netuid = int(groups[2])

                    elif intent_type == IntentType.UNSTAKE and groups:
                        if groups[0]:
                            try:
                                intent.amount = float(groups[0])
                            except ValueError:
                                pass

                    elif intent_type == IntentType.TRANSFER and groups:
                        if groups[0]:
                            try:
                                intent.amount = float(groups[0])
                            except ValueError:
                                pass
                        if len(groups) > 1 and groups[1]:
                            # Check if it's an SS58 address
                            if cls.SS58_PATTERN.match(groups[1]):
                                intent.destination = groups[1]

                    elif intent_type in (IntentType.METAGRAPH, IntentType.VALIDATORS):
                        if groups and groups[0]:
                            intent.netuid = int(groups[0])

                    elif intent_type == IntentType.REGISTER:
                        if groups and groups[0]:
                            intent.netuid = int(groups[0])

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
