-- ============================================================
-- gbrain · 014 · deck-aware email/deck log — exposes the SOURCE (email vs pitch
-- deck, and whether the deck came via Drive upload or an email attachment), the
-- bronze ref to open the original, and the Drive source_url. Idempotent.
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
       case when e.source = 'gmail'              then 'Email'
            when r.payload ? 'source_url'        then 'Pitch deck (Drive)'
            else                                      'Pitch deck (email)'
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
