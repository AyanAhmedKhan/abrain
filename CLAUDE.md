# CLAUDE.md — gbrain build context & instructions

You are continuing the build of **gbrain**, a unified "company brain" for
**Dexter Capital / Dexter Ventures** (an Indian investment bank + micro-VC).
It ingests deal-flow data from many sources into one queryable intelligence
layer: structured notes, a financial time-series, and a knowledge graph.

Read this whole file before acting. It is the source of truth for what
exists, the conventions, and what to do next.

---

## 1. What gbrain does (one paragraph)

Sources (Gmail, WhatsApp, Calendar, Drive, PDFs, internal deal data) land
raw → are normalized into one canonical envelope → gated (dedup + a cheap
signal score, so junk never costs money) → PDFs/text are extracted and
chunked locally → **Gemini** analyzes each into a structured note → the note
fans out into a typed knowledge layer (entities, financial observations,
tasks) and is embedded into pgvector → a deterministic resolver links people/
companies/deals into a graph. The same document arriving via two channels is
extracted **once** (hash dedup). Cost lives almost entirely in the one LLM
step, which is gated, batched-friendly, and runs on Gemini against Vertex
credits (≈ free).

---

## 2. Locked stack (do not relitigate without asking the user)

| Layer | Choice |
|---|---|
| Database | **Supabase** — Postgres + pgvector + pgmq + Storage. **Database only.** No Edge Functions, no business logic in pg_cron. |
| Bronze files | Supabase Storage bucket `gbrain-bronze` (private) |
| Orchestration (edges) | **n8n** on the VPS (Docker) — triggers, webhooks, pollers, delivery |
| Processing (loops) | **Python workers** on the VPS (systemd) — stateless, idempotent, queue-driven |
| Analysis / extraction | **Gemini 2.5 Flash** (workhorse), escalate to `gemini-2.5-pro` on low confidence. (Gemini 2.0 Flash was SHUT DOWN 2026-06-01 — never use it.) |
| Embeddings | `gemini-embedding-001` (Vertex), MRL-truncated to **768** dims (= `gb_chunk.embedding vector(768)`) |
| Host | Hostinger KVM 4 VPS, Mumbai. Root via SSH. n8n already runs here. |

---

## 3. Current status — what's done vs pending

### Built + tested locally (all green, via `GBRAIN_FAKE_LLM=1`)
- All migrations `001`–`005`.
- Full worker pipeline: `normalize → preprocess → extract → embed → resolve`.
- Gemini client (analysis + embeddings) with a fake mode for testing.
- Knowledge graph: resolve worker, graph SQL, viewer, spine seeder.
- Connectors: `gmail_receiver.json` (v2, downloads PDFs to bronze), `whapi_receiver.json`.
- systemd units, deploy script, `tests/test_dedup.py`, `tests/test_pipeline.py`.

### Done on the LIVE system
- Supabase project `gilnemnskdbyecilsvux` created; migrations **001–003 applied**; `pgmq` + auto-RLS enabled.
- VPS: repo at `/opt/gbrain`, venv built, **M0 workers (normalize + sweeper) deployed**, **Gate 0 (`test_dedup`) passed live**.

### PENDING — this is your job (in order)
1. Apply migrations **004** (graph) and **005** (auto-enqueue) in Supabase SQL Editor.
2. Create the **`gbrain-bronze`** private Storage bucket.
3. Put secrets in `/opt/gbrain/.env`: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (service_role), and `GEMINI_API_KEY` (AI Studio key — simplest) **or** the Vertex trio.
4. Deploy the latest repo to the VPS, install M1 deps, enable all workers.
5. Set `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` in **n8n's environment** (the bronze-upload HTTP node reads them).
6. Import `gmail_receiver.json`; attach Gmail OAuth + Postgres credentials; create a Gmail **"Call Notes"** label + filter; activate.
7. Run `test_pipeline` against live Supabase with **real Gemini** → this is **Gate M1**.
8. Seed the spine: `seed_spine.py` with the user's 92-deal transactions CSV.
9. (Optional) paste the user's Notes-Agent Gemini prompt into `workers/lib/note_schema.py`.

After M1 verifies live: M2 (WhatsApp via `whapi_receiver.json` → same pipeline; run the legacy Notes Agent in parallel until a 10-deck parity check), then M3 (Calendar/Drive), M4 (residual identity resolver only if deterministic coverage <90%), M5 (retrieval/"ask the brain" + governance).

---

## 4. Repo layout

```
sql/            001 foundation · 002 queues · 003 entities(knowledge) · 004 graph · 005 auto_enqueue
workers/
  lib/          db.py · queues.py · signal_score.py · storage.py · gemini.py · note_schema.py
  normalize.py  preprocess.py · extract.py · embed.py · resolve.py · sweeper.py
  seed_spine.py graph_export.py
n8n/            gmail_receiver.json · whapi_receiver.json
tests/          test_dedup.py (Gate 0) · test_pipeline.py (Gate M1)
ops/            deploy.sh · systemd/gbrain-*.service|timer
graph_viewer.html   MASTER_PLAN.md   README.md
```

---

## 5. Conventions — follow these exactly

**The status state machine** (gb_envelope.status):
`raw → normalized → (skipped | preprocessed) → extracted → embedded → resolved → indexed`, plus `failed`. Each worker owns one transition.

**Worker pattern** (every worker matches this — copy it):
- Loop: `pgmq.read(vt, qty)` → for each msg: re-check `status` (idempotency — a redelivered message must be a no-op) → do work → update status → `pgmq.send` to the next queue → `pgmq.archive`.
- On exception: retry until `read_ct >= MAX_READS`, then `gb_dlq` + status `failed` + archive.
- Support `--once` (drain then exit) for tests.
- Connectors stay **dumb**: just `INSERT` into `gb_raw`. The `005` trigger auto-enqueues; never put LLM/parse logic in a connector.

**Migrations**: append-only, numbered, idempotent (`if not exists`, `on conflict`). Never edit a shipped migration; add a new one.

**Cost discipline**: spend only in `extract.py`. Everything upstream is free. Gate (dedup + signal score) before any token. `note_schema.py` is the ONLY file to edit to change the analysis prompt/output.


**Gmail classification** (`workers/lib/gmail_filter.py`): the receiver pulls a
BROAD candidate net (`-in:spam -in:trash -category:promotions -category:social`),
and the classifier decides index-vs-skip per message. Priority: trusted label →
automated/bulk skip → confidential skip (security/finance/HR — never indexed,
body is cleared) → deal signals index → default skip. The word "confidential"
is NOT a deny trigger (decks are confidential). Set `GMAIL_DEAL_LABEL_IDS` (env)
to your Gmail "Call Notes" label ID so label-trust fires. Edit the regex/lists
in that file to tune. Confidential mail never reaches extraction/embedding/graph
and its searchable body is nulled.

**DB access**: `workers/lib/db.py` loads `.env` (python-dotenv) and connects via `DATABASE_URL`. Use the Supabase **direct or session** connection (port 5432) — NEVER the transaction pooler (6543); it breaks pgmq/session semantics.

---

## 6. How to test (no tokens needed)

```bash
cd /opt/gbrain
sudo -u gbrain env GBRAIN_FAKE_LLM=1 ./.venv/bin/python -m tests.test_dedup     # Gate 0
sudo -u gbrain env GBRAIN_FAKE_LLM=1 ./.venv/bin/python -m tests.test_pipeline  # Gate M1 (fake)
```
Both run against live Supabase using `source like 'test%'` rows and clean up
after themselves. `test_pipeline` stubs storage in-memory, so it does NOT need
the bronze bucket. To verify Gate M1 *for real*, set real Gemini creds and run
`test_pipeline` without `GBRAIN_FAKE_LLM` (it will make real calls).

---

## 7. Deploy / update on the VPS

```bash
# from /opt/gbrain (repo already here); to update from a new tarball:
systemctl stop gbrain-normalize gbrain-preprocess gbrain-extract gbrain-embed gbrain-resolve 2>/dev/null
cp /opt/gbrain/.env /root/env.backup
tar -xzf /root/gbrain.tar.gz -C /opt && cp /root/env.backup /opt/gbrain/.env
cd /opt/gbrain && ./.venv/bin/pip install -r requirements.txt
chown -R gbrain:gbrain /opt/gbrain && chmod 600 .env
cp ops/systemd/gbrain-*.service ops/systemd/gbrain-*.timer /etc/systemd/system/ && systemctl daemon-reload
systemctl enable --now gbrain-normalize gbrain-preprocess gbrain-extract gbrain-embed gbrain-resolve gbrain-sweeper.timer
journalctl -u gbrain-extract -f
```
Workers run as the unprivileged `gbrain` user. `.env` must be `chown gbrain:gbrain` + `chmod 600` (db.py reads it).

---

## 8. Known gotchas (these bit us already)

- **Supabase direct host is IPv6-only.** The VPS has IPv6, so it works. If any connection fails "network unreachable," switch `DATABASE_URL` / n8n Postgres cred to the **Session pooler** (host `aws-0-ap-south-1.pooler.supabase.com`-style, port 5432, user `postgres.gilnemnskdbyecilsvux`). Never the transaction pooler (6543).
- **DB password contains `@`.** In a URL (`.env`) it must be `%40`. In n8n's separate password field, use it **raw**. (User should rotate this password — it was exposed in a screenshot.)
- **Hostinger had a broken apt mirror** (`in.mirror.coganng.com`, TLS failures). It's disabled (renamed `ubuntu-mirrors.list.disabled`); `archive.ubuntu.com` works. Install with `--no-install-recommends` to avoid pulling 270MB of build tools — psycopg/pymupdf ship wheels, no compiler needed.
- **Gemini 2.0 Flash shut down 2026-06-01.** Use `gemini-2.5-flash`. If the user's legacy Notes Agent is on 2.0, it broke — flag it.
- **pgmq is not available in a vanilla local Postgres.** On Supabase it's real (enabled). Don't assume it locally.
- Use `GBRAIN_FAKE_LLM=1` for any test you don't want to cost tokens.

---

## 9. Environment variables (`/opt/gbrain/.env`)

```
DATABASE_URL=postgresql://postgres:<PWD-%40-encoded>@db.gilnemnskdbyecilsvux.supabase.co:5432/postgres
SIGNAL_THRESHOLD=0.35
SWEEPER_GRACE_MINUTES=5
SUPABASE_URL=https://gilnemnskdbyecilsvux.supabase.co
SUPABASE_SERVICE_KEY=<service_role key>
BRONZE_BUCKET=gbrain-bronze
GEMINI_API_KEY=<AI Studio key>        # OR the Vertex trio (GOOGLE_GENAI_USE_VERTEXAI=true + project + location + GOOGLE_APPLICATION_CREDENTIALS)
EXTRACT_MODEL=gemini-2.5-flash
ESCALATE_MODEL=gemini-2.5-pro
EMBED_MODEL=gemini-embedding-001
EMBED_DIMS=768
GMAIL_DEAL_LABEL_IDS=Label_xxxx   # your Gmail 'Call Notes' label ID(s), comma-sep
```
n8n also needs `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` in its own environment (Docker compose `environment:`), for the Gmail receiver's bronze-upload node.

---

## 10. Useful queries (verify the brain works)

```sql
select * from gb_pipeline_status;                          -- what's at each stage
select queue_name, queue_length from pgmq.metrics_all();    -- queue depths
select title, extraction->>'company_name', status from gb_envelope where status='indexed' order by ingested_at desc;
select * from gb_company_360 where company = 'Acme Robotics';
select * from gb_observation_latest;                        -- current financials per company
select gb_graph_json();                                     -- full graph (for the viewer)
select * from gb_dlq order by at desc;                      -- failures
```
Graph viewer: `python -m workers.graph_export /root/graph.json`, then open `graph_viewer.html` and load the file.

---

## 11. Working style for you (Claude Code)

- Work the PENDING list (§3) top to bottom. Confirm each gate before moving on.
- Before any destructive DB op or anything touching the live Notes Agent / Whapi channel, **ask the user**.
- Keep connectors dumb and workers idempotent. Match existing patterns.
- After code changes, run the relevant test with `GBRAIN_FAKE_LLM=1` before deploying.
- Don't reorder the locked stack (§2) decisions without asking.
- The user prefers concrete, verified steps over long explanations.
```
```
