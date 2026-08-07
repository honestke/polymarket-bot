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
