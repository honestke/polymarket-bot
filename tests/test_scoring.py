import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import scoring


def test_categorize_matches_keyword():
    assert scoring.categorize("Will OpenAI release GPT-6 in 2026?", []) == "AI"


def test_categorize_falls_back_to_other():
    assert scoring.categorize("Will it rain in Nairobi tomorrow?", []) == "Other"


def test_categorize_uses_tags_too():
    assert scoring.categorize("Some ambiguous question", ["crypto", "defi"]) == "Crypto"


def test_assign_tier_boundaries():
    assert scoring.assign_tier(0.5) == "critical"
    assert scoring.assign_tier(2) == "hot"
    assert scoring.assign_tier(6) == "active"
    assert scoring.assign_tier(10) == "warm"
    assert scoring.assign_tier(40) == "background"
    assert scoring.assign_tier(None) == "background"


def test_opportunity_score_bounded():
    score = scoring.opportunity_score(
        volatility_points=50, volume_24h=1_000_000, liquidity_delta=10_000,
        discovery_recency_hours=0, confidence=1.0,
    )
    assert 0.0 <= score <= 1.0


def test_priority_boost_never_lowers_score():
    base = 0.4
    boosts = [{"keyword_or_category": "ai", "weight": 2.0}]
    boosted = scoring.apply_priority_boost(base, "Will AI pass the Turing test?", "AI", boosts)
    assert boosted >= base
