-- ============================================================
-- gbrain · 012 · deal pipeline, financial trends, follow-up inbox (gold views)
-- No table changes: user-set pipeline stage + owner live on the company entity
-- attrs (attrs.pipeline_stage / attrs.deal_owner) so they survive re-ingestion
-- (fan_out merges attrs and never sets those keys). Idempotent.
-- ============================================================

-- Kanban: one card per deal (has_deal companies, plus any company explicitly
-- placed on the board). pipeline_stage defaults to 'Sourced'.
create or replace view gb_deal_pipeline as
select c.company,
       c.entity_id,
       coalesce(e.attrs->>'pipeline_stage', 'Sourced') as pipeline_stage,
       e.attrs->>'deal_owner'                          as owner,
       c.sector, c.stage as round_stage, c.round_type,
       c.ask_inr_cr, c.valuation_inr_cr, c.revenue_inr_cr,
       c.poc, c.fitment, c.last_interaction, c.has_deal
from gb_company_card c
left join gb_entity e on e.id = c.entity_id
where c.has_deal or (e.attrs ? 'pipeline_stage');

-- Financial time-series per company (for trend charts + growth/multiples).
create or replace view gb_company_financials as
select en.canonical as company, en.id as entity_id,
       o.metric, o.value_num, o.unit, o.period, o.as_of, o.created_at, o.envelope_id
from gb_observation o
join gb_entity en on en.id = o.entity_id and en.type = 'company'
where o.value_num is not null;

-- Open follow-ups (action items not done) with company + overdue flag.
create or replace view gb_open_tasks as
select t.id, t.description, t.owner, t.due_date, t.priority, t.created_at,
       co.canonical as company, t.company_id,
       (t.due_date is not null and t.due_date < current_date) as overdue
from gb_task t
left join gb_entity co on co.id = t.company_id
where coalesce(t.status, 'open') not in ('done', 'closed', 'cancelled');
