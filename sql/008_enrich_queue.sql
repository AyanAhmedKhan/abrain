-- ============================================================
-- gbrain · 008 · enrichment queue (Scrappa persons→LinkedIn)
-- A dedicated pgmq queue so extract can hand off LinkedIn lookups
-- asynchronously (never blocks/breaks the paid pipeline). Idempotent.
-- ============================================================
do $$ begin
  perform pgmq.create('gb_q_enrich');
exception when others then null;  -- already exists
end $$;
