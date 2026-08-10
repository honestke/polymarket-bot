from datetime import datetime, timedelta, timezone

from supabase import Client, create_client

from . import config

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
    return _client


def _chunks(items: list, size: int = 200):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def upsert_markets(rows: list[dict]) -> None:
    if not rows:
        return
    for chunk in _chunks(rows):
        get_client().table("markets").upsert(chunk, on_conflict="market_id").execute()


def get_markets_by_ids(market_ids: list[str]) -> dict[str, dict]:
    """Bulk-fetch existing rows for a batch of market_ids, keyed by id.
    Used to compute deltas (price/volume/tier change) against the previous
    scan without a query per market.

    Chunked because Supabase's `.in_()` filter is sent as a URL query
    parameter — with the whole platform in scope (thousands of ids), a
    single unchunked call overflows the URL length limit. Batches of 200
    keep each request well within normal URL limits regardless of how
    many markets are being tracked.
    """
    if not market_ids:
        return {}
    result: dict[str, dict] = {}
    chunk_size = 200
    for i in range(0, len(market_ids), chunk_size):
        chunk = market_ids[i : i + chunk_size]
        response = get_client().table("markets").select("*").in_("market_id", chunk).execute()
        for row in response.data:
            result[row["market_id"]] = row
    return result


def insert_price_snapshots(rows: list[dict]) -> None:
    if not rows:
        return
    for chunk in _chunks(rows):
        get_client().table("price_snapshots").insert(chunk).execute()


def get_cooldown(dedup_key: str) -> dict | None:
    result = get_client().table("alert_cooldowns").select("*").eq("dedup_key", dedup_key).execute()
    return result.data[0] if result.data else None


def upsert_cooldown(row: dict) -> None:
    get_client().table("alert_cooldowns").upsert(row, on_conflict="dedup_key").execute()


def insert_alert(row: dict) -> dict:
    result = get_client().table("alerts").insert(row).execute()
    return result.data[0]


def insert_ai_analysis(row: dict) -> None:
    get_client().table("ai_analysis").insert(row).execute()


def get_priority_boosts() -> list[dict]:
    return get_client().table("priority_boosts").select("*").execute().data


def get_top_by_volume(limit: int = 10) -> list[dict]:
    result = (
        get_client()
        .table("markets")
        .select("*")
        .eq("status", "active")
        .order("last_volume_24h", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


def search_markets(term: str, limit: int = 5) -> list[dict]:
    """Case-insensitive substring match on the question text. Used by
    /add so boosting a keyword also shows what it currently matches,
    instead of a bare confirmation with no visible effect."""
    result = (
        get_client()
        .table("markets")
        .select("*")
        .eq("status", "active")
        .ilike("question", f"%{term}%")
        .order("opportunity_score", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


def get_top_opportunities(limit: int = 10) -> list[dict]:
    result = (
        get_client()
        .table("markets")
        .select("*")
        .eq("status", "active")
        .order("opportunity_score", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


def get_active_market_ids() -> set[str]:
    """General-purpose helper — not currently used by the resolution
    sweep (see mark_expired_as_resolved for why 'missing from a fetch'
    isn't a safe signal), kept because it's a reasonable primitive other
    features may want later."""
    result = get_client().table("markets").select("market_id").eq("status", "active").execute()
    return {row["market_id"] for row in result.data}


def mark_resolved(market_ids: list[str]) -> None:
    if not market_ids:
        return
    now = datetime.now(timezone.utc).isoformat()
    for chunk in _chunks(market_ids):
        get_client().table("markets").update({"status": "resolved", "updated_at": now}).in_(
            "market_id", chunk
        ).execute()


def mark_expired_as_resolved() -> int:
    """Flips status to 'resolved' for any market whose end_date has
    passed. Deliberately NOT based on 'missing from the latest scan
    fetch' — Gamma's pagination caps each scan at roughly the top ~2,100
    markets by volume (see shared/polymarket_client.py), so a real,
    still-active but lower-volume market can simply fall outside a given
    scan's slice without being resolved. end_date is a property of the
    market itself, independent of what any single fetch happened to
    include, so it doesn't have that failure mode."""
    now_iso = datetime.now(timezone.utc).isoformat()
    result = (
        get_client()
        .table("markets")
        .update({"status": "resolved", "updated_at": now_iso})
        .eq("status", "active")
        .lt("end_date", now_iso)
        .execute()
    )
    return len(result.data or [])


def get_market(market_id: str) -> dict | None:
    result = get_client().table("markets").select("*").eq("market_id", market_id).execute()
    return result.data[0] if result.data else None


def get_active_market_slugs() -> list[dict]:
    """Just market_id + slug for every active market — used to compute
    group_size ourselves (see recompute_group_sizes in scan.py) rather
    than depending on Gamma's nested event.markets array, which the
    /markets endpoint doesn't reliably include."""
    result = get_client().table("markets").select("market_id, slug").eq("status", "active").execute()
    return result.data


def update_group_sizes(size: int, market_ids: list[str]) -> None:
    if not market_ids:
        return
    for chunk in _chunks(market_ids):
        get_client().table("markets").update({"group_size": size}).in_("market_id", chunk).execute()


def get_latest_ai_summary(market_id: str) -> dict | None:
    result = (
        get_client()
        .table("ai_analysis")
        .select("*")
        .eq("market_id", market_id)
        .order("generated_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_recent_snapshots(market_id: str, limit: int = 5) -> list[dict]:
    result = (
        get_client()
        .table("price_snapshots")
        .select("price_yes, volume_24h, captured_at")
        .eq("market_id", market_id)
        .order("captured_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


def get_market_by_short_id(short_id: str) -> dict | None:
    """Used to resolve button presses back to a real market — callback_data
    carries short_id, never the raw market_id (see shared/formatting.py
    for why)."""
    result = get_client().table("markets").select("*").eq("short_id", short_id).execute()
    return result.data[0] if result.data else None


def get_recent_markets(limit: int = 10) -> list[dict]:
    result = (
        get_client()
        .table("markets")
        .select("*")
        .eq("status", "active")
        .order("first_discovered_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


def get_ending_soon(limit: int = 10) -> list[dict]:
    result = (
        get_client()
        .table("markets")
        .select("*")
        .eq("status", "active")
        .in_("current_tier", ["hot", "critical"])
        .order("end_date", desc=False)
        .limit(limit)
        .execute()
    )
    return result.data


def get_ending_in_range(min_days: float, max_days: float | None, limit: int = 10) -> list[dict]:
    """Powers the Ending Soon time-bucket picker. min/max are days from
    now; max_days=None means unbounded (the 'longer than 1 month' bucket).
    Computed client-side against end_date rather than a stored day-count
    column, since 'days remaining' changes every second and storing it
    would go stale between scans."""
    now = datetime.now(timezone.utc)
    min_dt = (now + timedelta(days=min_days)).isoformat()
    query = (
        get_client()
        .table("markets")
        .select("*")
        .eq("status", "active")
        .gte("end_date", min_dt)
        .order("opportunity_score", desc=True)
        .limit(limit)
    )
    if max_days is not None:
        max_dt = (now + timedelta(days=max_days)).isoformat()
        query = query.lte("end_date", max_dt)
    return query.execute().data


def get_top_opportunities_since(since_days: float, limit: int = 10) -> list[dict]:
    """Powers the Best Opportunities Today/Week/Month picker — filters by
    how recently a market was discovered, then ranks by score. A market
    discovered a month ago that's still strong won't show in 'Today', but
    will in 'Month'."""
    since_dt = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
    result = (
        get_client()
        .table("markets")
        .select("*")
        .eq("status", "active")
        .gte("first_discovered_at", since_dt)
        .order("opportunity_score", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


def get_live_feed(limit: int = 15) -> list[dict]:
    """Feed-channel alerts (logged but not pushed — see
    shared/alert_engine.py) joined with the market's current info, most
    recent first. Powers the /live command."""
    result = (
        get_client()
        .table("alerts")
        .select("alert_type, triggered_value, sent_at, markets(question, category, opportunity_score, short_id, slug, current_tier)")
        .eq("channel", "feed")
        .order("sent_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


def get_push_threshold(chat_id: int) -> float:
    """Per-chat push cutoff (0-1). Falls back to config's default if the
    user hasn't customized it — see /threshold in services/bot/commands.py."""
    result = get_client().table("user_settings").select("push_threshold").eq("chat_id", chat_id).execute()
    if result.data:
        return float(result.data[0]["push_threshold"])
    return config.PUSH_OPPORTUNITY_THRESHOLD


def set_push_threshold(chat_id: int, value: float) -> None:
    get_client().table("user_settings").upsert(
        {"chat_id": chat_id, "push_threshold": value, "updated_at": datetime.now(timezone.utc).isoformat()},
        on_conflict="chat_id",
    ).execute()


def set_pending_action(chat_id: int, action: str | None) -> None:
    """Tracks 'this chat is waiting for a specific kind of free-text
    reply' (currently just 'search'). Reliable across every Telegram
    client, unlike depending on reply_to_message threading — see
    migrations/007_pending_action.sql."""
    get_client().table("user_settings").upsert(
        {"chat_id": chat_id, "pending_action": action},
        on_conflict="chat_id",
    ).execute()


def get_and_clear_pending_action(chat_id: int) -> str | None:
    """Reads the pending action, if any, and immediately clears it so a
    normal follow-up message afterward isn't mistakenly captured too."""
    result = get_client().table("user_settings").select("pending_action").eq("chat_id", chat_id).execute()
    action = result.data[0].get("pending_action") if result.data else None
    if action:
        set_pending_action(chat_id, None)
    return action


def get_trending(hours: float = 6, limit: int = 10) -> list[dict]:
    """Markets with a price_move or volume_spike alert (push OR feed —
    trending is about recent movement, not whether it was loud enough to
    interrupt someone) in the last `hours`. Deduplicated to one entry per
    market (the most recent), ranked by current opportunity_score."""
    since_dt = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    result = (
        get_client()
        .table("alerts")
        .select("market_id, sent_at, markets(*)")
        .in_("alert_type", ["price_move", "volume_spike"])
        .gte("sent_at", since_dt)
        .order("sent_at", desc=True)
        .limit(100)
        .execute()
    )
    seen: set[str] = set()
    trending: list[dict] = []
    for row in result.data:
        mid = row.get("market_id")
        if not mid or mid in seen or not row.get("markets"):
            continue
        seen.add(mid)
        trending.append(row["markets"])
    trending.sort(key=lambda m: m.get("opportunity_score") or 0, reverse=True)
    return trending[:limit]


def get_ending_in_calendar_month(year: int, month: int, limit: int = 10) -> list[dict]:
    """Markets resolving within a specific calendar month, e.g. December
    2026 — separate from the relative Ending Soon buckets."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc)
    result = (
        get_client()
        .table("markets")
        .select("*")
        .eq("status", "active")
        .gte("end_date", start.isoformat())
        .lt("end_date", end.isoformat())
        .order("opportunity_score", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


def get_categories() -> list[dict]:
    """Returns [{'category': 'AI', 'count': 42}, ...]. Supabase's client
    doesn't do GROUP BY directly, so this pulls the category column for
    active markets and counts client-side — fine at this scale (a few
    thousand rows), would need a proper SQL view if the platform grew by
    another order of magnitude."""
    result = get_client().table("markets").select("category").eq("status", "active").execute()
    counts: dict[str, int] = {}
    for row in result.data:
        cat = row.get("category") or "Other"
        counts[cat] = counts.get(cat, 0) + 1
    return [{"category": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]


def get_markets_by_category(category: str, limit: int = 10) -> list[dict]:
    result = (
        get_client()
        .table("markets")
        .select("*")
        .eq("status", "active")
        .eq("category", category)
        .order("opportunity_score", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


def save_market(chat_id: int, market_id: str) -> None:
    get_client().table("saved_markets").upsert(
        {"chat_id": chat_id, "market_id": market_id}, on_conflict="chat_id,market_id"
    ).execute()


def unsave_market(chat_id: int, market_id: str) -> None:
    get_client().table("saved_markets").delete().eq("chat_id", chat_id).eq("market_id", market_id).execute()


def get_saved_markets(chat_id: int) -> list[dict]:
    result = (
        get_client()
        .table("saved_markets")
        .select("market_id, markets(*)")
        .eq("chat_id", chat_id)
        .execute()
    )
    return [row["markets"] for row in result.data if row.get("markets")]
