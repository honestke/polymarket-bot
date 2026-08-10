"""
Threshold checks + cooldown/hysteresis + push-vs-feed routing. Shared by
the scan job. Kept as a plain module rather than a deployed service in
V1 — it has no independent schedule of its own, it just runs inline
during each scan pass.

Every event that clears its cooldown/hysteresis gate gets LOGGED (written
to the `alerts` table, channel='feed' by default). Only events on markets
scoring at or above PUSH_OPPORTUNITY_THRESHOLD also get an instant
Telegram push (channel='push'). This is what stops routine volume blips
on low-scoring markets from interrupting you — they still show up in
/live, they just don't buzz your phone. See shared/config.py.
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
    """Tier changes are always feed-only, never pushed — a market simply
    crossing into a new urgency window isn't itself a signal worth
    interrupting someone for, even if the market is high-scoring (a real
    score change would already have triggered a price/volume push)."""
    new_tier = market_row.get("current_tier")
    if old_tier is None or old_tier == new_tier:
        return False
    market_id = market_row["market_id"]
    dedup_key = f"{market_id}:tier_change:{new_tier}"
    if db.get_cooldown(dedup_key):
        return False

    _log_alert(market_row, "tier_change", chat_id, value=None, channel="feed")
    db.upsert_cooldown({"dedup_key": dedup_key, "last_sent_at": datetime.now(timezone.utc).isoformat()})
    return True


def _fire_if_due(market_row: dict, alert_type: str, value: float, chat_id, icon: str, highlight: str) -> bool:
    """Two rules gate whether this fires at all: a time cooldown, AND (if
    still cooling down) the value must have moved meaningfully further
    than last time — this stops a market oscillating around the threshold
    from generating endless log entries. Once it fires, a SEPARATE
    decision (see _log_alert) decides push vs. feed-only."""
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

    opportunity = market_row.get("opportunity_score") or 0.0
    channel = "push" if opportunity >= config.PUSH_OPPORTUNITY_THRESHOLD else "feed"
    _log_alert(market_row, alert_type, chat_id, value=value, channel=channel, icon=icon, highlight=highlight)

    minutes = config.ALERT_COOLDOWN_MINUTES.get(tier, 60)
    db.upsert_cooldown({
        "dedup_key": dedup_key,
        "last_sent_at": now.isoformat(),
        "last_alerted_value": value,
        "cooldown_until": (now + timedelta(minutes=minutes)).isoformat(),
    })
    return True


def _log_alert(market_row: dict, alert_type: str, chat_id, value: float | None,
                channel: str, icon: str = "⏰", highlight: str | None = None) -> None:
    """Always writes to the `alerts` table. Only sends a Telegram message
    when channel == 'push' — 'feed' alerts are logged for /live and
    nothing else, by design."""
    db.insert_alert({
        "market_id": market_row["market_id"],
        "chat_id": chat_id,
        "alert_type": alert_type,
        "triggered_value": value,
        "channel": channel,
    })
    if channel == "push":
        text = formatting.format_market_card(market_row, icon=icon, highlight=highlight)
        keyboard = formatting.market_keyboard(market_row["short_id"], market_row.get("slug"))
        telegram_client.send_message(chat_id, text, reply_markup=keyboard)
