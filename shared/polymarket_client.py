"""
Thin client for Polymarket's public Gamma API (no auth required for reads).

NOTE ON FIELD NAMES: the fields referenced below (question, conditionId,
outcomePrices, volume24hr, liquidity, endDate, tags, clobTokenIds) come
from Polymarket's current public API documentation. In particular,
Polymarket doesn't reliably document a market *creation* timestamp on this
endpoint — `created_on_polymarket_at` will likely come back None, in which
case `discovery_latency_seconds` falls back to None in the scan job (see
README for the honest fallback).

IMPORTANT: `outcomePrices`, `outcomes`, and `clobTokenIds` are returned as
JSON-ENCODED STRINGS (e.g. '["0.62", "0.38"]'), not native arrays — this
is a well-documented Polymarket API quirk. Indexing into the raw string
silently grabs a character instead of a price and fails without an
exception, which is what caused every market card to show a blank
probability until this was fixed. Always json.loads() these fields first.
"""
import json

import httpx

from . import config

PAGE_SIZE = 100
MAX_PAGES = 500  # backstop against runaway pagination; 500 * 100 = 50,000 markets


def fetch_all_active_markets() -> list[dict]:
    """Two passes — highest-volume-first and lowest-volume-first — merged
    and deduplicated by market_id.

    A single volume-descending pass only ever reaches the top ~2,100
    markets by volume before hitting Gamma's pagination wall (see
    `_fetch_sorted` below) — every lower-volume market on the platform
    would be permanently invisible to a "monitor everything" bot with
    only one pass. A second ascending pass covers the opposite end of the
    spectrum, roughly doubling real coverage. Still not a guarantee of
    literally every market if the platform has more than ~4,200 active
    listings at once, but it closes the gap enormously versus one pass.
    """
    high_volume_first = _fetch_sorted(ascending=False)
    low_volume_first = _fetch_sorted(ascending=True)

    merged: dict[str, dict] = {}
    for m in high_volume_first + low_volume_first:
        if m["market_id"]:
            merged[m["market_id"]] = m
    return list(merged.values())


def _fetch_sorted(ascending: bool) -> list[dict]:
    """One paginated pass in a given sort direction. Polymarket's API
    returns a 422 error past a certain offset depth instead of an empty
    page (confirmed in production). That's not documented behavior
    anywhere public, so rather than assume a fixed cutoff, this treats
    any error response as "no more pages for this pass" and returns
    whatever was successfully fetched instead of crashing the whole scan
    over it. `MAX_PAGES` is a hard backstop in case the API ever starts
    returning 200s forever."""
    markets: list[dict] = []
    offset = 0
    direction = "ascending" if ascending else "descending"
    with httpx.Client(timeout=30) as client:
        for _ in range(MAX_PAGES):
            resp = client.get(
                f"{config.GAMMA_API_BASE}/markets",
                params={
                    "limit": PAGE_SIZE,
                    "offset": offset,
                    "active": True,
                    "order": "volume24hr",
                    "ascending": ascending,
                },
            )
            if resp.status_code >= 400:
                print(
                    f"Gamma API returned {resp.status_code} at offset={offset} ({direction} pass); "
                    f"stopping this pass with {len(markets)} markets collected."
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
    outcome_prices = _parse_json_field(raw.get("outcomePrices"))
    price_yes = _safe_float(outcome_prices[0]) if outcome_prices else None

    # Polymarket's public URL (polymarket.com/event/{slug}) needs the
    # EVENT's slug, not the market's own slug — these are two different
    # values, and using the market slug was landing on blank/wrong pages
    # in practice. The /markets response nests an "events" array on each
    # market object; prefer the first event's slug, and only fall back to
    # the market's own slug if no event is attached (some single-market
    # listings may not nest one).
    events = raw.get("events") or []
    event_slug = events[0].get("slug") if events and isinstance(events[0], dict) else None
    slug = event_slug or raw.get("slug")

    return {
        "market_id": raw.get("conditionId"),
        "question": raw.get("question"),
        "slug": slug,
        "tags": _parse_json_field(raw.get("tags")),
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


def _parse_json_field(value) -> list:
    """Handles Gamma's JSON-string-encoded array fields. Returns [] for
    anything that isn't a real list or a string containing one."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError):
            return []
    return []
