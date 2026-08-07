"""
Threshold checks + cooldown/hysteresis. Shared by the scan job. Kept as a
plain module rather than a deployed service in V1 — it has no independent
schedule of its own, it just runs inline during each scan pass.
"""
from datetime import datetime, timedelta, timezone

from . import config, db, telegram_client


def maybe_alert_price_move(market_id: str, question: str, tier: str,
                            prev_price: float | None, new_price: float | None, chat_id) -> bool:
    if prev_price is None or new_price is None:
        return False
    delta_points = abs(new_price - prev_price) * 100
    if delta_points < config.PRICE_MOVE_THRESHOLD_POINTS:
        return False
    return _fire_if_due(
        market_id, "price_move", delta_points, tier, chat_id,
        text=(
            f"📈 *Price move*\n\n{question}\n\n"
            f"{prev_price:.0%} → {new_price:.0%}  (Δ{delta_points:.1f} pts)  |  tier: {tier}"
        ),
    )


def maybe_alert_volume_spike(market_id: str, question: str, tier: str,
                              trailing_volume: float | None, new_volume: float | None, chat_id) -> bool:
    if not trailing_volume or new_volume is None:
        return False
    if new_volume < trailing_volume * config.VOLUME_SPIKE_MULTIPLIER:
        return False
    return _fire_if_due(
        market_id, "volume_spike", new_volume, tier, chat_id,
        text=(
            f"🔥 *Volume spike*\n\n{question}\n\n"
            f"24h volume ${new_volume:,.0f}  (≥{config.VOLUME_SPIKE_MULTIPLIER:.0f}× trailing avg)  |  tier: {tier}"
        ),
    )


def maybe_alert_tier_change(market_id: str, question: str, old_tier: str | None, new_tier: str, chat_id) -> bool:
    if old_tier is None or old_tier == new_tier:
        return False
    dedup_key = f"{market_id}:tier_change:{new_tier}"
    if db.get_cooldown(dedup_key):
        return False
    telegram_client.send_message(chat_id, f"⏰ *{question}*\n\nnow entering the *{new_tier}* monitoring tier.")
    db.upsert_cooldown({"dedup_key": dedup_key, "last_sent_at": datetime.now(timezone.utc).isoformat()})
    return True


def _fire_if_due(market_id: str, alert_type: str, value: float, tier: str, chat_id, text: str) -> bool:
    """Two rules gate re-firing: a time cooldown, AND (if still cooling
    down) the value must have moved meaningfully further than last time —
    this stops a market oscillating around the threshold from spamming."""
    dedup_key = f"{market_id}:{alert_type}"
    cooldown = db.get_cooldown(dedup_key)
    now = datetime.now(timezone.utc)

    if cooldown:
        cooldown_until = cooldown.get("cooldown_until")
        last_value = cooldown.get("last_alerted_value") or 0.0
        still_cooling = bool(cooldown_until) and datetime.fromisoformat(cooldown_until) > now
        moved_further = abs(value - last_value) >= config.PRICE_MOVE_THRESHOLD_POINTS / 2
        if still_cooling and not moved_further:
            return False

    telegram_client.send_message(chat_id, text)
    minutes = config.ALERT_COOLDOWN_MINUTES.get(tier, 60)
    db.upsert_cooldown({
        "dedup_key": dedup_key,
        "last_sent_at": now.isoformat(),
        "last_alerted_value": value,
        "cooldown_until": (now + timedelta(minutes=minutes)).isoformat(),
    })
    return True
