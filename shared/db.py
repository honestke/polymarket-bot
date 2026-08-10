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


def get_market(market_id: str) -> dict | None:
    result = get_client().table("markets").select("*").eq("market_id", market_id).execute()
    return result.data[0] if result.data else None


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
