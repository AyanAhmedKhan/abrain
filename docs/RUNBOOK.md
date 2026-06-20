# gbrain — Operator's Runbook

The complete guide to running, operating, and extending **gbrain**, the Dexter
Capital "company brain" on the Hostinger VPS. Everything here reflects the
system as actually deployed.

---

## 1. What it is

gbrain ingests deal-flow (starting with Gmail call notes) and turns each item
into a **structured note**, a **financial time-series**, embeddings for
**semantic search**, and a **knowledge graph** of companies / people / deals.

Flow per item:

```
source (Gmail) → normalize (classify, dedup) → preprocess (text + chunks)
   → extract (Gemini → structured note + entities/observations/tasks)
   → embed (Gemini embeddings → pgvector) → resolve (identity → graph edges) → indexed
```

Cost lives almost entirely in the one **extract** step (Gemini on Vertex
credits). Everything before it is free, and a classifier/gate drops junk and
confidential mail before a token is spent.

---

## 2. Where everything lives

| Thing | Location |
|---|---|
| Code | `/opt/gbrain` (runs as the unprivileged `gbrain` user) |
| Python venv | `/opt/gbrain/.venv` |
| Config / secrets | `/opt/gbrain/.env` (`chmod 600`, owner `gbrain`) |
| Gemini service account | `/opt/gbrain/vertex-sa.json` |
| Gmail OAuth client | `/opt/gbrain/client_secret.json` |
| Gmail mailbox tokens | `/opt/gbrain/tokens/<email>.json` (one per mailbox) |
| Graph viewer (served) | `/opt/gbrain/viewer/` → `127.0.0.1:8099` |
| Latest code mirror | `/root/cbrain/stage/gbrain/` |
| Database | Supabase project `gilnemnskdbyecilsvux` (Postgres + pgvector + pgmq + Storage) |
| Bronze file store | Supabase Storage bucket `gbrain-bronze` (private) |

**Always run Python as the `gbrain` user**, e.g.:
`sudo -u gbrain /opt/gbrain/.venv/bin/python -m <module>`

---

## 3. The services (systemd)

| Unit | Type | What it does |
|---|---|---|
| `gbrain-normalize` | always-on | classify + dedup raw rows |
| `gbrain-preprocess` | always-on | PDF→text, chunking |
| `gbrain-extract` | always-on | Gemini structured extraction (the paid step) |
| `gbrain-embed` | always-on | embeddings → pgvector |
| `gbrain-resolve` | always-on | identity resolution → graph edges |
| `gbrain-sweeper.timer` | every 5 min | re-enqueue any orphaned raw rows |
| `gbrain-gmail.timer` | every 1 min | poll Gmail mailboxes, land new mail *(enable to go live)* |
| `gbrain-viewer.service` | always-on | serve the graph viewer on `127.0.0.1:8099` |
| `gbrain-graph.timer` | every 5 min | refresh the viewer's `graph.json` |

### Everyday commands

```bash
# status of everything
systemctl list-units 'gbrain-*'
systemctl status gbrain-extract

# start / stop / restart a worker
systemctl restart gbrain-extract
systemctl stop  gbrain-extract
systemctl start gbrain-extract

# follow logs (live)
journalctl -u gbrain-extract -f
journalctl -u gbrain-gmail -n 50 --no-pager   # last 50 lines

# turn continuous Gmail ingestion ON
systemctl enable --now gbrain-gmail.timer
# turn it OFF (pause ingestion)
systemctl disable --now gbrain-gmail.timer
```

---

## 4. Connecting Gmail (add a mailbox)

OAuth user tokens — no Workspace admin needed. One token per mailbox; the
connector reads every token in `/opt/gbrain/tokens/`.

**One-time setup (already done):** a Desktop OAuth client at
`/opt/gbrain/client_secret.json` (Google Cloud project `n8n-data-ingstion`,
consent screen *External / Testing*). To authorize a new mailbox, first add its
address as a **Test user** on the OAuth consent screen (Google Cloud → APIs &
Services → OAuth consent screen → Audience → Test users).

**Add the mailbox:**

```bash
# 1) print the consent URL
sudo -u gbrain /opt/gbrain/.venv/bin/python -m workers.connectors.gmail_auth
#    open it in a browser, sign in as that mailbox, click Allow.
#    the browser redirects to a 'localhost' page that fails to load — that's expected.
#    copy that full address-bar URL (it contains ?code=...).

# 2) exchange it for a token (paste the URL as the argument)
sudo -u gbrain /opt/gbrain/.venv/bin/python -m workers.connectors.gmail_auth "http://localhost/?...code=..."
#    → writes /opt/gbrain/tokens/<email>.json
```

Verify auth without ingesting:

```bash
sudo -u gbrain /opt/gbrain/.venv/bin/python -c \
"from workers.connectors import gmail; print([k for k,_ in gmail.accounts()])"
```

---

## 5. Ingesting mail

The connector is **dumb**: it polls Gmail, uploads PDF attachments to bronze,
and INSERTs rows into `gb_raw`. A DB trigger enqueues them; the always-on
workers do the rest. Each mailbox tracks its own position in `gb_sync_cursor`.

```bash
# one manual poll (default window = last 7 days, ≤50 msgs/poll)
sudo -u gbrain /opt/gbrain/.venv/bin/python -m workers.connectors.gmail --once

# continuous (every minute) — the normal mode
systemctl enable --now gbrain-gmail.timer
```

**Backfill more history.** The first poll for a mailbox looks back
`GMAIL_INITIAL_DAYS` (default 7). To pull older mail, widen the window and reset
that mailbox's cursor, then poll:

```bash
# reset cursor for one mailbox (re-scan from scratch; dedup makes this safe)
sudo -u gbrain /opt/gbrain/.venv/bin/python -c \
"from workers.lib.db import connect; connect().execute(\"delete from gb_sync_cursor where source like 'gmail:%'\")"

# poll a wider window once (e.g. last 365 days, up to 200 messages)
sudo -u gbrain env GMAIL_INITIAL_DAYS=365 GMAIL_MAX_RESULTS=200 \
  /opt/gbrain/.venv/bin/python -m workers.connectors.gmail --once
```

Tuning knobs (env, optional): `GMAIL_QUERY`, `GMAIL_INITIAL_DAYS`,
`GMAIL_MAX_RESULTS`, `GMAIL_POLL_SECONDS`.

---

## 6. Watching it work

```bash
sudo -u gbrain /opt/gbrain/.venv/bin/python - <<'PY'
from workers.lib.db import connect
c=connect()
print("status:", dict(c.execute("select status,count(*) from gb_envelope group by status").fetchall()))
print("queues:", [(r['queue_name'],r['queue_length']) for r in c.execute("select * from pgmq.metrics_all()").fetchall()])
print("DLQ:", c.execute("select count(*) from gb_dlq").fetchone()['count'])
PY
```

The status machine: `raw → normalized → (skipped|preprocessed) → extracted →
embedded → resolved → indexed`, plus `failed`. Queue depth 0 + nothing stuck =
idle and healthy.

---

## 7. Seeing the data

### Ask the brain (natural-language Q&A)

```bash
sudo -u gbrain /opt/gbrain/.venv/bin/python -m workers.ask "which fintech companies are raising the most?"
sudo -u gbrain /opt/gbrain/.venv/bin/python -m workers.ask "summarize what Park+ does and its key risks"
sudo -u gbrain /opt/gbrain/.venv/bin/python -m workers.ask "list companies raising over 100 crore with valuation"
```
Grounds Gemini in three retrieved contexts — a compact deal-facts table (list/
numeric questions), a dossier of any company named in the question, and the top-k
nearest call-note chunks (pgvector) — then answers **with citations**, or says
"I don't have that in the brain yet." Retrieval is free; one cheap Gemini call
per question. Code: `workers/ask.py` (importable: `from workers.ask import ask`).

### A. SQL (psql-style, via the venv)

```bash
sudo -u gbrain /opt/gbrain/.venv/bin/python - <<'PY'
import json
from workers.lib.db import connect
c=connect()
# indexed notes
for r in c.execute("""select extraction->>'company_name' co, extraction->>'sector' sec,
    extraction->>'stage' stg, extraction->>'ask_inr_cr' ask
    from gb_envelope where status='indexed' and extraction is not null order by 1""").fetchall():
    print(r['co'], '|', r['sec'], '|', r['stg'], '| ask₹cr', r['ask'])
# financials
print("\nfinancials:")
for r in c.execute("""select e.canonical, o.metric, o.value_num, o.unit, o.period
    from gb_observation o join gb_entity e on e.id=o.entity_id order by 1 limit 30""").fetchall():
    print(' ', r['canonical'], r['metric'], r['value_num'], r['unit'] or '', r['period'] or '')
PY
```

Handy views/queries: `gb_pipeline_status`, `gb_company_360`,
`gb_observation_latest`, `gb_dlq`, `gb_cost_log`, `select gb_graph_json();`.

### B. Semantic search ("ask by meaning")

```bash
sudo -u gbrain /opt/gbrain/.venv/bin/python - <<'PY'
from workers.lib.db import connect
from workers.lib.gemini import embed
c=connect(); q="rare-earth-free EV motor company"
v="["+",".join(f"{x:.6f}" for x in embed([q])[0])+"]"
for r in c.execute("""select e.extraction->>'company_name' co, left(ch.text,90) t,
    round((ch.embedding <=> %s::vector)::numeric,3) d
    from gb_chunk ch join gb_envelope e on e.id=ch.envelope_id
    where ch.embedding is not null order by ch.embedding <=> %s::vector limit 5""",(v,v)).fetchall():
    print(r['d'], r['co'], '—', r['t'].strip())
PY
```

### C. Graph viewer (visual)

It runs as a service on **`127.0.0.1:8099`**. From your laptop in VS Code:
forward port **8099** (Ports panel) and open
**`http://localhost:8099/graph_viewer.html`**.

- Central **Dexter Capital** hub → **sector** rings → **company** tiles →
  **people / deals / documents**.
- Left panel filters: **Entity types**, **Sectors**, **Relationships** — each
  with toggle, **only**, and **all/none**.
- **Radial ⇄ Force** toggle in the header. Click a node for its detail card;
  hover to highlight its connections; search box top-left.

`graph.json` auto-refreshes every 5 min (`gbrain-graph.timer`). To refresh now:

```bash
systemctl start gbrain-graph.service     # re-export immediately
# then hard-refresh the browser (Cmd/Ctrl+Shift+R)
```

---

## 8. Configuration (`/opt/gbrain/.env`)

Key settings (already populated):

```
DATABASE_URL=postgresql://postgres:<pwd>@db.gilnemnskdbyecilsvux.supabase.co:5432/postgres
SUPABASE_URL=https://gilnemnskdbyecilsvux.supabase.co
SUPABASE_SERVICE_KEY=<service_role>          # bronze uploads
BRONZE_BUCKET=gbrain-bronze
GOOGLE_GENAI_USE_VERTEXAI=true               # Gemini via Vertex credits
GOOGLE_CLOUD_PROJECT=sunny-bastion-498008-g1
GOOGLE_CLOUD_LOCATION=global
GOOGLE_APPLICATION_CREDENTIALS=/opt/gbrain/vertex-sa.json
EXTRACT_MODEL=gemini-2.5-flash               # escalates to gemini-2.5-pro on low confidence
EMBED_MODEL=gemini-embedding-001             # 768 dims
SIGNAL_THRESHOLD=0.35
GMAIL_TOKEN_DIR=/opt/gbrain/tokens
GMAIL_QUERY=-in:spam -in:trash -category:promotions -category:social
```

After editing `.env`: `chmod 600 .env && chown gbrain:gbrain .env` and
restart the affected workers.

**To change what the extractor pulls out**, edit the prompt in
`workers/lib/note_schema.py` (the only file that controls extraction output),
then `systemctl restart gbrain-extract`.

**To tune the Gmail classifier** (what's indexed vs skipped), edit
`workers/lib/gmail_filter.py`, then `systemctl restart gbrain-normalize`.

---

## 9. Cost

Only `extract` spends. Watch it:

```bash
sudo -u gbrain /opt/gbrain/.venv/bin/python -c \
"from workers.lib.db import connect; c=connect(); \
print([(r['model'],r['n'],r['usd']) for r in c.execute(\"select model,count(*) n,round(sum(coalesce(usd,0)),4) usd from gb_cost_log group by model\").fetchall()])"
```

Reference: ~50 call notes ≈ a few US cents on Gemini Flash (with ~1/5
auto-escalating to Pro). The classifier skips bulk/automated/confidential mail
so it never reaches a paid call.

---

## 10. Testing (no tokens)

```bash
cd /opt/gbrain
# Gate 0 — dedup
sudo -u gbrain env GBRAIN_FAKE_LLM=1 ./.venv/bin/python -m tests.test_dedup
# Gate M1 — full pipeline, fake LLM
sudo -u gbrain env GBRAIN_FAKE_LLM=1 ./.venv/bin/python -m tests.test_pipeline
# Gate M1 — REAL Gemini (note: must be =0; the test defaults to fake)
sudo -u gbrain env GBRAIN_FAKE_LLM=0 ./.venv/bin/python -m tests.test_pipeline
```

Both use `source like 'test%'`/`'gmail'` test rows and clean up after
themselves.

---

## 11. Deploying code changes

```bash
cd /opt/gbrain
# edit code (mirror lives at /root/cbrain/stage/gbrain), then:
sudo -u gbrain env GBRAIN_FAKE_LLM=1 ./.venv/bin/python -m tests.test_pipeline   # verify
chown -R gbrain:gbrain /opt/gbrain
systemctl restart gbrain-normalize gbrain-preprocess gbrain-extract gbrain-embed gbrain-resolve
```

If you add a Python dependency: add it to `requirements.txt`, then
`./.venv/bin/pip install -r requirements.txt`.

---

## 12. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Worker won't start, "network unreachable" | Supabase direct host is IPv6-only. The VPS has IPv6 so it's fine; if it ever fails, switch `DATABASE_URL` to the **session pooler** (port 5432). Never the **transaction pooler** (6543) — it breaks pgmq. |
| DB password has `@` | In `DATABASE_URL` it must be `%40`. |
| Gmail poll: `unauthorized` / token error | Mailbox not a Test user, or token revoked. Re-run the add-a-mailbox flow (§4). |
| Items stuck at `preprocessed` | The paid `extract` worker is the bottleneck — check `journalctl -u gbrain-extract -f`; it processes one call note at a time. |
| Image-only PDF decks | Current pipeline needs a text layer; scanned/exported decks dead-letter as `scanned_pdf_no_text_layer`. Gemini multimodal reads them — adding that is a planned enhancement. |
| `test_pipeline` shows `(fake-llm)` unexpectedly | The test defaults to fake; pass `GBRAIN_FAKE_LLM=0` for a real run. |
| Failed items | `select * from gb_dlq order by at desc;` |
| Viewer won't load | `systemctl status gbrain-viewer`; ensure port 8099 is forwarded in VS Code. |

---

## 13. What's next (not yet built)

- **Multimodal PDF extraction** — send image decks straight to Gemini (so
  scanned/designed decks work end-to-end).
- **Better forwarded-email cleaning** — strip forward headers / footers before
  embedding to sharpen search.
- **Seed the 92-deal spine** — `python -m workers.seed_spine <csv>` to preload
  canonical companies/deals.
- **More sources** — WhatsApp, Calendar, Drive (same pipeline).
- **"Ask the brain"** — a retrieval/Q&A layer over the embeddings + graph.
- **Logo/avatar enrichment** for the graph viewer.

---

*Quick reference:* logs `journalctl -u gbrain-extract -f` · pause ingest
`systemctl disable --now gbrain-gmail.timer` · add mailbox
`python -m workers.connectors.gmail_auth` · viewer
`http://localhost:8099/graph_viewer.html`.
