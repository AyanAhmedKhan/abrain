-- ============================================================
-- gbrain · 015 · origin-aware deck/email log. Decks can now arrive three ways:
--   Drive link, direct computer upload, or an email attachment. The connector
--   stamps gb_raw.payload->>'origin' (drive|computer|email); this view turns it
--   into a human SOURCE label. Falls back to the legacy source_url heuristic so
--   rows ingested before 015 still classify. Idempotent (drop + recreate).
-- ============================================================
drop view if exists gb_email_log;
create view gb_email_log as
select to_char(e.occurred_at, 'YYYY-MM-DD')      as date,
       e.occurred_at,
       e.source,
       e.title,
       e.extraction->>'company_name'             as company,
       e.extraction->>'summary'                  as summary,
       e.extraction->>'poc'                      as poc,
       e.extraction->>'fitment'                  as fitment,
       e.actors->>'from'                         as from_actor,
       e.id                                      as envelope_id,
       case when e.source = 'gmail'                    then 'Email'
            when r.payload->>'origin' = 'drive'        then 'Pitch deck (Drive)'
            when r.payload->>'origin' = 'computer'     then 'Pitch deck (uploaded)'
            when r.payload->>'origin' = 'email'        then 'Pitch deck (email)'
            when r.payload ? 'source_url'              then 'Pitch deck (Drive)'   -- legacy
            else                                            'Pitch deck (email)'
       end                                       as kind,
       att.storage_ref                           as deck_ref,
       r.payload->>'source_url'                  as source_url,
       r.payload->>'filename'                    as filename
from gb_envelope e
left join gb_raw r on r.id = e.raw_id
left join lateral (select storage_ref from gb_attachment a
                    where a.envelope_id = e.id limit 1) att on true
where e.source in ('gmail', 'pdf') and e.status = 'indexed'
order by e.occurred_at desc nulls last;
