-- Run this in the Supabase SQL editor after 002_saved_markets.sql.
--
-- Telegram's inline keyboard callback_data has a strict 64-byte limit.
-- Polymarket's market_id (a 66-character 0x-prefixed hex string) already
-- exceeds that on its own, before adding a prefix like "details:" or
-- "save:". Every button on every market card was silently failing to
-- send because of this. short_id is a 10-character hash, comfortably
-- under the limit, unique enough that collisions are not a realistic
-- concern at this scale (~40 bits of entropy).

alter table markets add column if not exists short_id text;
create unique index if not exists idx_markets_short_id on markets(short_id);
