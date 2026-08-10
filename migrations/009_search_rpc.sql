-- Run this in the Supabase SQL editor after 008_search_index.sql.
--
-- Replaces the URL-based ilike filter search was using with a Postgres
-- function called via RPC instead. Context: search consistently failed
-- with a Cloudflare edge error ("Worker threw exception") regardless of
-- search term — tested with "elon" and "bitcoin", both failed
-- identically. Ruled out: slow query (a trigram index didn't help),
-- wrong ilike syntax (confirmed correct against Supabase's own docs),
-- and problematic data in specific matching rows (failed for two
-- unrelated terms, not just one). The one thing that distinguishes this
-- query from every other working query in the bot is being the only one
-- using a URL-encoded ilike filter. An RPC call sends the search term as
-- a plain JSON body parameter instead of a URL filter, sidestepping
-- whatever is happening with ilike's URL encoding specifically.

create or replace function search_markets_by_term(search_term text, result_limit int default 10)
returns setof markets
language sql
stable
as $$
  select *
  from markets
  where status = 'active'
    and question ilike '%' || search_term || '%'
  order by opportunity_score desc
  limit result_limit;
$$;

NOTIFY pgrst, 'reload schema';
