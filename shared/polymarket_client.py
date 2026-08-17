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
    """One paginated pass in a given sort direction, using Polymarket's
    cursor-based keyset pagination.

    CONFIRMED via Polymarket's own changelog (docs.polymarket.com/changelog)
    and live testing: the legacy offset-based GET /markets endpoint has
    been fully sunset — it now returns 422 for literally any request,
    not just ones with a high offset. This is a real, external API
    migration, not the same class of bug as the earlier "offset > ~2100"
    issue (which was this migration already partially in effect). Two
    things changed together: the endpoint (/markets -> /markets/keyset,
    using after_cursor/next_cursor instead of offset) AND the response
    shape (a bare array before, now wrapped as
    {"markets": [...], "next_cursor": "..."}).

    Cursor pagination has no known fixed depth cap the way offset-based
    pagination did, so the two-pass (ascending + descending) coverage
    workaround in fetch_all_active_markets() may no longer be necessary
    — kept for now as a safety net rather than assumed away, since that's
    a separate, lower-risk simplification to make once this fix is
    confirmed working in production.
    """
    markets: list[dict] = []
    cursor: str | None = None
    direction = "ascending" if ascending else "descending"
    with httpx.Client(timeout=30) as client:
        for _ in range(MAX_PAGES):
            params = {
                "limit": PAGE_SIZE,
                "closed": "false",  # current docs-confirmed filter for active markets on keyset endpoints
                "order": "volume24hr",
                "ascending": ascending,
            }
            if cursor:
                params["after_cursor"] = cursor

            resp = client.get(f"{config.GAMMA_API_BASE}/markets/keyset", params=params)
            if resp.status_code >= 400:
                print(
                    f"Gamma API returned {resp.status_code} ({direction} pass, "
                    f"cursor={'set' if cursor else 'none'}); stopping this pass "
                    f"with {len(markets)} markets collected."
                )
                break

            data = resp.json()
            page = data.get("markets") if isinstance(data, dict) else data
            if not page:
                break
            markets.extend(normalize(m) for m in page)

            next_cursor = data.get("next_cursor") if isinstance(data, dict) else None
            if not next_cursor:
                break
            cursor = next_cursor
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

    # How many sibling markets share this event (e.g. "Ballon d'Or Winner
    # 2026" has one binary market per candidate, all under one event) —
    # used to show "one of N candidates" context on the card instead of
    # a lone binary market that looks disconnected from its siblings.
    # NOT VERIFIED LIVE: whether the market-level /markets endpoint's
    # nested "events" entry includes the full sibling "markets" array
    # (confirmed present when fetching an event directly via /events) or
    # just a lightweight reference. Defensive fallback to None either way.
    group_size = None
    if events and isinstance(events[0], dict):
        sibling_markets = events[0].get("markets")
        if isinstance(sibling_markets, list):
            group_size = len(sibling_markets)

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
        "group_size": group_size,
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
