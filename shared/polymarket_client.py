"""
Thin client for Polymarket's public Gamma API (no auth required for reads).

NOTE ON FIELD NAMES: the fields referenced below (question, conditionId,
outcomePrices, volume24hr, liquidity, endDate, tags, clobTokenIds) come
from Polymarket's current public API documentation. This module was
written without live network access to gamma-api.polymarket.com from
this environment, so it hasn't been tested against a real response.
Before relying on it, run:

    python -c "from shared.polymarket_client import fetch_all_active_markets; \
               print(fetch_all_active_markets()[:2])"

and adjust `normalize()` if any field names have changed. In particular,
Polymarket doesn't reliably document a market *creation* timestamp on this
endpoint — `created_on_polymarket_at` will likely come back None, in which
case `discovery_latency_seconds` falls back to None in the scan job (see
README for the honest fallback).
"""
import httpx

from . import config

PAGE_SIZE = 100


def fetch_all_active_markets() -> list[dict]:
    """Paginate through every active market via offset/limit. Returns a
    list of normalized dicts. A handful of requests covers the whole
    platform (thousands of markets / 100 per page), well within Gamma's
    rate limits."""
    markets: list[dict] = []
    offset = 0
    with httpx.Client(timeout=30) as client:
        while True:
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
            resp.raise_for_status()
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
        "created_on_polymarket_at": raw.get("createdAt"),  # best-effort, may be absent
        "active": raw.get("active", True),
    }


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
