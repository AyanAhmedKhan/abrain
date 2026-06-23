-- ============================================================
-- gbrain · 011 · edge metadata (employment current/past, role, tenure)
-- Adds a props JSONB to gb_edge so a works_at edge can carry whether the role
-- is current, the title, and start/end — powering "current team" vs "past
-- employees (alumni)" on company surfaces. Idempotent.
-- ============================================================
alter table gb_edge add column if not exists props jsonb not null default '{}'::jsonb;
