-- ============================================================
-- gbrain · Phase 0 · Queue topology (pgmq)
-- One queue per stage boundary, exactly as the build spec §3.
-- Idempotent — pgmq.create is a no-op if the queue exists.
-- ============================================================

select pgmq.create('gb_q_normalize');   -- connectors        → normalize worker
select pgmq.create('gb_q_preprocess');  -- gate pass         → preprocess worker (Phase 1)
select pgmq.create('gb_q_extract');     -- preprocess        → batch submitter   (Phase 1, ACCUMULATOR)
select pgmq.create('gb_q_embed');       -- extract handler   → embed batch cron  (Phase 1, ACCUMULATOR)
select pgmq.create('gb_q_resolve');     -- embed handler     → resolve worker    (Phase 4)
select pgmq.create('gb_q_index');       -- resolve worker    → index worker      (Phase 4)
select pgmq.create('gb_q_backfill');    -- backfill jobs     → throttled router  (rate-limited)

-- queue depths at a glance (pairs with gb_pipeline_status):
--   select queue_name, queue_length, oldest_msg_age_sec from pgmq.metrics_all();
