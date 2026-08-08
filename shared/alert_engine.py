"""
Threshold checks + cooldown/hysteresis. Shared by the scan job. Kept as a
plain module rather than a deployed service in V1 — it has no independent
schedule of its own, it just runs inline during each scan pass.

Functions take the full `market_row` dict (as built in scan.py, matching
the `markets` table schema) rather than individual scalars, since the
rich card format (shared/formatting.py) needs slug, opportunity_score,
last_price_yes, etc. — not just the question and tier.
"""
from datetime import datetime, timedelta, timezone

from . import config, db, formatting, telegram_client


def maybe_alert_price_move(market_row: dict, prev_price: float | None, chat_id) -> bool:
    new_price = market_row.get("last_price_yes")
    if prev_price is None or new_price is None:
        return False
    delta_points = abs(new_price - prev_price) * 100
    if delta_points < config.PRICE_MOVE_THRESHOLD_POINTS:
        return False
    highlight = f"Moved {prev_price:.0%} → {new_price:.0%}  (Δ{delta_points:.1f} pts)"
    return _fire_if_due(market_row, "price_move", delta_points, chat_id, icon="📈", highlight=highlight)


def maybe_alert_volume_spike(market_row: dict, trailing_volume: float | None, chat_id) -> bool:
    new_volume = market_row.get("last_volume_24h")
    if not trailing_volume or new_volume is None:
        return False
    if new_volume < trailing_volume * config.VOLUME_SPIKE_MULTIPLIER:
        return False
    highlight = f"Volume spike: ≥{config.VOLUME_SPIKE_MULTIPLIER:.0f}× trailing average"
    return _fire_if_due(market_row, "volume_spike", new_volume, chat_id, icon="🔥", highlight=highlight)


def maybe_alert_tier_change(market_row: dict, old_tier: str | None, chat_id) -> bool:
    new_tier = market_row.get("current_tier")
    if old_tier is None or old_tier == new_tier:
        return False
    market_id = market_row["market_id"]
    dedup_key = f"{market_id}:tier_change:{new_tier}"
    if db.get_cooldown(dedup_key):
        return False
    text = formatting.format_market_card(market_row, icon="⏰", highlight=f"Now entering the {new_tier} tier")
    keyboard = formatting.market_keyboard(market_row["short_id"], market_row.get("slug"))
    telegram_client.send_message(chat_id, text, reply_markup=keyboard)
    db.upsert_cooldown({"dedup_key": dedup_key, "last_sent_at": datetime.now(timezone.utc).isoformat()})
    return True


def _fire_if_due(market_row: dict, alert_type: str, value: float, chat_id, icon: str, highlight: str) -> bool:
    """Two rules gate re-firing: a time cooldown, AND (if still cooling
    down) the value must have moved meaningfully further than last time —
    this stops a market oscillating around the threshold from spamming."""
    market_id = market_row["market_id"]
    tier = market_row.get("current_tier", "background")
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

    text = formatting.format_market_card(market_row, icon=icon, highlight=highlight)
    keyboard = formatting.market_keyboard(market_row["short_id"], market_row.get("slug"))
    telegram_client.send_message(chat_id, text, reply_markup=keyboard)

    minutes = config.ALERT_COOLDOWN_MINUTES.get(tier, 60)
    db.upsert_cooldown({
        "dedup_key": dedup_key,
        "last_sent_at": now.isoformat(),
        "last_alerted_value": value,
        "cooldown_until": (now + timedelta(minutes=minutes)).isoformat(),
    })
    return True
