"""Smart staking recommendations for taox.

Provides explainable, deterministic staking recommendations with
diversification advice.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from rich import box
from rich.panel import Panel
from rich.table import Table

from taox.data.taostats import TaostatsClient, Validator
from taox.ui.console import (
    console,
    format_address,
    format_tao,
    redact_address,
)
from taox.ui.theme import Symbols, TaoxColors


class RiskLevel(Enum):
    """Risk tolerance levels for staking."""

    LOW = "low"
    MEDIUM = "med"
    HIGH = "high"


@dataclass
class ScoringWeights:
    """Weights for the validator scoring model.

    All weights should sum to 1.0.
    """

    # Stability: higher stake means more trust/stability
    stake_weight: float = 0.35

    # Take rate: lower is better for delegators
    take_weight: float = 0.25

    # Rank: better rank means better performance
    rank_weight: float = 0.30

    # Diversity bonus: bonus for validators with moderate stake
    diversity_weight: float = 0.10

    def validate(self) -> bool:
        """Validate weights sum to 1.0."""
        total = self.stake_weight + self.take_weight + self.rank_weight + self.diversity_weight
        return abs(total - 1.0) < 0.01


# Default weights by risk level
RISK_WEIGHTS = {
    RiskLevel.LOW: ScoringWeights(
        stake_weight=0.45,  # Prefer established validators
        take_weight=0.20,
        rank_weight=0.25,
        diversity_weight=0.10,
    ),
    RiskLevel.MEDIUM: ScoringWeights(
        stake_weight=0.35,
        take_weight=0.25,
        rank_weight=0.30,
        diversity_weight=0.10,
    ),
    RiskLevel.HIGH: ScoringWeights(
        stake_weight=0.20,  # More willing to try newer validators
        take_weight=0.30,  # Prioritize low fees
        rank_weight=0.35,
        diversity_weight=0.15,
    ),
}


@dataclass
class ValidatorScore:
    """Scored validator with breakdown."""

    validator: Validator
    total_score: float
    stake_score: float
    take_score: float
    rank_score: float
    diversity_score: float
    risk_tier: str  # "low", "medium", "high"


@dataclass
class StakeRecommendation:
    """A staking recommendation with allocation."""

    validator: Validator
    score: ValidatorScore
    allocation_percent: float
    allocation_amount: float


@dataclass
class RecommendationResult:
    """Complete recommendation result with explanation."""

    recommendations: list[StakeRecommendation]
    total_amount: float
    netuid: int
    risk_level: RiskLevel
    weights_used: ScoringWeights
    diversification_reason: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


def score_validator(
    validator: Validator,
    all_validators: list[Validator],
    weights: ScoringWeights,
) -> ValidatorScore:
    """Score a validator using the deterministic scoring model.

    Args:
        validator: Validator to score
        all_validators: All validators for normalization
        weights: Scoring weights to use

    Returns:
        ValidatorScore with breakdown
    """
    # Normalize stake (0-1, higher stake = higher score)
    max_stake = max(v.stake for v in all_validators) if all_validators else 1
    min_stake = min(v.stake for v in all_validators) if all_validators else 0
    stake_range = max_stake - min_stake if max_stake > min_stake else 1

    stake_normalized = (validator.stake - min_stake) / stake_range
    stake_score = stake_normalized * weights.stake_weight

    # Score take rate (0-1, lower take = higher score)
    # Take rates typically range from 0.05 to 0.18 (5% to 18%)
    max_take = max(v.take for v in all_validators) if all_validators else 0.18
    min_take = min(v.take for v in all_validators) if all_validators else 0.05
    take_range = max_take - min_take if max_take > min_take else 0.01

    # Invert: lower take should give higher score
    take_normalized = 1 - ((validator.take - min_take) / take_range)
    take_score = take_normalized * weights.take_weight

    # Score rank (0-1, lower rank number = higher score)
    max_rank = max(v.rank for v in all_validators) if all_validators else 1
    rank_normalized = 1 - (validator.rank / max_rank) if max_rank > 0 else 0.5
    rank_score = rank_normalized * weights.rank_weight

    # Diversity score: bonus for mid-tier stake (not too concentrated)
    # Validators in the middle 60% of stake get higher diversity scores
    stake_percentile = stake_normalized
    if 0.2 <= stake_percentile <= 0.8:
        diversity_score = 1.0 * weights.diversity_weight
    elif 0.1 <= stake_percentile <= 0.9:
        diversity_score = 0.7 * weights.diversity_weight
    else:
        diversity_score = 0.4 * weights.diversity_weight

    total_score = stake_score + take_score + rank_score + diversity_score

    # Determine risk tier based on stake percentile
    if stake_percentile >= 0.7:
        risk_tier = "low"
    elif stake_percentile >= 0.3:
        risk_tier = "medium"
    else:
        risk_tier = "high"

    return ValidatorScore(
        validator=validator,
        total_score=total_score,
        stake_score=stake_score,
        take_score=take_score,
        rank_score=rank_score,
        diversity_score=diversity_score,
        risk_tier=risk_tier,
    )


def calculate_diversification(
    amount: float,
    scored_validators: list[ValidatorScore],
    diversify_count: int = 1,
) -> tuple[list[StakeRecommendation], Optional[str]]:
    """Calculate stake allocation with optional diversification.

    Args:
        amount: Total amount to stake
        scored_validators: Validators sorted by score (highest first)
        diversify_count: Number of validators to split across

    Returns:
        Tuple of (recommendations, diversification_reason)
    """
    if not scored_validators:
        return [], None

    recommendations = []
    reason = None

    # If large amount (>= 100 TAO), suggest diversification
    if amount >= 100 and diversify_count == 1:
        diversify_count = 2
        reason = "Amount >= 100 TAO: split recommended to reduce concentration risk"

    # If very large amount (>= 500 TAO), suggest more diversification
    if amount >= 500 and diversify_count < 3:
        diversify_count = 3
        reason = "Amount >= 500 TAO: split across 3 validators recommended"

    # Ensure we have enough validators
    diversify_count = min(diversify_count, len(scored_validators))

    if diversify_count == 1:
        # Single validator
        top = scored_validators[0]
        recommendations.append(
            StakeRecommendation(
                validator=top.validator,
                score=top,
                allocation_percent=100.0,
                allocation_amount=amount,
            )
        )
    elif diversify_count == 2:
        # 70/30 split
        recommendations.append(
            StakeRecommendation(
                validator=scored_validators[0].validator,
                score=scored_validators[0],
                allocation_percent=70.0,
                allocation_amount=amount * 0.7,
            )
        )
        recommendations.append(
            StakeRecommendation(
                validator=scored_validators[1].validator,
                score=scored_validators[1],
                allocation_percent=30.0,
                allocation_amount=amount * 0.3,
            )
        )
        if not reason:
            reason = "Split 70/30 between top 2 validators for diversification"
    else:
        # 50/30/20 split for 3+ validators
        allocations = [50.0, 30.0, 20.0]
        for i in range(min(3, len(scored_validators))):
            pct = allocations[i]
            recommendations.append(
                StakeRecommendation(
                    validator=scored_validators[i].validator,
                    score=scored_validators[i],
                    allocation_percent=pct,
                    allocation_amount=amount * (pct / 100),
                )
            )
        if not reason:
            reason = "Split 50/30/20 across top 3 validators for diversification"

    return recommendations, reason


async def get_stake_recommendations(
    taostats: TaostatsClient,
    amount: float,
    netuid: int = 1,
    top_n: int = 5,
    diversify: int = 1,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
) -> RecommendationResult:
    """Get staking recommendations for an amount.

    Args:
        taostats: TaostatsClient instance
        amount: Amount of TAO to stake
        netuid: Subnet ID
        top_n: Number of top validators to show
        diversify: Number of validators to split across (0 = auto)
        risk_level: Risk tolerance level

    Returns:
        RecommendationResult with recommendations and explanation
    """
    # Get validators
    validators = await taostats.get_validators(netuid=netuid, limit=50)

    if not validators:
        return RecommendationResult(
            recommendations=[],
            total_amount=amount,
            netuid=netuid,
            risk_level=risk_level,
            weights_used=RISK_WEIGHTS[risk_level],
            warnings=["No validators found for this subnet"],
        )

    # Get scoring weights for risk level
    weights = RISK_WEIGHTS[risk_level]

    # Score all validators
    scored = [score_validator(v, validators, weights) for v in validators]

    # Sort by total score (highest first)
    scored.sort(key=lambda s: s.total_score, reverse=True)

    # Get top N for display
    top_scored = scored[:top_n]

    # Calculate diversification
    recommendations, diversify_reason = calculate_diversification(amount, top_scored, diversify)

    # Generate warnings
    warnings = []

    # Check if top validator has very high take
    if top_scored and top_scored[0].validator.take > 0.15:
        warnings.append(
            f"Top validator has high take rate ({top_scored[0].validator.take * 100:.1f}%)"
        )

    # Check concentration
    if recommendations and len(recommendations) == 1 and amount >= 50:
        warnings.append("Consider diversifying across multiple validators for amounts >= 50 TAO")

    return RecommendationResult(
        recommendations=recommendations,
        total_amount=amount,
        netuid=netuid,
        risk_level=risk_level,
        weights_used=weights,
        diversification_reason=diversify_reason,
        warnings=warnings,
    )


def display_recommendations(
    result: RecommendationResult,
    share_mode: bool = False,
    json_output: bool = False,
) -> None:
    """Display staking recommendations.

    Args:
        result: RecommendationResult to display
        share_mode: If True, redact addresses
        json_output: If True, output as JSON
    """
    if json_output:
        output = {
            "amount": result.total_amount,
            "netuid": result.netuid,
            "risk_level": result.risk_level.value,
            "recommendations": [
                {
                    "validator_name": r.validator.name,
                    "validator_hotkey": (
                        r.validator.hotkey if not share_mode else redact_address(r.validator.hotkey)
                    ),
                    "allocation_percent": r.allocation_percent,
                    "allocation_amount": r.allocation_amount,
                    "score": r.score.total_score,
                    "take_rate": r.validator.take,
                    "risk_tier": r.score.risk_tier,
                }
                for r in result.recommendations
            ],
            "scoring_weights": {
                "stake": result.weights_used.stake_weight,
                "take": result.weights_used.take_weight,
                "rank": result.weights_used.rank_weight,
                "diversity": result.weights_used.diversity_weight,
            },
            "diversification_reason": result.diversification_reason,
            "warnings": result.warnings,
        }
        print(json.dumps(output, indent=2))
        return

    # Title panel
    title = f"Staking Recommendation - {format_tao(result.total_amount)} on SN{result.netuid}"
    console.print(
        Panel(
            f"[bold]{title}[/bold]\n" f"Risk level: {result.risk_level.value}",
            box=box.ROUNDED,
            border_style="primary",
        )
    )
    console.print()

    if not result.recommendations:
        console.print("[warning]No recommendations available.[/warning]")
        return

    # Recommendations table
    table = Table(
        title="[primary]Recommended Validators[/primary]",
        box=box.ROUNDED,
        border_style=TaoxColors.BORDER,
    )
    table.add_column("#", justify="right", style="muted")
    table.add_column("Validator", style="validator")
    table.add_column("Allocation", justify="right", style="tao")
    table.add_column("Take", justify="right", style="warning")
    table.add_column("Score", justify="right", style="info")
    table.add_column("Risk", justify="center")

    for i, rec in enumerate(result.recommendations, 1):
        v = rec.validator
        name = v.name or "[muted]Unknown[/muted]"

        # Risk tier styling
        risk_style = {
            "low": "[success]Low[/success]",
            "medium": "[warning]Med[/warning]",
            "high": "[error]High[/error]",
        }.get(rec.score.risk_tier, rec.score.risk_tier)

        table.add_row(
            str(i),
            name,
            f"{rec.allocation_percent:.0f}% ({format_tao(rec.allocation_amount, symbol=False)} τ)",
            f"{v.take * 100:.1f}%",
            f"{rec.score.total_score:.2f}",
            risk_style,
        )

    console.print(table)
    console.print()

    # Show hotkeys (redacted in share mode)
    console.print("[bold]Hotkeys:[/bold]")
    for i, rec in enumerate(result.recommendations, 1):
        hotkey = rec.validator.hotkey
        hotkey = redact_address(hotkey) if share_mode else format_address(hotkey)
        console.print(f"  {i}. {hotkey}")
    console.print()

    # Diversification advice
    if result.diversification_reason:
        console.print(f"[info]{Symbols.INFO} {result.diversification_reason}[/info]")
        console.print()

    # Why section - explain the scoring
    console.print("[bold]Why these validators?[/bold]")
    weights = result.weights_used
    console.print(
        f"  Scoring weights: Stake {weights.stake_weight:.0%}, "
        f"Take {weights.take_weight:.0%}, "
        f"Rank {weights.rank_weight:.0%}, "
        f"Diversity {weights.diversity_weight:.0%}"
    )
    console.print(f"  Risk profile: {result.risk_level.value} - ", end="")
    if result.risk_level == RiskLevel.LOW:
        console.print("prioritizes established validators with proven track record")
    elif result.risk_level == RiskLevel.MEDIUM:
        console.print("balances stability with good returns")
    else:
        console.print("prioritizes lower fees and higher potential returns")
    console.print()

    # Warnings
    if result.warnings:
        console.print("[bold yellow]Warnings:[/bold yellow]")
        for warning in result.warnings:
            console.print(f"  {Symbols.WARN} {warning}")
        console.print()

    # Next steps
    console.print("[bold]Next steps:[/bold]")
    for _i, rec in enumerate(result.recommendations, 1):
        v = rec.validator
        name = v.name or format_address(v.hotkey, truncate=True)
        console.print(
            f"  {Symbols.NEXT} [command]taox stake --amount {rec.allocation_amount:.2f} "
            f'--validator "{name}" --netuid {result.netuid}[/command]'
        )


async def stake_recommend(
    taostats: TaostatsClient,
    amount: float,
    netuid: int = 1,
    top_n: int = 5,
    diversify: int = 1,
    risk_level: str = "med",
    share_mode: bool = False,
    json_output: bool = False,
) -> RecommendationResult:
    """Get and display staking recommendations.

    Args:
        taostats: TaostatsClient instance
        amount: Amount of TAO to stake
        netuid: Subnet ID
        top_n: Number of top validators to show
        diversify: Number of validators to split across (0 = auto)
        risk_level: Risk tolerance ("low", "med", "high")
        share_mode: If True, redact addresses
        json_output: If True, output as JSON

    Returns:
        RecommendationResult
    """
    # Parse risk level
    risk = RiskLevel.MEDIUM
    if risk_level.lower() in ("low", "l"):
        risk = RiskLevel.LOW
    elif risk_level.lower() in ("high", "h"):
        risk = RiskLevel.HIGH

    with console.status("[bold green]Analyzing validators..."):
        result = await get_stake_recommendations(
            taostats=taostats,
            amount=amount,
            netuid=netuid,
            top_n=top_n,
            diversify=diversify,
            risk_level=risk,
        )

    display_recommendations(result, share_mode=share_mode, json_output=json_output)

    return result
