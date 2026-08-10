-- Run this in the Supabase SQL editor after 005_user_settings.sql.
-- Lets market cards show "one of N candidates" for multi-outcome events
-- (e.g. "Ballon d'Or Winner 2026" — many separate binary markets, one
-- per candidate, bundled under one event).

alter table markets add column if not exists group_size integer;
NOTIFY pgrst, 'reload schema';
