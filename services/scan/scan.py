"""
Unified scan job — runs every 5 minutes via .github/workflows/scan.yml.

Monitors every active market on Polymarket, not a filtered subset. This
replaces the earlier design's separate discovery + lifecycle loops: the
Gamma API's listing endpoint returns every active market in a handful of
paginated calls, so there's no efficiency gain from polling markets
individually or from limiting the initial fetch to a watchlist. One bulk
pass per cycle both finds brand-new markets and updates every tracked one
— which is what makes "monitor the entire platform" affordable on
free-tier infrastructure (see the deployment section of the architecture
doc for the API-call and storage math).

Watchlist ("priority_boosts") entries change ranking and alert
sensitivity only — every market gets scored and tracked regardless of
whether anything matches.
"""
from datetime import datetime, timezone

from shared import alert_engine, config, db, formatting, scoring, telegram_client
from shared.polymarket_client import fetch_all_active_markets


def run() -> None:
    raw_markets = [m for m in fetch_all_active_markets() if m["market_id"]]

    # Polymarket's offset-based pagination can return the same market on
    # more than one page — most likely when many low-volume markets tie
    # on the volume24hr sort key, which makes offset-based ordering
    # unstable across page boundaries. A duplicate market_id in the same
    # upsert batch makes Postgres reject the whole batch (`ON CONFLICT DO
    # UPDATE command cannot affect row a second time`), so dedup before
    # anything else touches the list.
    seen_ids: set[str] = set()
    deduped_markets = []
    for m in raw_markets:
        if m["market_id"] in seen_ids:
            continue
        seen_ids.add(m["market_id"])
        deduped_markets.append(m)
    raw_markets = deduped_markets

    ids = [m["market_id"] for m in raw_markets]
    previous = db.get_markets_by_ids(ids)
    boosts = db.get_priority_boosts()
    now = datetime.now(timezone.utc)

    market_rows: list[dict] = []
    snapshot_rows: list[dict] = []

    for m in raw_markets:
        market_id = m["market_id"]
        prev_row = previous.get(market_id)
        is_new = prev_row is None

        category = scoring.categorize(m["question"], m["tags"])
        days_remaining = scoring.time_remaining_days(m["end_date"])
        tier = scoring.assign_tier(days_remaining)
        old_tier = prev_row["current_tier"] if prev_row else None

        prev_price = prev_row.get("last_price_yes") if prev_row else None
        prev_liquidity = prev_row.get("last_liquidity") if prev_row else None
        volatility_points = abs((m["price_yes"] or 0.0) - (prev_price if prev_price is not None else (m["price_yes"] or 0.0))) * 100
        liquidity_delta = (m["liquidity"] or 0.0) - (prev_liquidity or 0.0)

        confidence = scoring.confidence_score(m["liquidity"], m["volume_24h"])
        risk = scoring.risk_score(m["liquidity"], volatility_points, days_remaining)

        market_age_days = None
        if prev_row and prev_row.get("first_discovered_at"):
            first_seen = datetime.fromisoformat(prev_row["first_discovered_at"].replace("Z", "+00:00"))
            market_age_days = (now - first_seen).total_seconds() / 86400
        reliability = scoring.source_reliability_score(market_age_days)

        discovery_recency_hours = 0.0 if is_new else (market_age_days or 999) * 24
        base_opportunity = scoring.opportunity_score(
            volatility_points=volatility_points,
            volume_24h=m["volume_24h"],
            liquidity_delta=liquidity_delta,
            discovery_recency_hours=discovery_recency_hours,
            confidence=confidence,
        )
        opportunity = scoring.apply_priority_boost(base_opportunity, m["question"], category, boosts)

        row = {
            "market_id": market_id,
            "short_id": formatting.short_id(market_id),
            "question": m["question"],
            "slug": m["slug"],
            "category": category,
            "status": "active",
            "current_tier": tier,
            "last_price_yes": m["price_yes"],
            "last_volume_24h": m["volume_24h"],
            "last_liquidity": m["liquidity"],
            "last_polled_at": now.isoformat(),
            "end_date": m["end_date"],
            "risk_score": risk,
            "confidence_score": confidence,
            "source_reliability_score": reliability,
            "opportunity_score": opportunity,
            "updated_at": now.isoformat(),
        }

        if is_new:
            row["first_discovered_at"] = now.isoformat()
            row["discovery_latency_seconds"] = None
            if m.get("created_on_polymarket_at"):
                try:
                    created = datetime.fromisoformat(m["created_on_polymarket_at"].replace("Z", "+00:00"))
                    row["discovery_latency_seconds"] = int((now - created).total_seconds())
                except ValueError:
                    pass  # creation timestamp present but unparseable — leave latency null rather than guess
        else:
            # first_discovered_at is NOT NULL — every row in a batched
            # upsert must carry it, even rows that aren't new. Carry the
            # ORIGINAL value forward unchanged rather than refreshing it,
            # since this is the core mission KPI and must never drift
            # just because a market got re-scanned.
            row["first_discovered_at"] = prev_row["first_discovered_at"]
            # Same reasoning for discovery_latency_seconds: this column
            # allows NULL, so a missing key here wouldn't crash the batch
            # — but omitting it would silently overwrite an existing
            # market's real latency value with NULL whenever it shares a
            # batch with any new market that does set the key. Carry it
            # forward explicitly instead.
            row["discovery_latency_seconds"] = prev_row.get("discovery_latency_seconds")

        market_rows.append(row)

        chat_id = config.DEFAULT_CHAT_ID
        should_snapshot = tier in ("hot", "critical")
        ai_trigger = False

        if is_new:
            should_snapshot = True
            if opportunity >= config.NEW_MARKET_ALERT_THRESHOLD:
                text = formatting.format_market_card(row, icon="🆕", highlight="Just discovered")
                keyboard = formatting.market_keyboard(row["short_id"], row.get("slug"))
                telegram_client.send_message(chat_id, text, reply_markup=keyboard)
            # Markets below the threshold are still tracked and scored —
            # they surface later via /top or the hourly digest, not lost.
        else:
            price_fired = alert_engine.maybe_alert_price_move(row, prev_price, chat_id)
            volume_fired = alert_engine.maybe_alert_volume_spike(row, prev_row.get("last_volume_24h"), chat_id)
            alert_engine.maybe_alert_tier_change(row, old_tier, chat_id)
            ai_trigger = price_fired or volume_fired
            if price_fired or volume_fired or volatility_points >= config.SNAPSHOT_NOISE_THRESHOLD_POINTS:
                should_snapshot = True

        if should_snapshot:
            snapshot_rows.append({
                "market_id": market_id,
                "price_yes": m["price_yes"],
                "volume_24h": m["volume_24h"],
                "captured_at": now.isoformat(),
            })

        if ai_trigger:
            # Local import: keeps `scan.py` runnable even if the AI
            # dependency/key isn't configured yet, and keeps the AI call
            # strictly gated behind an alert having already fired (see
            # shared/alert_engine.py) rather than running on every market.
            from services.analysis.summarize import summarize_market
            summarize_market(market_id, m["question"], prev_price, m["price_yes"], tier)

    db.upsert_markets(market_rows)
    db.insert_price_snapshots(snapshot_rows)
    print(f"Scan complete: {len(market_rows)} markets processed, {len(snapshot_rows)} snapshots written.")


if __name__ == "__main__":
    run()
