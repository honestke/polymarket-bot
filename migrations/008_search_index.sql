-- Run this in the Supabase SQL editor after 007_pending_action.sql.
--
-- Speeds up /search (ilike '%term%' on question). A leading-wildcard
-- LIKE/ILIKE pattern can't use a normal B-tree index — Postgres has to
-- scan every row and pattern-match its text. Across ~8,000 active
-- markets, that's real work, and is the most likely explanation for why
-- Search specifically (not any other command) keeps hitting a Cloudflare
-- edge-layer error: a slow scan is more likely to trip a timeout than
-- the simple filtered/sorted queries every other command uses.
--
-- pg_trgm is Postgres's standard extension for fast substring search —
-- this makes ilike '%term%' use an index instead of a full scan.

create extension if not exists pg_trgm;
create index if not exists idx_markets_question_trgm on markets using gin (question gin_trgm_ops);
NOTIFY pgrst, 'reload schema';
