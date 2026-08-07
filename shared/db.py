from supabase import Client, create_client

from . import config

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
    return _client


def upsert_markets(rows: list[dict]) -> None:
    if not rows:
        return
    get_client().table("markets").upsert(rows, on_conflict="market_id").execute()


def get_markets_by_ids(market_ids: list[str]) -> dict[str, dict]:
    """Bulk-fetch existing rows for a batch of market_ids, keyed by id.
    Used to compute deltas (price/volume/tier change) against the previous
    scan without a query per market."""
    if not market_ids:
        return {}
    result = get_client().table("markets").select("*").in_("market_id", market_ids).execute()
    return {row["market_id"]: row for row in result.data}


def insert_price_snapshots(rows: list[dict]) -> None:
    if not rows:
        return
    get_client().table("price_snapshots").insert(rows).execute()


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
