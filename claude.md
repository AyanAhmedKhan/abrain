# CLAUDE.md — gbrain build context & instructions

You are continuing the build of **gbrain**, a unified "company brain" for
**Dexter Capital / Dexter Ventures** (Indian investment bank + micro-VC).
It ingests deal-flow from many sources into one queryable layer: structured
notes, a financial time-series, and a knowledge graph.

**Read this whole file before doing anything.** It is the source of truth for
what exists, the conventions, and what to do next. The user is non-trivially
technical but cautious — prefers concrete, verified steps, and does NOT want
their production n8n touched.

---

## 1. What gbrain does

Sources (Gmail first; then WhatsApp, Calendar, Drive, dashboard) land raw →
**normalize** into one canonical envelope → **gate** (dedup + signal score, or
for Gmail a rule-based classifier) so junk/confidential never costs money →
**preprocess** (PDF→text, page-aware chunks) → **extract** (Gemini analyzes
into a structured note + fans out to entities/observations/tasks) → **embed**
(Gemini → pgvector) → **resolve** (deterministic identity resolution → graph
edges) → indexed & queryable. Same document via two channels = extracted once
(hash dedup). Cost lives almost entirely in the one Gemini step; it's gated and
runs on Vertex credits (≈ free).

---

## 2. Locked stack (do not relitigate without asking the user)

| Layer | Choice |
|---|---|
| Database | **Supabase** — Postgres + pgvector + pgmq + Storage. Database ONLY. |
| Bronze files | Supabase Storage bucket `gbrain-bronze` (private) |
| **Gmail ingestion** | **Standalone Python connector** (`workers/connectors/gmail.py`), NOT n8n. User wants n8n untouched. |
| Orchestration (edges) | n8n stays for later delivery-back only; not used for ingestion now |
| Processing | Python workers on the VPS (systemd), stateless, idempotent, queue-driven |
| Analysis | **Gemini 2.5 Flash** (workhorse), escalate to `gemini-2.5-pro` on low confidence. (Gemini 2.0 Flash SHUT DOWN 2026-06-01 — never use.) |
| Embeddings | `gemini-embedding-001` (Vertex), MRL → **768** dims (= `gb_chunk.embedding vector(768)`) |
| Host | Hostinger KVM 4 VPS, Mumbai. Install at **`/opt/gbrain`**, run as unprivileged **`gbrain`** user (NOT root, NOT /root). n8n already runs here in Docker — leave it alone. |
| Gmail auth | **Service account + domain-wide delegation** (recommended; Workspace, no browser). OAuth token is the fallback. |

---

## 3. Current status

### Built + tested locally — ALL GREEN via `GBRAIN_FAKE_LLM=1`
Entire system is written and passing: migrations 001–005, the full worker
pipeline (normalize→preprocess→extract→embed→resolve), the Gemini client, the
knowledge graph (resolve + graph SQL + viewer + spine seeder), the Gmail
classifier, and the standalone Gmail connector. `tests/test_pipeline.py` drives
a PDF + emails through every stage and asserts the note, knowledge fan-out,
embeddings, cross-channel dedup, the classifier (confidential mail skipped +
body cleared), and the graph. `tests/test_dedup.py` is Gate 0.

### Live on the real system
- Supabase project `gilnemnskdbyecilsvux`: migrations **001–003 applied**; pgmq + auto-RLS on.
- VPS: repo at `/opt/gbrain`, venv, **M0 workers (normalize + sweeper) deployed, Gate 0 passed.**

### PENDING — your job, in order (this gets Milestone 1 live)
1. **Deploy the latest code** to `/opt/gbrain` (preserve `.env`), `pip install -r requirements.txt`, `chown -R gbrain:gbrain`, install all systemd units, `daemon-reload`.
2. **Apply migrations 004 and 005** in Supabase SQL Editor.
3. **Create the `gbrain-bronze`** private Storage bucket.
4. **Secrets into `/opt/gbrain/.env`**: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (service_role), `GEMINI_API_KEY` (or the Vertex trio).
5. **Gmail auth** (service account preferred): create SA + key at `/opt/gbrain/sa.json`, enable Gmail API, authorize the SA client-id for `gmail.readonly` in Workspace Admin (domain-wide delegation), set `GMAIL_SERVICE_ACCOUNT_FILE` + `GMAIL_IMPERSONATE` in `.env`. Set `GMAIL_DEAL_LABEL_IDS` to the "Call Notes" label id.
6. **Gate M1**: run `tests/test_pipeline.py` with `GBRAIN_FAKE_LLM=1`, then once with real Gemini.
7. **Enable workers**: `gbrain-normalize preprocess extract embed resolve`, plus timers `gbrain-sweeper.timer gbrain-gmail.timer`.
8. **Seed the spine**: `python -m workers.seed_spine <92-deal CSV>`.
9. (optional) paste the user's Notes-Agent prompt into `workers/lib/note_schema.py`.
10. **Verify live**: send a real call-note email (with a PDF) → confirm a structured note in `gb_envelope.extraction` and edges in the graph (`graph_export.py` → `graph_viewer.html`).

After M1 verifies: M2 (WhatsApp via `n8n/whapi_receiver.json` OR a connector → same pipeline; run legacy Notes Agent in parallel until 10-deck parity), M3 (Calendar + Drive + dashboard spine), M4 (add a Gemini residual identity resolver only if deterministic edge coverage <90%), M5 (retrieval / "ask the brain" + governance + budget caps).

---

## 4. File map

```
sql/
  001_foundation.sql   13 tables, indexes, RLS, gb_pipeline_status view
  002_queues.sql       7 pgmq queues
  003_entities.sql     typed knowledge layer: views (gb_company/person/investor/deal/meeting/document),
                       gb_observation (financial time-series), gb_task, gb_pipeline
  004_graph.sql        gb_neighbors/gb_subgraph/gb_graph_json, gb_company_360, gb_entity_activity
  005_auto_enqueue.sql trigger: any INSERT into gb_raw auto-sends to gb_q_normalize
workers/
  lib/db.py            connection; loads .env (python-dotenv); DATABASE_URL
  lib/queues.py        pgmq send/read/archive + DLQ helper; queue name constants
  lib/signal_score.py  generic gate scoring + DEAL vocabulary regex
  lib/gmail_filter.py  Gmail classifier (index vs skip; confidential exclusion)
  lib/storage.py       Supabase Storage upload/download (bronze)
  lib/gemini.py        Gemini analysis + embeddings; FAKE mode (GBRAIN_FAKE_LLM=1)
  lib/note_schema.py   THE analysis prompt — edit to match the user's note format
  normalize.py         Stage 1+2: envelope + gate (Gmail → classifier)
  preprocess.py        Stage 3: PDF→text (PyMuPDF), page-aware chunks; scanned→DLQ
  extract.py           Stage 4: Gemini → note → entities/observations/tasks → cost log
  embed.py             Stage 5: gemini-embedding-001 → pgvector → resolve
  resolve.py           Stage 6: deterministic identity resolution → graph edges
  sweeper.py           backstop: re-enqueues orphaned gb_raw
  seed_spine.py        load 92-deal CSV → canonical entities (the spine)
  graph_export.py      dump gb_graph_json() → graph.json (for the viewer)
  connectors/gmail.py  standalone Gmail poller (no n8n) — lands emails + PDFs
  connectors/gmail_auth.py  one-time OAuth helper (run on a laptop, copy token.json)
n8n/                   gmail_receiver.json / whapi_receiver.json — OPTIONAL (user chose the connector)
tests/test_dedup.py    Gate 0
tests/test_pipeline.py Gate M1 (full pipeline + classifier + graph)
ops/deploy.sh          VPS setup; ops/systemd/*.service|timer  — one per worker
graph_viewer.html      D3 knowledge-graph viewer (load graph.json)
MASTER_PLAN.md README.md requirements.txt .env.example
```

---

## 5. Pipeline & status state machine

`raw → normalized → (skipped | preprocessed) → extracted → embedded → resolved → indexed`, plus `failed`.
Each worker owns one transition. Queues (pgmq): `gb_q_normalize → gb_q_preprocess → gb_q_extract → gb_q_embed → gb_q_resolve → gb_q_index`. The only paid step is `extract`.

---

## 6. Conventions — follow exactly

- **Idempotency**: every worker re-checks `status` before acting; a redelivered pgmq message must be a no-op. Upserts are conflict-safe.
- **Worker loop**: `pgmq.read(vt, qty)` → per msg: re-check status → work → set status → `pgmq.send` next → `pgmq.archive`. On error: retry to `MAX_READS` then `gb_dlq` + status `failed` + archive. Support `--once`.
- **Connectors stay dumb**: just INSERT into `gb_raw`; the 005 trigger enqueues. No LLM/parse logic in a connector.
- **Gmail classifier** (`gmail_filter.py`): priority = trusted label → automated/bulk skip → confidential skip (security/finance/HR; body is CLEARED; never indexed) → deal signals index → default skip. The word "confidential" is NOT a deny trigger (decks are confidential). Tune the regex/lists in that file.
- **Migrations**: append-only, numbered, idempotent. Never edit a shipped one.
- **Cost**: spend only in `extract.py`. `note_schema.py` is the only file to change the prompt.
- **DB access**: direct or **session** pooler (port 5432). NEVER the transaction pooler (6543) — breaks pgmq/session semantics.
- **Install**: `/opt/gbrain`, run as `gbrain` user. `.env` is `chown gbrain:gbrain` + `chmod 600`.

---

## 7. Testing (no tokens needed)

```bash
cd /opt/gbrain
sudo -u gbrain env GBRAIN_FAKE_LLM=1 ./.venv/bin/python -m tests.test_dedup
sudo -u gbrain env GBRAIN_FAKE_LLM=1 ./.venv/bin/python -m tests.test_pipeline
```
Both run against live Supabase using `source like 'test%'`/`source='gmail'` test rows and clean up. `test_pipeline` stubs storage in-memory (no bronze needed). For a real Gate M1, set Gemini creds and run `test_pipeline` WITHOUT `GBRAIN_FAKE_LLM`.

---

## 8. Deploy / update

```bash
# new tarball at /root/gbrain.tar.gz
systemctl stop gbrain-normalize gbrain-preprocess gbrain-extract gbrain-embed gbrain-resolve 2>/dev/null
cp /opt/gbrain/.env /root/env.backup
tar -xzf /root/gbrain.tar.gz -C /opt && cp /root/env.backup /opt/gbrain/.env
cd /opt/gbrain && ./.venv/bin/pip install -r requirements.txt
chown -R gbrain:gbrain /opt/gbrain && chmod 600 .env
cp ops/systemd/gbrain-*.service ops/systemd/gbrain-*.timer /etc/systemd/system/ && systemctl daemon-reload
sudo -u gbrain env GBRAIN_FAKE_LLM=1 ./.venv/bin/python -m tests.test_pipeline
systemctl enable --now gbrain-normalize gbrain-preprocess gbrain-extract gbrain-embed gbrain-resolve gbrain-sweeper.timer gbrain-gmail.timer
journalctl -u gbrain-extract -f
```
`pip install` may pull google-api libs; if apt is ever needed use `--no-install-recommends` (a broken mirror was disabled; build tools are unneeded — wheels only).

---

## 9. Gmail auth (recommended: service account)

1. Google Cloud → enable Gmail API → create a Service Account → JSON key → `/opt/gbrain/sa.json`.
2. Workspace Admin (admin.google.com) → Security → API controls → Domain-wide delegation → add the SA **client id** with scope `https://www.googleapis.com/auth/gmail.readonly`. **(Most-missed step — without it you get "unauthorized".)**
3. `.env`: `GMAIL_SERVICE_ACCOUNT_FILE=/opt/gbrain/sa.json`, `GMAIL_IMPERSONATE=<mailbox that gets call notes>`.
Fallback (single mailbox, no admin): run `workers/connectors/gmail_auth.py` on a laptop → copy `token.json` to the VPS → set `GMAIL_TOKEN_FILE`.

Test one poll: `sudo -u gbrain ./.venv/bin/python -m workers.connectors.gmail --once`

---

## 10. Env reference (`/opt/gbrain/.env`)

```
DATABASE_URL=postgresql://postgres:<PWD-%40-encoded>@db.gilnemnskdbyecilsvux.supabase.co:5432/postgres
SUPABASE_URL=https://gilnemnskdbyecilsvux.supabase.co
SUPABASE_SERVICE_KEY=<service_role>
BRONZE_BUCKET=gbrain-bronze
GEMINI_API_KEY=<AI Studio key>     # OR GOOGLE_GENAI_USE_VERTEXAI=true + project + location + GOOGLE_APPLICATION_CREDENTIALS
EXTRACT_MODEL=gemini-2.5-flash
ESCALATE_MODEL=gemini-2.5-pro
EMBED_MODEL=gemini-embedding-001
EMBED_DIMS=768
SIGNAL_THRESHOLD=0.35
GMAIL_SERVICE_ACCOUNT_FILE=/opt/gbrain/sa.json
GMAIL_IMPERSONATE=<mailbox>
GMAIL_DEAL_LABEL_IDS=Label_xxxx
GMAIL_QUERY=-in:spam -in:trash -category:promotions -category:social
```

---

## 11. Gotchas (these already bit us)

- Supabase direct host is **IPv6-only**; VPS has IPv6 so it works. On failure use the **Session pooler** (port 5432, user `postgres.gilnemnskdbyecilsvux`). Never transaction pooler (6543).
- DB password contains `@` → `%40` in the URL, raw in form fields. (User should rotate it — exposed in a screenshot.)
- Gemini 2.0 Flash is dead (2026-06-01) → `gemini-2.5-flash`. If the user's legacy Notes Agent is on 2.0, flag it.
- pgmq is not in a vanilla local Postgres; it IS on Supabase.
- `GBRAIN_FAKE_LLM=1` for any test you don't want to cost tokens.
- Do NOT touch the n8n container / docker-compose — Gmail goes via the Python connector.

---

## 12. Verification queries

```sql
select * from gb_pipeline_status;
select queue_name, queue_length from pgmq.metrics_all();
select source, status, skip_reason, title, extraction->>'company_name' from gb_envelope order by ingested_at desc limit 20;
select skip_reason, count(*) from gb_envelope where source='gmail' group by skip_reason;  -- classifier behaviour
select * from gb_company_360 where company = 'X';
select * from gb_observation_latest;
select * from gb_dlq order by at desc;
select gb_graph_json();
```

---

## 13. Working style for you (Claude Code)

- Work the PENDING list (§3) top to bottom; confirm each gate before moving on.
- Before anything destructive, or anything touching the n8n container / live Whapi channel / Notes Agent: **ask the user**.
- Keep connectors dumb, workers idempotent; match existing patterns.
- After code changes, run the relevant test with `GBRAIN_FAKE_LLM=1` before deploying.
- Don't relitigate the locked stack (§2) without asking.
- Start by reading this file and reporting the current state you find on the VPS and in Supabase.
