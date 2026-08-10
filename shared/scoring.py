"""
V1 scoring — everything here is computed from market metadata only (price,
volume, liquidity, time remaining, tags/question text). No AI, no external
evidence, so it's free and instant to compute for every market on every
scan, no matter how many are being tracked.

`opportunity_score` is a heuristic "worth a closer look" ranking —
momentum, volume acceleration, liquidity growth, discovery recency — NOT
an estimate of mispricing. A true edge score (AI probability vs. market
price) needs the V2 research layer to be evidence-backed; computing one in
V1 would just be dressing up a guess as a number, which is the exact
failure mode the earlier spec critique flagged. Keep `opportunity_score`
and "edge" conceptually separate even after V2 adds the latter.
"""
import re
from datetime import datetime, timezone

CATEGORY_KEYWORDS = {
    "AI": ["ai", "artificial intelligence", "openai", "anthropic", "llm", "gpt"],
    "Politics": ["election", "president", "senate", "congress", "governor", "vote"],
    "Crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "token"],
    "Sports": ["nfl", "nba", "nhl", "mlb", "premier league", "champions league", "world cup", "ufc"],
    "Economics": ["fed", "rate cut", "inflation", "gdp", "recession", "jobs report"],
    "Technology": ["apple", "google", "microsoft", "nvidia", "tesla", "iphone"],
    "Entertainment": ["oscar", "grammy", "box office", "movie", "album"],
    "Science": ["nasa", "spacex", "climate", "vaccine", "fda"],
    "Weather": ["weather", "temperature", "rain", "snow", "hurricane", "storm", "celsius", "fahrenheit", "forecast", "heatwave"],
}


def categorize(question: str | None, tags: list[str] | None) -> str:
    """Auto-tag for organization only — never used to exclude a market
    from monitoring.

    Uses word-boundary matching, not naive substring containment: a plain
    `"ai" in text` check would match inside ordinary words like "rain" or
    "captain". Multi-word keywords (e.g. "rate cut") still match as a
    contiguous phrase via the same regex.
    """
    text = (question or "").lower()
    tag_text = " ".join(tags or []).lower()
    combined = f"{text} {tag_text}"
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", combined):
                return category
    return "Other"


def time_remaining_days(end_date_iso: str | None) -> float | None:
    if not end_date_iso:
        return None
    try:
        end = datetime.fromisoformat(end_date_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (end - datetime.now(timezone.utc)).total_seconds() / 86400


def assign_tier(days_remaining: float | None) -> str:
    if days_remaining is None:
        return "background"
    if days_remaining <= 1:
        return "critical"
    if days_remaining <= 3:
        return "hot"
    if days_remaining <= 7:
        return "active"
    if days_remaining <= 14:
        return "warm"
    return "background"


def risk_score(liquidity: float | None, volatility_points: float, days_remaining: float | None) -> float:
    """Higher = riskier signal: thin order book, high recent volatility,
    close to resolution."""
    liquidity = liquidity or 0.0
    thinness = 1 / (1 + liquidity / 10_000)
    urgency = 1 / (1 + (days_remaining if days_remaining is not None else 999) / 7)
    volatility_component = min(volatility_points / 20, 1.0)
    return round(min(1.0, 0.5 * thinness + 0.3 * volatility_component + 0.2 * urgency), 3)


def confidence_score(liquidity: float | None, volume_24h: float | None) -> float:
    """How much to trust the observed market *signal itself* — not an
    opinion about where the price should be, since V1 has no independent
    estimate to be confident about."""
    liquidity = liquidity or 0.0
    volume_24h = volume_24h or 0.0
    return round(min(1.0, (liquidity / 50_000) * 0.5 + (volume_24h / 20_000) * 0.5), 3)


def source_reliability_score(market_age_days: float | None) -> float:
    """V1 proxy: how established the market itself is (no external news
    sources exist yet to score in V1 — see README/architecture doc). This
    field is reused in V2 as a real per-source credibility score once
    research aggregation exists."""
    if market_age_days is None:
        return 0.5
    return round(min(1.0, 0.4 + market_age_days / 30), 3)


def opportunity_score(
    volatility_points: float,
    volume_24h: float | None,
    liquidity_delta: float,
    discovery_recency_hours: float,
    confidence: float,
) -> float:
    """Heuristic composite ranking used across the entire platform, not
    just watchlisted markets. Weights are starting defaults — tune once
    you have real alert history to check them against."""
    volume_24h = volume_24h or 0.0
    recency_boost = max(0.0, 1 - discovery_recency_hours / 48)  # new markets get a temporary boost
    raw = (
        0.35 * min(volatility_points / 20, 1.0)
        + 0.25 * min(volume_24h / 20_000, 1.0)
        + 0.15 * min(max(liquidity_delta, 0.0) / 5_000, 1.0)
        + 0.15 * recency_boost
        + 0.10 * confidence
    )
    return round(min(1.0, raw), 3)


def apply_priority_boost(base_score: float, question: str | None, category: str, boosts: list[dict]) -> float:
    """Boosts affect ranking/alert sensitivity only — they never gate
    whether a market gets scored or tracked in the first place."""
    text = (question or "").lower()
    multiplier = 1.0
    for boost in boosts:
        term = str(boost.get("keyword_or_category", "")).lower()
        if term and (term in text or term == category.lower()):
            multiplier = max(multiplier, float(boost.get("weight", 1.0)))
    return round(min(1.0, base_score * multiplier), 3)
