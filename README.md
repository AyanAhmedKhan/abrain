# gbrain

**The company brain for Dexter Capital / Dexter Ventures.**

gbrain turns scattered deal-flow — Gmail call notes, decks, WhatsApp, internal
data — into one queryable intelligence layer: **structured notes**, a
**financial time-series**, **semantic search**, and a **knowledge graph** of the
companies, people, and deals you track. The same document arriving through two
channels is extracted **once**. Cost lives almost entirely in a single,
cost-gated LLM step that runs on Gemini against Vertex credits — effectively free
at Dexter's volume.

```
sources ─▶ normalize ─▶ preprocess ─▶ extract ─▶ embed ─▶ resolve ─▶ indexed
          classify+dedup  PDF→chunks   Gemini      pgvector   graph
                                       (the only paid step)
```

---

## Why it exists

Deal intelligence is normally trapped in inboxes, threads, and one analyst's
memory. gbrain ingests it raw, normalizes it into a single canonical envelope,
gates out junk and confidential mail **before** any token is spent, then fans
each item into a typed knowledge layer that you can query by SQL, by semantic
search, or in plain English. It replaces the old "Notes Agent" spreadsheet
pattern with a durable, idempotent, queue-driven system where all intelligence
lives behind the queue — not inside fragile connectors.

---

## What you get

| Capability | What it does |
|---|---|
| 🗂 **Structured notes** | Every call note / deck → a typed note via Gemini (company, sector, stage, ask, financials, summary). |
| 📈 **Financial time-series** | Revenue, valuation, raise, and other observations tracked over time per company (`gb_observation`). |
| 🔎 **Semantic search** | Local chunking + `gemini-embedding-001` (768-dim) in pgvector for nearest-neighbour retrieval. |
| 💬 **Ask the brain** | Natural-language Q&A grounded in a deal-facts table + top-k semantic chunks (`workers/ask.py`). |
| 🕸 **Knowledge graph** | Deterministic resolver links people ↔ companies ↔ deals into a browsable graph. |
| 🔗 **LinkedIn enrichment** | Founders/people enriched via Scrappa + Apify scrapers — **zero LLM tokens**, negative-cached, daily-capped. |
| 📊 **Dashboard** | Next.js app over flattened "gold" views — companies, people, and deals at a glance. |
| 📝 **Obsidian export** | Regenerates a Dexter-conventions Obsidian vault (References / Email / Categories) from the database. |

---

## Architecture

Everything is built on three durable truths: **Supabase** as the single managed
box (Postgres + pgvector + pgmq + Storage), `gb_envelope.status` as the state
machine, and **pgmq queues** as the "there's work for you" signal between
workers.

```
                  ┌──────────── Supabase (Postgres · pgvector · pgmq · Storage) ────────────┐
  Gmail mailboxes  │   gb_raw ──trigger──▶ gb_q_normalize                                    │
        │          │                                                                         │
        ▼          │   ┌───────────┐  ┌────────────┐  ┌─────────┐  ┌───────┐  ┌─────────┐    │
  connectors/  ────┼──▶│ normalize │─▶│ preprocess │─▶│ extract │─▶│ embed │─▶│ resolve │─▶ indexed
   gmail.py        │   └───────────┘  └────────────┘  └─────────┘  └───────┘  └─────────┘    │
  (poll + land)    │     classify       PDF → text      Gemini       768-dim     graph       │
   WhatsApp/Whapi  │     + dedup        + chunks         note         vectors     edges       │
        ┄┄┄┄┄┄┄┄┄┄┄│                                        │                                 │
                   └────────────────────────────────────────┼─────────────────────────────────┘
                                                             ▼
                                          dashboard · semantic Q&A · graph viewer · Obsidian
```

**Design rules that hold everywhere:**

- **Connectors are dumb.** They only `INSERT` into `gb_raw`; a DB trigger
  auto-enqueues. No parsing, no LLM, no classification in a connector.
- **Workers own one transition each** and are **idempotent** — a redelivered
  queue message re-checks `status` and is a harmless no-op. Nothing
  double-spends, nothing double-processes.
- **Spend only in `extract`.** Dedup + a cheap signal score gate every token;
  confidential mail (security / finance / HR) is never indexed and its body is
  cleared.
- **Migrations are append-only** — numbered, idempotent, never edited once
  shipped.

The status state machine:

```
raw → normalized → (skipped | preprocessed) → extracted → embedded → resolved → indexed
                                     │
                                     └──────────────── failed (→ gb_dlq)
```

---

## Tech stack

| Layer | Choice |
|---|---|
| **Database / queue / vectors / files** | Supabase — Postgres + pgvector + pgmq + Storage (database only) |
| **Orchestration (edges)** | n8n on the VPS (Docker) — triggers, webhooks, pollers |
| **Processing (loops)** | Python workers on the VPS (systemd) — stateless, idempotent, queue-driven |
| **Analysis / extraction** | Gemini 2.5 Flash (escalates to `gemini-2.5-pro` on low confidence) |
| **Embeddings** | `gemini-embedding-001`, MRL-truncated to 768 dims |
| **Enrichment** | Scrappa (LinkedIn search) + Apify (profile / company scrapers) |
| **Dashboard** | Next.js 14 + TypeScript + Tailwind |
| **Host** | Hostinger KVM 4 VPS, Mumbai |

---

## Repository layout

```
sql/                  Append-only migrations 001–010
  001 foundation · 002 queues · 003 entities · 004 graph · 005 auto_enqueue
  006 gold_views · 007 canon_sector · 008 enrich_queue · 009 person_profile · 010 company_profile
workers/
  lib/                db · queues · signal_score · storage · gemini · note_schema · search · taxonomy …
  connectors/         gmail.py (OAuth, multi-mailbox) · gmail_auth.py
  normalize.py        preprocess · extract · embed · resolve · sweeper       ← the core pipeline
  enrich.py           apify_linkedin · apify_company                          ← enrichment (no LLM)
  ask.py              seed_spine · graph_export · obsidian_export             ← retrieval & exports
dashboard/            Next.js app (companies · people · deals) over the gold views
n8n/                  gmail_receiver.json · whapi_receiver.json
tests/                test_dedup (Gate 0) · test_pipeline (Gate M1) · test_edges
ops/                  deploy.sh · systemd/gbrain-*.service|timer · viewer-public/
viewer/               graph_viewer.html — interactive knowledge-graph viewer
docs/                 PIPELINE.md · RUNBOOK.md · PROGRESS.md   ← start here for depth
```

---

## Quick start

> Production runs on the VPS at `/opt/gbrain` as the unprivileged `gbrain` user.
> The full operator guide is in **[docs/RUNBOOK.md](docs/RUNBOOK.md)**.

**1 · Database** — in the Supabase SQL Editor, run `sql/001`…`sql/010` in order
(each is idempotent). Create the private Storage bucket `gbrain-bronze`.

**2 · Configure** — copy `.env.example` to `.env` and fill in Supabase + Gemini
credentials:

```bash
cp .env.example .env        # DATABASE_URL (direct/session pooler, port 5432 — never 6543)
                            # SUPABASE_URL · SUPABASE_SERVICE_KEY · GEMINI_API_KEY (or Vertex trio)
```

**3 · Install & run the pipeline:**

```bash
pip install -r requirements.txt
python -m workers.normalize     # then: preprocess · extract · embed · resolve
python -m workers.sweeper       # re-enqueues any orphaned rows (schedule every 5 min)
```

On the VPS these run as systemd units — see [Operating](#operating).

**4 · Go live on Gmail:**

```bash
sudo -u gbrain /opt/gbrain/.venv/bin/python -m workers.connectors.gmail_auth   # add a mailbox
systemctl enable --now gbrain-gmail.timer                                      # poll + land
```

**5 · Ask the brain:**

```bash
python -m workers.ask "which fintech companies are raising the most?"
```

**6 · Dashboard:**

```bash
cd dashboard && npm install && npm run dev    # http://127.0.0.1:3001
```

---

## Operating

Always-on systemd services run the pipeline; timers handle polling and
maintenance:

| Unit | Cadence | Role |
|---|---|---|
| `gbrain-normalize` → `…-resolve` | always-on | the five pipeline stages |
| `gbrain-enrich` / `gbrain-profile` / `gbrain-company` | always-on | LinkedIn enrichment (no LLM) |
| `gbrain-gmail.timer` | every 1 min | poll mailboxes, land new mail |
| `gbrain-sweeper.timer` | every 5 min | re-enqueue orphaned raw rows |
| `gbrain-vault.timer` / `gbrain-graph.timer` | periodic | rebuild Obsidian vault / graph export |
| `gbrain-viewer` / `gbrain-dashboard` | always-on | serve the graph viewer / dashboard |

```bash
systemctl list-units 'gbrain-*'       # health at a glance
journalctl -u gbrain-extract -f       # follow the paid step
```

**Verify the brain works** (SQL):

```sql
select * from gb_pipeline_status;                      -- what's at each stage
select queue_name, queue_length from pgmq.metrics_all();-- queue depths
select * from gb_company_360 where company = 'Acme Robotics';
select * from gb_observation_latest;                   -- current financials per company
select * from gb_dlq order by at desc;                 -- failures
```

Graph viewer: `python -m workers.graph_export viewer/graph.json`, then open
`viewer/graph_viewer.html`.

---

## Testing

The pipeline is tested end-to-end with **no tokens spent** via a fake-LLM mode.
Both tests run against live Supabase using `source like 'test%'` rows and clean
up after themselves.

```bash
GBRAIN_FAKE_LLM=1 python -m tests.test_dedup       # Gate 0 — dedup + idempotency + signal gate
GBRAIN_FAKE_LLM=1 python -m tests.test_pipeline    # Gate M1 — full pipeline (stubbed storage)
```

Drop `GBRAIN_FAKE_LLM=1` with real Gemini credentials to verify Gate M1 for real.

---

## Documentation

| Doc | Read it for |
|---|---|
| **[docs/PIPELINE.md](docs/PIPELINE.md)** | How it works — architecture, the six stages, the classifier, the data model, retrieval. |
| **[docs/RUNBOOK.md](docs/RUNBOOK.md)** | How to run & operate it — services, Gmail, backfills, config, cost, troubleshooting. |
| **[docs/PROGRESS.md](docs/PROGRESS.md)** | What's done vs remaining, with a health-check snippet. |
| **[CLAUDE.md](CLAUDE.md)** | Build context, conventions, and the working agreement for contributors. |

---

<sub>Internal tooling for Dexter Capital / Dexter Ventures. Not for public distribution.</sub>
