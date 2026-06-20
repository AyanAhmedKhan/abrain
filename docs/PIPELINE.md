# gbrain — Pipeline & Architecture

How a single email becomes a structured note, financial data, embeddings, and
graph edges — stage by stage, with the design rules behind each.

---

## 1. Big picture

```
                         ┌──────────────── Supabase (Postgres + pgvector + pgmq + Storage) ───────────────┐
                         │                                                                                │
  Gmail mailbox(es)      │   gb_raw ──trigger──▶ gb_q_normalize                                           │
        │                │                                                                                │
        ▼                │   ┌──────────┐   ┌───────────┐   ┌─────────┐   ┌───────┐   ┌─────────┐         │
  connectors/gmail.py ───┼──▶│ normalize │─▶│ preprocess │─▶│ extract │─▶│ embed │─▶│ resolve │──▶ indexed │
   (poll + land)         │   └──────────┘   └───────────┘   └─────────┘   └───────┘   └─────────┘         │
                         │      classify        PDF→text       Gemini       vectors      graph            │
                         │      + dedup         + chunks        note        (768d)       edges            │
                         └────────────────────────────────────────────────────────────────────────────────┘
                                                                  │
                                                                  ▼
                                              viewer (graph) · SQL · semantic search
```

Two durable truths back the whole thing:
- **`gb_envelope.status`** — where each item is in the pipeline.
- **pgmq queues** (`gb_q_*`) — "there is work for you" signals between workers.

Each worker owns exactly one status transition and is **idempotent**: it
re-checks status before acting, so a redelivered queue message is a harmless
no-op. Nothing double-spends, nothing double-processes.

---

## 2. The status state machine

```
raw → normalized → (skipped | preprocessed) → extracted → embedded → resolved → indexed
                                     │
                                     └────────────── failed (→ gb_dlq)
```

| Queue | Producer → Consumer |
|---|---|
| `gb_q_normalize` | connector/trigger → **normalize** |
| `gb_q_preprocess` | normalize → **preprocess** |
| `gb_q_extract` | preprocess → **extract** |
| `gb_q_embed` | extract → **embed** |
| `gb_q_resolve` | embed → **resolve** |
| `gb_q_index` | (terminal marker) |
| `gb_q_backfill` | reserved for bulk re-processing |

---

## 3. Stage by stage

### Stage 0 — Connector (`workers/connectors/gmail.py`)
"Dumb" by design: **no parsing, no LLM, no classification.** It only:
1. Polls each mailbox (`/opt/gbrain/tokens/<email>.json`) using a Gmail
   `after:` cursor stored per-mailbox in `gb_sync_cursor` (`gmail:<email>`).
2. For each new message: uploads every **PDF attachment** to the private
   `gbrain-bronze` bucket (keyed by SHA-256), then INSERTs rows into `gb_raw`:
   - one `source='gmail'` row (the full message + decoded plain-text body), and
   - one `source='pdf'` row per attachment (carrying `hash`, `storage_ref`,
     `mime`).
3. A message is only marked "done" (its `gmail` row landed) **after** its PDFs
   are safely in bronze — so a storage hiccup re-polls the whole message instead
   of orphaning a deck.

A DB trigger (`gb_raw_auto_enqueue`) fires on every INSERT into `gb_raw` and
sends a message to `gb_q_normalize`. Connectors therefore never call the queue
directly — any insert path feeds the pipeline.

**Dedup at the door:** `gb_raw` has `unique(source, source_id)` (gmail→message
id, pdf→file hash), so re-seen items are no-ops.

### Stage 1+2 — Normalize (`workers/normalize.py`)
Maps the raw payload to one **canonical envelope** (`gb_envelope`): sender,
subject, occurred-at, thread, body (quotes/signatures stripped), labels, a
content hash, and an `idempotency_key = sha256(source + id + content_hash)`
that **kills cross-channel duplicates** (same deck via two channels = one
envelope).

Then it **gates**:
- **Gmail** → the rule-based classifier (`workers/lib/gmail_filter.py`) decides
  index vs skip (see §4). Indexed mail is queued to preprocess; skipped mail
  stops here (status `skipped`), and **confidential mail also has its body
  cleared** so it's never searchable.
- **Other sources** → a cheap signal score (`workers/lib/signal_score.py`); if
  below `SIGNAL_THRESHOLD` (0.35) it's skipped, so junk never costs a token.

### Stage 3 — Preprocess (`workers/preprocess.py`) — local, free
- **Attachment path** (`pdf` rows): download from bronze, extract the text
  layer with PyMuPDF, write a `gb_attachment` row (deduped on file hash — the
  **same deck arriving twice is extracted once**), and split into **page-aware
  chunks**. A scanned/image PDF with no text layer is dead-lettered with a clear
  reason (OCR/multimodal is a planned add).
- **Text path** (emails/messages): chunk the cleaned body.

Output: `gb_chunk` rows (page-tagged, citeable), status `preprocessed`.

### Stage 4 — Extract (`workers/extract.py`) — the only paid step
Sends the chunked text to **Gemini 2.5 Flash** with the prompt in
`workers/lib/note_schema.py`, getting back a strict JSON note (company, sector,
stage, ask/valuation/revenue, founders, key metrics, risks, action items,
confidence, summary). On **low confidence it auto-escalates to
`gemini-2.5-pro`** and retries.

The note is stored verbatim in `gb_envelope.extraction`, and **fans out** into
the typed knowledge layer:
- `gb_entity` — companies, people, deals (upserted, conflict-safe).
- `gb_observation` — the financial time-series (funding_ask, revenue,
  valuation… with unit + period).
- `gb_task` — action items.
- `gb_cost_log` — tokens + USD per call (cost accounting).

If a deck's hash already has a note (cross-channel dedup), preprocess links it
and extraction is **skipped entirely ($0)**.

### Stage 5 — Embed (`workers/embed.py`)
Embeds each chunk with `gemini-embedding-001`, MRL-truncated to **768 dims**,
into `gb_chunk.embedding` (`vector(768)`, HNSW-indexed). This powers semantic
search. Status → `embedded`, then queued to resolve.

### Stage 6 — Resolve (`workers/resolve.py`)
Deterministic identity resolution: links people ↔ companies ↔ deals ↔ the
source document into **graph edges** (`gb_edge`: `mentions`, `sent_by`,
`about`, `works_at`, `involves`) with provenance (which envelope, when). Status
→ `resolved` → `indexed`. The item is now fully in the brain.

### Backstop — Sweeper (`workers/sweeper.py`)
Every 5 minutes, re-enqueues any `gb_raw` row that somehow never produced an
envelope (lost handoff). Belt-and-suspenders.

---

## 4. The Gmail classifier (cost & privacy gate)

`workers/lib/gmail_filter.py`, first match wins:

1. **Trusted label** (`GMAIL_DEAL_LABEL_IDS`) → **index** as `call-notes`.
2. **Automated / bulk** (List-Unsubscribe, no-reply, Gmail Promotions/Social) →
   **skip**.
3. **Confidential / personal** (OTP/2FA, payslips/bank/UPI, HR letters — matched
   on subject) → **skip, body cleared, never indexed**. ("Confidential" alone is
   *not* a trigger — decks are routinely marked confidential.)
4. **Deal signals** (subject says "call notes/pitch/deck/raising/term sheet…",
   deal vocabulary, known sender, or a spine company mention) → **index** as
   `call-notes` / `deal-flow`.
5. **Default** → skip (under-indexing beats indexing noise).

Tune the regex/lists in that file; restart `gbrain-normalize`.

---

## 5. The data model (key tables)

| Table | Holds |
|---|---|
| `gb_raw` | immutable raw landings (verbatim payload + storage ref) |
| `gb_envelope` | the canonical item + `extraction` JSON + status |
| `gb_attachment` | deduped files (one row per unique hash) |
| `gb_chunk` | page-aware text chunks + 768-d embedding |
| `gb_entity` | companies / people / deals / documents (graph nodes) |
| `gb_edge` | typed relationships (graph edges) with provenance |
| `gb_observation` | financial time-series per entity |
| `gb_task` | extracted action items |
| `gb_cost_log` | per-call tokens + USD |
| `gb_dlq` | dead-lettered failures |
| `gb_sync_cursor` | per-mailbox poll position |

Useful views: `gb_pipeline_status`, `gb_company_360`, `gb_observation_latest`,
and the function `gb_graph_json()` (feeds the viewer).

---

## 6. How retrieval works ("how it finds")

- **Semantic search:** embed the query with the same model → cosine search over
  `gb_chunk.embedding` (`<=>` operator, HNSW index) → rank chunks → join back to
  the company/note. Finds by meaning, not keywords.
- **Structured lookup:** query `gb_observation` / `gb_company_360` for hard
  numbers (asks, valuations, revenue).
- **Graph traversal:** `gb_neighbors` / `gb_subgraph` walk the relationships
  (who works where, which people/deals connect to a company).

---

## 7. Design rules (why it's built this way)

- **Spend only in `extract`.** Everything upstream is free; the gate/classifier
  drops junk and confidential mail before any token.
- **Idempotent workers.** Re-checks status; redelivered messages are no-ops.
- **Dedup twice.** Raw `unique(source, source_id)` at the door; attachment hash
  + envelope `idempotency_key` for cross-channel duplicates.
- **Dumb connectors.** Just land rows; the trigger + workers do the thinking.
- **One prompt file.** `note_schema.py` is the only place to change extraction.
- **Append-only migrations**; never edit a shipped one.
- **Models:** `gemini-2.5-flash` workhorse → `gemini-2.5-pro` on low confidence;
  `gemini-embedding-001` @ 768 dims. (Gemini 2.0 is shut down — never use.)

See `docs/RUNBOOK.md` for how to run/operate, and `docs/PROGRESS.md` for status.
