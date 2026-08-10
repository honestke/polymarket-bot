# Polymarket Intelligence Bot — V1

Monitors **every** active market on Polymarket (no category filter), ranks
opportunities, and sends Telegram alerts plus a periodic ranked digest.

## What changed from the earlier design

Earlier drafts scoped monitoring to a watchlist-filtered subset of markets.
This build tracks the entire platform by default. Watchlist entries (the
`priority_boosts` table, `/add` and `/remove` commands) now only weight
*ranking and alert sensitivity* — they never determine which markets get
tracked or scored. Discovery and lifecycle polling were also merged into a
single `services/scan/scan.py` job: since the Gamma API returns every
active market in a handful of paginated calls, there's no efficiency gain
from treating "find new markets" and "update tracked markets" as separate
loops.

## Setup

1. **Supabase** — create a free project, then run `migrations/001_init.sql`
   in the SQL editor. Copy the project URL and the `service_role` key.
2. **Telegram bot** — message **@BotFather**, create a bot, copy the token.
   Send the bot a message, then hit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat_id`.
3. **Anthropic API key** (optional but recommended) — from
   console.anthropic.com. Without one, scans still run fine; AI summaries
   are just skipped (see `services/analysis/summarize.py`).
4. Copy `.env.example` to `.env` and fill in values for local testing.
5. **GitHub Actions** — add the same values as repository secrets
   (Settings → Secrets and variables → Actions). `scan.yml` and
   `digest.yml` start running on schedule as soon as they're on the
   default branch.
6. **Telegram webhook (Render)** — deploy `services/bot/app.py` as a
   Render **free web service** (build command `pip install -r
   requirements.txt`, start command
   `uvicorn services.bot.app:app --host 0.0.0.0 --port $PORT`). Once
   deployed, register the webhook:
   ```
   curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d "url=https://<your-render-app>.onrender.com/webhook" \
     -d "secret_token=<same value as TELEGRAM_WEBHOOK_SECRET>"
   ```

## Before you trust this in production, verify these

- **Gamma API field names.** `shared/polymarket_client.py` assumes field
  names (`conditionId`, `outcomePrices`, `volume24hr`, `endDate`, `tags`,
  etc.) from Polymarket's public documentation. This was written without
  live network access to the API from the environment that built it — run
  ```
  python -c "from shared.polymarket_client import fetch_all_active_markets; print(fetch_all_active_markets()[:2])"
  ```
  before trusting it, and fix `normalize()` if the live response differs.
- **`discovery_latency_seconds` will likely be `None`.** Polymarket
  doesn't reliably expose a market creation timestamp on the Gamma
  listing endpoint. If it's missing in practice, treat
  `first_discovered_at` (when *this bot* first saw the market) as the
  honest best-available proxy for "how fast did we catch it" — true
  seconds-since-creation isn't measurable from this API alone unless a
  future Polymarket API update adds the field.
- **GitHub Actions cron granularity.** `*/5 * * * *` is the practical
  minimum, and scheduled runs can lag a few minutes under load, especially
  on public runners. Fine for Warm/Background tiers; less fine for
  Critical (final 24h) — that's exactly the gap the V2 WebSocket upgrade
  in the architecture doc is meant to close.
- **Storage growth.** With the whole platform in scope (thousands of
  active markets), `price_snapshots` only gets a row when a market is in
  the Hot/Critical tier or moves more than
  `SNAPSHOT_NOISE_THRESHOLD_POINTS`. Everything else just updates the
  `markets` row in place. Still worth watching Supabase's free 500MB cap;
  tighten the noise threshold if you approach it.
- **No trading, no financial advice.** This bot's only outputs are alerts
  and a ranked digest — nothing here places an order or tells you to. If
  that ever changes, treat wallet/key handling as a completely separate,
  carefully isolated component (see the Security section of the
  architecture doc).

## Tuning

Every threshold lives in `shared/config.py` — cooldown minutes, price-move
and volume-spike thresholds, the new-market alert score cutoff, and tier
boundaries. Treat the shipped numbers as a starting point: you won't know
the right values until you've watched a week or two of real alerts against
real market behavior.

## Running tests

```
pip install -r requirements.txt
export SUPABASE_URL=https://fake.supabase.co SUPABASE_SERVICE_KEY=fake TELEGRAM_BOT_TOKEN=fake
pytest tests/
```

The dummy env vars are needed because `shared/config.py` fails fast on
missing secrets at import time (by design — see its comments), and some
test modules import code that pulls in `shared/config.py` transitively.
No real credentials are used or contacted; nothing in the test suite
touches the network.
