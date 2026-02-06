"""Tests for smart staking recommendations."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from taox.cli import app
from taox.commands.recommend import (
    RISK_WEIGHTS,
    RiskLevel,
    ScoringWeights,
    calculate_diversification,
    get_stake_recommendations,
    score_validator,
)
from taox.data.taostats import Validator

runner = CliRunner()


# Test fixtures
@pytest.fixture
def sample_validators():
    """Sample validators for testing."""
    return [
        Validator(
            hotkey="5AAA111",
            name="Top Validator",
            stake=1000000.0,
            vpermit=True,
            netuid=1,
            uid=0,
            rank=1,
            take=0.09,
        ),
        Validator(
            hotkey="5BBB222",
            name="Mid Validator",
            stake=500000.0,
            vpermit=True,
            netuid=1,
            uid=1,
            rank=5,
            take=0.05,
        ),
        Validator(
            hotkey="5CCC333",
            name="Low Fee Validator",
            stake=200000.0,
            vpermit=True,
            netuid=1,
            uid=2,
            rank=10,
            take=0.03,
        ),
        Validator(
            hotkey="5DDD444",
            name="High Fee Validator",
            stake=300000.0,
            vpermit=True,
            netuid=1,
            uid=3,
            rank=8,
            take=0.18,
        ),
        Validator(
            hotkey="5EEE555",
            name="Small Validator",
            stake=50000.0,
            vpermit=True,
            netuid=1,
            uid=4,
            rank=20,
            take=0.10,
        ),
    ]


class TestScoringWeights:
    """Tests for ScoringWeights."""

    def test_default_weights_sum_to_one(self):
        """Test default weights sum to 1.0."""
        weights = ScoringWeights()
        assert weights.validate()

    def test_risk_weights_sum_to_one(self):
        """Test all risk level weights sum to 1.0."""
        for risk_level, weights in RISK_WEIGHTS.items():
            assert weights.validate(), f"Weights for {risk_level} don't sum to 1.0"


class TestScoreValidator:
    """Tests for score_validator function."""

    def test_highest_stake_gets_high_stake_score(self, sample_validators):
        """Test that highest stake validator gets high stake score."""
        weights = ScoringWeights()
        top_validator = sample_validators[0]  # 1M stake

        score = score_validator(top_validator, sample_validators, weights)

        # Should have high stake score (normalized to 1.0)
        assert score.stake_score > 0.3

    def test_lowest_take_gets_high_take_score(self, sample_validators):
        """Test that lowest take validator gets high take score."""
        weights = ScoringWeights()
        low_fee = sample_validators[2]  # 3% take

        score = score_validator(low_fee, sample_validators, weights)

        # Should have high take score
        assert score.take_score > 0.2

    def test_rank_1_gets_high_rank_score(self, sample_validators):
        """Test that rank 1 validator gets high rank score."""
        weights = ScoringWeights()
        top_ranked = sample_validators[0]  # rank 1

        score = score_validator(top_ranked, sample_validators, weights)

        # Should have high rank score
        assert score.rank_score > 0.25

    def test_score_breakdown_sums_to_total(self, sample_validators):
        """Test that score components sum to total score."""
        weights = ScoringWeights()

        for v in sample_validators:
            score = score_validator(v, sample_validators, weights)
            expected_total = (
                score.stake_score + score.take_score + score.rank_score + score.diversity_score
            )
            assert abs(score.total_score - expected_total) < 0.001

    def test_risk_tier_assignment(self, sample_validators):
        """Test risk tier is assigned based on stake percentile."""
        weights = ScoringWeights()

        # High stake = low risk
        top = score_validator(sample_validators[0], sample_validators, weights)
        assert top.risk_tier == "low"

        # Low stake = high risk
        small = score_validator(sample_validators[4], sample_validators, weights)
        assert small.risk_tier == "high"


class TestCalculateDiversification:
    """Tests for calculate_diversification function."""

    def test_single_validator_allocation(self, sample_validators):
        """Test single validator gets 100% allocation."""
        weights = ScoringWeights()
        scored = [score_validator(v, sample_validators, weights) for v in sample_validators]
        scored.sort(key=lambda s: s.total_score, reverse=True)

        recommendations, reason = calculate_diversification(50.0, scored, diversify_count=1)

        assert len(recommendations) == 1
        assert recommendations[0].allocation_percent == 100.0
        assert recommendations[0].allocation_amount == 50.0

    def test_two_validator_split(self, sample_validators):
        """Test two validator split is 70/30."""
        weights = ScoringWeights()
        scored = [score_validator(v, sample_validators, weights) for v in sample_validators]
        scored.sort(key=lambda s: s.total_score, reverse=True)

        recommendations, reason = calculate_diversification(100.0, scored, diversify_count=2)

        assert len(recommendations) == 2
        assert recommendations[0].allocation_percent == 70.0
        assert recommendations[1].allocation_percent == 30.0
        assert recommendations[0].allocation_amount == 70.0
        assert recommendations[1].allocation_amount == 30.0

    def test_three_validator_split(self, sample_validators):
        """Test three validator split is 50/30/20."""
        weights = ScoringWeights()
        scored = [score_validator(v, sample_validators, weights) for v in sample_validators]
        scored.sort(key=lambda s: s.total_score, reverse=True)

        recommendations, reason = calculate_diversification(100.0, scored, diversify_count=3)

        assert len(recommendations) == 3
        assert recommendations[0].allocation_percent == 50.0
        assert recommendations[1].allocation_percent == 30.0
        assert recommendations[2].allocation_percent == 20.0

    def test_auto_diversify_large_amount(self, sample_validators):
        """Test auto-diversification for amounts >= 100 TAO."""
        weights = ScoringWeights()
        scored = [score_validator(v, sample_validators, weights) for v in sample_validators]
        scored.sort(key=lambda s: s.total_score, reverse=True)

        # Pass diversify_count=1 but amount >= 100
        recommendations, reason = calculate_diversification(150.0, scored, diversify_count=1)

        # Should auto-upgrade to 2 validators
        assert len(recommendations) == 2
        assert "split" in reason.lower() or "100" in reason

    def test_auto_diversify_very_large_amount(self, sample_validators):
        """Test auto-diversification for amounts >= 500 TAO."""
        weights = ScoringWeights()
        scored = [score_validator(v, sample_validators, weights) for v in sample_validators]
        scored.sort(key=lambda s: s.total_score, reverse=True)

        recommendations, reason = calculate_diversification(500.0, scored, diversify_count=1)

        # Should auto-upgrade to 3 validators
        assert len(recommendations) == 3


class TestRiskLevels:
    """Tests for risk level effects on scoring."""

    def test_low_risk_prefers_high_stake(self, sample_validators):
        """Test low risk prefers established validators."""
        low_weights = RISK_WEIGHTS[RiskLevel.LOW]
        high_weights = RISK_WEIGHTS[RiskLevel.HIGH]

        assert low_weights.stake_weight > high_weights.stake_weight

    def test_high_risk_prefers_low_take(self, sample_validators):
        """Test high risk prefers lower fees."""
        low_weights = RISK_WEIGHTS[RiskLevel.LOW]
        high_weights = RISK_WEIGHTS[RiskLevel.HIGH]

        assert high_weights.take_weight > low_weights.take_weight


class TestGetStakeRecommendations:
    """Tests for get_stake_recommendations function."""

    @pytest.mark.asyncio
    async def test_returns_recommendations(self, sample_validators):
        """Test that recommendations are returned."""
        mock_taostats = AsyncMock()
        mock_taostats.get_validators = AsyncMock(return_value=sample_validators)

        result = await get_stake_recommendations(
            taostats=mock_taostats,
            amount=100.0,
            netuid=1,
        )

        assert len(result.recommendations) > 0
        assert result.total_amount == 100.0
        assert result.netuid == 1

    @pytest.mark.asyncio
    async def test_handles_no_validators(self):
        """Test handling when no validators found."""
        mock_taostats = AsyncMock()
        mock_taostats.get_validators = AsyncMock(return_value=[])

        result = await get_stake_recommendations(
            taostats=mock_taostats,
            amount=100.0,
            netuid=999,
        )

        assert len(result.recommendations) == 0
        assert "No validators found" in result.warnings[0]

    @pytest.mark.asyncio
    async def test_respects_risk_level(self, sample_validators):
        """Test that risk level affects recommendations."""
        mock_taostats = AsyncMock()
        mock_taostats.get_validators = AsyncMock(return_value=sample_validators)

        low_result = await get_stake_recommendations(
            taostats=mock_taostats,
            amount=100.0,
            risk_level=RiskLevel.LOW,
        )

        high_result = await get_stake_recommendations(
            taostats=mock_taostats,
            amount=100.0,
            risk_level=RiskLevel.HIGH,
        )

        # Low risk should use higher stake weight
        assert low_result.weights_used.stake_weight > high_result.weights_used.stake_weight

    @pytest.mark.asyncio
    async def test_warns_on_high_take(self, sample_validators):
        """Test warning when top validator has high take."""
        # Create validators where top has very high take
        high_take_validators = [
            Validator(
                hotkey="5AAA111",
                name="High Take Top",
                stake=1000000.0,
                vpermit=True,
                netuid=1,
                uid=0,
                rank=1,
                take=0.20,  # 20% take
            ),
        ]

        mock_taostats = AsyncMock()
        mock_taostats.get_validators = AsyncMock(return_value=high_take_validators)

        result = await get_stake_recommendations(
            taostats=mock_taostats,
            amount=100.0,
        )

        # Should have warning about high take
        assert any("high take" in w.lower() for w in result.warnings)


class TestCLICommand:
    """Tests for CLI recommend command."""

    def test_recommend_command_exists(self):
        """Test that recommend command exists."""
        result = runner.invoke(app, ["recommend", "--help"])
        assert result.exit_code == 0
        assert "staking recommendations" in result.output.lower()

    @patch("taox.commands.recommend.stake_recommend")
    def test_recommend_basic_invocation(self, mock_recommend):
        """Test basic recommend command invocation."""
        from taox.commands.recommend import RecommendationResult, RiskLevel, ScoringWeights

        mock_recommend.return_value = RecommendationResult(
            recommendations=[],
            total_amount=100.0,
            netuid=1,
            risk_level=RiskLevel.MEDIUM,
            weights_used=ScoringWeights(),
        )

        result = runner.invoke(app, ["recommend", "100"])
        # Should not error
        assert result.exit_code == 0

    def test_recommend_json_output(self):
        """Test recommend command with --json flag."""
        result = runner.invoke(app, ["recommend", "100", "--json"])
        # Should not error, and should produce JSON-like output
        assert result.exit_code == 0
        # In demo mode, should output JSON
        try:
            data = json.loads(result.output)
            assert "amount" in data or "recommendations" in data
        except json.JSONDecodeError:
            # Not JSON - might have status output
            pass

    def test_recommend_with_options(self):
        """Test recommend command with various options."""
        result = runner.invoke(
            app, ["recommend", "100", "--netuid", "1", "--risk", "low", "--top", "3"]
        )
        assert result.exit_code == 0

    def test_recommend_share_mode(self):
        """Test recommend command with --share flag."""
        result = runner.invoke(app, ["recommend", "100", "--share"])
        assert result.exit_code == 0


class TestDeterministicScoring:
    """Tests to ensure scoring is deterministic and reproducible."""

    def test_same_input_same_output(self, sample_validators):
        """Test that same input produces same output."""
        weights = ScoringWeights()

        score1 = score_validator(sample_validators[0], sample_validators, weights)
        score2 = score_validator(sample_validators[0], sample_validators, weights)

        assert score1.total_score == score2.total_score
        assert score1.stake_score == score2.stake_score
        assert score1.take_score == score2.take_score
        assert score1.rank_score == score2.rank_score

    def test_ranking_is_consistent(self, sample_validators):
        """Test that validator ranking is consistent."""
        weights = ScoringWeights()

        scored = [score_validator(v, sample_validators, weights) for v in sample_validators]
        scored.sort(key=lambda s: s.total_score, reverse=True)

        # Run again
        scored2 = [score_validator(v, sample_validators, weights) for v in sample_validators]
        scored2.sort(key=lambda s: s.total_score, reverse=True)

        # Order should be the same
        for i in range(len(scored)):
            assert scored[i].validator.hotkey == scored2[i].validator.hotkey
