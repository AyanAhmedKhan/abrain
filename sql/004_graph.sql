-- ============================================================
-- gbrain · 004 · Knowledge graph layer
-- Traversal + export over gb_entity / gb_edge. Idempotent.
-- Run after 001–003.
-- ============================================================

-- ── 1-hop neighborhood of an entity (both directions) ───────
create or replace function gb_neighbors(p_entity uuid)
returns table(entity_id uuid, entity_type text, canonical text,
              rel text, direction text, via_envelope uuid, occurred_at timestamptz)
language sql stable as $$
  select e2.id, e2.type, e2.canonical, g.rel, 'out', g.envelope_id, g.occurred_at
  from gb_edge g join gb_entity e2 on e2.id = g.dst
  where g.src = p_entity
  union all
  select e1.id, e1.type, e1.canonical, g.rel, 'in', g.envelope_id, g.occurred_at
  from gb_edge g join gb_entity e1 on e1.id = g.src
  where g.dst = p_entity
$$;

-- ── n-hop subgraph around an entity (for the viewer) ─────────
create or replace function gb_subgraph(p_entity uuid, p_depth int default 2)
returns table(src uuid, rel text, dst uuid)
language sql stable as $$
  with recursive walk(src, rel, dst, depth) as (
    select g.src, g.rel, g.dst, 1 from gb_edge g
    where g.src = p_entity or g.dst = p_entity
    union
    select g.src, g.rel, g.dst, w.depth + 1
    from gb_edge g join walk w
      on (g.src in (w.src, w.dst) or g.dst in (w.src, w.dst))
    where w.depth < p_depth
  )
  select distinct src, rel, dst from walk
$$;

-- ── full graph as one JSON document (viewer/export) ─────────
create or replace function gb_graph_json()
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'generated_at', now(),
    'nodes', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', id, 'type', type, 'label', canonical,
        'attrs', attrs,
        'degree', (select count(*) from gb_edge g where g.src = e.id or g.dst = e.id)))
      from gb_entity e), '[]'::jsonb),
    'edges', coalesce((
      select jsonb_agg(jsonb_build_object(
        'source', src, 'target', dst, 'rel', rel,
        'occurred_at', occurred_at, 'envelope_id', envelope_id))
      from gb_edge), '[]'::jsonb)
  )
$$;

-- ── temporal activity per entity (who touched what, when) ───
create or replace view gb_entity_activity as
select e.id as entity_id, e.type, e.canonical,
       g.rel, g.occurred_at, g.envelope_id,
       env.source, env.title
from gb_entity e
join gb_edge g on g.src = e.id or g.dst = e.id
left join gb_envelope env on env.id = g.envelope_id
order by g.occurred_at desc nulls last;

-- ── company 360 view: everything connected to a company ─────
create or replace view gb_company_360 as
select c.id as company_id, c.canonical as company,
       n.entity_type, n.canonical as connected_to, n.rel, n.direction,
       n.occurred_at
from gb_entity c
cross join lateral gb_neighbors(c.id) n
where c.type = 'company';

-- ── helper: find-or-none entity by any key value ────────────
create or replace function gb_entity_by_key(p_value text)
returns uuid language sql stable as $$
  select id from gb_entity
  where keys->>'phone' = p_value
     or keys->>'email' = lower(p_value)
     or keys->>'domain' = lower(p_value)
  limit 1
$$;
