"""
Thin client for Polymarket's public Gamma API (no auth required for reads).

NOTE ON FIELD NAMES: the fields referenced below (question, conditionId,
outcomePrices, volume24hr, liquidity, endDate, tags, clobTokenIds) come
from Polymarket's current public API documentation. In particular,
Polymarket doesn't reliably document a market *creation* timestamp on this
endpoint — `created_on_polymarket_at` will likely come back None, in which
case `discovery_latency_seconds` falls back to None in the scan job (see
README for the honest fallback).
"""
import httpx

from . import config

PAGE_SIZE = 100
MAX_PAGES = 500  # backstop against runaway pagination; 500 * 100 = 50,000 markets


def fetch_all_active_markets() -> list[dict]:
    """Paginate through every active market via offset/limit. Returns a
    list of normalized dicts.

    Polymarket's API returns a 422 error past a certain offset depth
    instead of an empty page (confirmed in production). That's not
    documented behavior anywhere public, so rather than assume a fixed
    cutoff, this treats any error response as "no more pages" and returns
    whatever was successfully fetched instead of crashing the whole scan
    over it. `MAX_PAGES` is a hard backstop in case the API ever starts
    returning 200s forever.
    """
    markets: list[dict] = []
    offset = 0
    with httpx.Client(timeout=30) as client:
        for _ in range(MAX_PAGES):
            resp = client.get(
                f"{config.GAMMA_API_BASE}/markets",
                params={
                    "limit": PAGE_SIZE,
                    "offset": offset,
                    "active": True,
                    "order": "volume24hr",
                    "ascending": False,
                },
            )
            if resp.status_code >= 400:
                print(
                    f"Gamma API returned {resp.status_code} at offset={offset}; "
                    f"stopping pagination with {len(markets)} markets collected."
                )
                break
            page = resp.json()
            if not page:
                break
            markets.extend(normalize(m) for m in page)
            if len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    return markets


def normalize(raw: dict) -> dict:
    outcome_prices = raw.get("outcomePrices") or []
    price_yes = _safe_float(outcome_prices[0]) if outcome_prices else None
    return {
        "market_id": raw.get("conditionId"),
        "question": raw.get("question"),
        "slug": raw.get("slug"),
        "tags": raw.get("tags") or [],
        "price_yes": price_yes,
        "volume_24h": _safe_float(raw.get("volume24hr")),
        "liquidity": _safe_float(raw.get("liquidity")),
        "end_date": raw.get("endDate"),
        "created_on_polymarket_at": raw.get("createdAt"),
        "active": raw.get("active", True),
    }


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
