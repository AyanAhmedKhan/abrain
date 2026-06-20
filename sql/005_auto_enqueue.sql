-- ============================================================
-- gbrain · 005 · Auto-enqueue on raw landing
-- A trigger on gb_raw sends the pgmq message itself, so ANY
-- insert path (n8n Postgres node, n8n Supabase node, REST,
-- psql, workers) feeds the pipeline — connectors no longer
-- need to call pgmq.send explicitly. The sweeper remains the
-- backstop. Idempotent.
-- ============================================================

create or replace function gb_raw_auto_enqueue()
returns trigger language plpgsql as $$
begin
  perform pgmq.send('gb_q_normalize',
                    jsonb_build_object('raw_id', new.id::text));
  return new;
end $$;

drop trigger if exists gb_raw_enqueue on gb_raw;
create trigger gb_raw_enqueue
  after insert on gb_raw
  for each row execute function gb_raw_auto_enqueue();

-- NOTE: existing connector SQL that still calls pgmq.send() after the
-- insert is harmless — normalize is idempotent, a double message is a
-- no-op — but connectors can now be simplified to a bare INSERT.
