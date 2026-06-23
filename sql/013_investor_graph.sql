-- ============================================================
-- gbrain · 013 · investor & co-investment intelligence (gold views)
-- Built on investor entities + invests_in edges (workers/investors.py). Idempotent.
-- ============================================================

-- investor → portfolio company (distinct)
create or replace view gb_investor_portfolio as
select distinct i.canonical as investor, i.id as investor_id,
       d.canonical as company, d.id as company_id
from gb_edge ed
join gb_entity i on i.id = ed.src and i.type = 'investor'
join gb_entity d on d.id = ed.dst and d.type = 'company'
where ed.rel = 'invests_in';

-- leaderboard: portfolio size per investor
create or replace view gb_investor_stats as
select investor, investor_id, count(distinct company_id) as portfolio
from gb_investor_portfolio group by 1, 2;

-- co-investors: investor pairs sharing ≥1 portfolio company
create or replace view gb_coinvestors as
select a.investor as investor_a, a.investor_id as a_id,
       b.investor as investor_b, b.investor_id as b_id,
       count(distinct a.company_id) as shared
from gb_investor_portfolio a
join gb_investor_portfolio b on a.company_id = b.company_id and a.investor_id < b.investor_id
group by 1, 2, 3, 4;
