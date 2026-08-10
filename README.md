# Polymarket Intelligence Bot

Monitors **every** active market on Polymarket (no category filter), ranks
opportunities, and gives you a fully button-driven Telegram bot — no
command memorization required. Currently deployed and running.

## Mission

Detect valuable opportunities as early as possible after a market is
created, then monitor them through their entire lifecycle. Discovery
latency is tracked as a first-class metric. See `discovery_latency_seconds`
on the `markets` table.

## What it actually does

- Scans the **entire platform** every 5 minutes (two-pass fetch — see
  "Known limitations" below for why one pass isn't enough).
- Scores every market on a 0–1 `opportunity_score`, plus risk, confidence,
  and source-reliability — all deterministic/free in V1, no AI required.
- **Pushes an instant Telegram alert only for high-scoring events**
  (default cutoff: 85/100, customizable per-user via buttons). Everything
  else that fires a threshold is still logged, just to 📡 Live Updates
  instead of your phone — this is what keeps the bot from becoming noise.
- Detects resolved markets (via `end_date`, not "missing from a scan" —
  see the caveat below on why that distinction matters) and stops
  surfacing them in ranked views.
- Everything is reachable by tapping a button. No slash commands are
  required for normal use.

## The menu

Sent automatically after `/start`, stays pinned under the message box:

| Button | What it shows |
|---|---|
| 🏆 Best Opportunities | Top-ranked markets — pick Today / This Week / This Month |
| 💰 By Volume | Top markets by 24h volume — pick Top 5 / 10 / 20 |
| 🔥 Trending | Markets with real price/volume movement in the last 6 hours |
| 🆕 New Markets | Most recently discovered |
| ⏳ Ending Soon | Pick a relative window (<12h / <24h / <3d / <week / <month / longer) or a specific calendar month |
| 📡 Live Updates | Everything that fired an alert but didn't clear your push threshold |
| 📂 Categories | Browse by category (tap a category to filter) |
| ⭐ Saved | Markets you've tapped ⭐ Save on |
| 🔍 Search | Type a keyword, get matching markets — pure search, no side effects |
| 📊 Stats | How many markets are currently tracked |
| ⚙️ Settings | Push threshold (tap a preset, 20–95), and add/remove category boosts by tapping — no typing needed for either |
| ❓ Help | Full text command reference, for anyone who wants it |

Every market card has three buttons: **Open Market** (direct Polymarket
link, works with zero backend involvement), **View Details**, and **Save**.

`/add <custom keyword>` still exists as a text command for boosting on a
specific word that isn't a category (e.g. a person's name) — that's the
one thing that can't become a button, since a button requires a
predetermined list and a keyword is open-ended by definition. It also
immediately shows what currently matches, not just a bare confirmation.

## Setup

1. **Supabase** — create a free project. Run every file in `migrations/`
   **in order** (001 through the highest-numbered file) in the SQL
   Editor. Each is idempotent (`if not exists`), safe to re-run.
2. **Telegram bot** — message **@BotFather**, `/newbot`, save the token.
   Message your new bot once so Telegram has a chat to reference, then
   visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your
   `chat_id` (or use **@userinfobot** — send it any message, it replies
   with your numeric ID directly, which is the same as your private
   chat_id with any bot).
3. **Anthropic API key** (optional) — from console.anthropic.com. Without
   one, AI summaries are skipped; everything else works fine.
4. **GitHub repository secrets** (Settings → Secrets and variables →
   Actions): `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (the **legacy**
   `service_role` key, not the newer `sb_secret_...` one — see caveat
   below), `TELEGRAM_BOT_TOKEN`, `DEFAULT_CHAT_ID`, and
   `ANTHROPIC_API_KEY` if you have one.
5. **`.github/workflows/*.yml`** — fine-grained GitHub tokens need a
   separate **Workflows** permission (distinct from Contents) to push
   files here. If pushing via API/git fails specifically on these two
   files, add that file manually through GitHub's web editor instead.
6. **Render** — deploy `services/bot/app.py` as a free **web service**
   (not a background worker — Render's free tier only covers web
   services). Build command `pip install -r requirements.txt`, start
   command `uvicorn services.bot.app:app --host 0.0.0.0 --port $PORT`.
   Environment variables: same four/five as the GitHub secrets, plus
   `TELEGRAM_WEBHOOK_SECRET` (any random string you choose).
7. **Register the webhook** (one-time, from any terminal):
   ```
   curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d "url=https://<your-render-app>.onrender.com/webhook" \
     -d "secret_token=<same value as TELEGRAM_WEBHOOK_SECRET>"
   ```
   Confirm it worked: `curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"`
   should show your URL and `"pending_update_count": 0`. The bot's own
   command menu (the native `/` autocomplete in Telegram) registers
   itself automatically every time this service boots — no separate step.
8. Send `/start` to your bot. Done.

## Known limitations (read before assuming something's broken)

- **Coverage isn't literally 100% of the platform.** Gamma's `/markets`
  endpoint returns a 422 error past roughly offset 2,100, regardless of
  sort order. The scan does two passes (highest-volume-first and
  lowest-volume-first) to cover both ends of the spectrum — roughly
  doubling real coverage — but a platform with more than ~4,200
  simultaneously active markets would still have some truly
  middle-of-the-pack ones invisible to both passes. Not solved by more
  passes; would need real cursor-based pagination if Gamma ever exposes
  one.
- **Resolved-market detection uses `end_date`, not "missing from a scan
  result."** A market can legitimately be a real, still-active,
  lower-volume market that simply falls outside a *given* scan's
  ~2,100-market slice — treating "not in this fetch" as "resolved" was a
  real bug caught during development. `end_date < now()` is the only
  signal this bot uses for resolution, since it doesn't depend on what
  any single fetch happened to include.
- **`discovery_latency_seconds` is usually null.** Polymarket doesn't
  reliably expose a market creation timestamp on the Gamma listing
  endpoint. `first_discovered_at` (when this bot first saw it) is the
  honest fallback.
- **Gamma returns `outcomePrices`/`outcomes`/`tags` as JSON-encoded
  strings**, not native arrays — a real, previously-shipped bug came
  from indexing into the raw string instead of parsing it first. Already
  fixed (`shared/polymarket_client.py`), documented here so it's obvious
  if it ever regresses.
- **`group_size`** (the "one of N candidates" label on multi-outcome
  event markets) depends on Gamma's `/markets` response nesting a full
  sibling `markets` array under each market's `events[0]` — confirmed
  true when fetching an *event* directly; not fully verified for the
  market-level endpoint this bot actually calls. If the label is simply
  absent rather than wrong, this is why.
- **Telegram's `callback_data` has a hard 64-byte limit.** Market IDs
  (66-char hex strings) blow past that on their own — every button on
  every card silently failed to send until a short hash (`short_id`)
  was introduced to reference markets in buttons instead of the raw ID.
  Boost-removal buttons truncate long keywords to 45 chars for the same
  reason.
- **Supabase's new `sb_secret_...` API key format isn't compatible with
  the pinned `supabase-py` version** — use the **Legacy** `service_role`
  key (Project Settings → API Keys → "Legacy anon, service_role API
  keys" tab) instead. Using the new key produces a client-side "Invalid
  API key" error before any request is even made.
- **After running a migration, if you get `PGRST204: could not find the
  column... in the schema cache`**, the column exists but Supabase's API
  layer hasn't refreshed its cache yet. Run `NOTIFY pgrst, 'reload
  schema';` (included at the end of every migration file from 002 on).

## AI cost optimization

AI calls (Claude Haiku) are gated strictly behind an alert already having
fired (price move or volume spike) — never on a routine poll, never
per-market just because a market exists. A real "add a second/free LLM"
request was evaluated and declined: the cost this system already incurs
is trivial by design, and a free-tier third-party LLM endpoint is exactly
the kind of dependency that fails silently and unpredictably in an
unattended scheduled job.

## Tuning

Thresholds live in `shared/config.py` — cooldown minutes, price-move and
volume-spike thresholds, tier boundaries, Ending Soon buckets, Best
Opportunities windows. Each user's push threshold is stored per-`chat_id`
in the `user_settings` table and overrides the config default.

## Running tests

```
pip install -r requirements.txt
export SUPABASE_URL=https://fake.supabase.co SUPABASE_SERVICE_KEY=fake TELEGRAM_BOT_TOKEN=fake
pytest tests/
```

Dummy env vars are needed because `shared/config.py` fails fast on
missing secrets at import time, and several test modules transitively
import it. Nothing in the suite touches the network — it's pure-function
coverage (scoring, formatting, Gamma response parsing), not integration
tests against live Supabase/Telegram/Render.

## No trading, no financial advice

This bot's only outputs are alerts, rankings, and a live feed — nothing
here places an order or tells you to. If that ever changes, wallet/key
handling should be a completely separate, carefully isolated component,
never in the same process as the alerting logic.
