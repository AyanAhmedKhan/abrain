# gbrain — Implementation Plan & Engineering Best Practices

> [!abstract] What this note is
> The **execution layer** on top of [[gbrain - Cost-Optimized Ingestion Pipeline|the cost/architecture note]] and [[gbrain - Processing Pipeline & Data Ingestion Plan|the build spec]]. Those answer _what to build and why it's cheap_. This answers **_how we actually ship it_** — repo layout, environments, migrations, testing, deployment, ops, security, and a phase-by-phase plan with hard acceptance gates. Where the build spec gives a checklist, this gives the engineering discipline around each box.

> [!tip] The one rule that governs everything
> **The queue is the source of truth for work; `status` is the source of truth for state; the worker is stateless and idempotent.** Every practice below exists to keep those three things true under retries, crashes, redeploys, and backfills.

---

## Contents

- [[#0. Goals, non-goals, success criteria]]
- [[#1. Repository & project structure]]
- [[#2. Environments & configuration]]
- [[#3. Cross-cutting engineering practices]]
- [[#4. Schema & migration governance]]
- [[#5. The n8n / code-worker boundary (resolved)]]
- [[#6. Phase plan with acceptance gates]]
- [[#7. Cost-control implementation]]
- [[#8. Observability, SLOs & alerting]]
- [[#9. Security, privacy & DPDP]]
- [[#10. Deployment & operations]]
- [[#11. Testing strategy]]
- [[#12. Risk register & rollback]]
- [[#13. Sequenced milestones]]
- [[#14. Open decisions]]

---

## 0. Goals, non-goals, success criteria

**Goal.** A unified, queryable company brain for Dexter Capital/Ventures that ingests WhatsApp, Gmail, Calendar, Drive/Docs, PDFs, and internal deal data, at a variable cost in the low tens of dollars/month, with the existing [[Dexter Venture Notes]] extraction absorbed into the new batched pipeline.

**Non-goals (explicitly out of scope for v1).**
- Real-time/streaming answers — minutes of latency on ingestion is fine.
- A managed graph DB ([[Neo4j]]) — Postgres edges until SQL strains.
- Self-hosted embeddings — API/Vertex until ~10–50M tok/mo.
- A custom frontend — retrieval is API/CLI first; UI is a later, separate track.

**Success criteria (measurable).**
1. A pitch deck arriving on WhatsApp produces a structured, citeable note with **zero manual steps** and one LLM extraction regardless of channel.
2. The same deck arriving on **both** WhatsApp and email is extracted **once** (dedup proven).
3. Monthly variable cost stays in the **low tens of dollars** at busy-month volume (the cost note's §12 envelope).
4. A worker crash or a redelivered webhook never causes a double extraction.
5. A misbehaving backfill **cannot** exceed the daily budget cap.

---

## 1. Repository & project structure

One repo, three deployable concerns (SQL, workers, n8n), plus tests and ops. Phase 0 is already scaffolded in this shape.

```
gbrain/
├── sql/
│   ├── migrations/            # numbered, immutable once merged
│   │   ├── 001_foundation.sql
│   │   ├── 002_queues.sql
│   │   └── 0NN_*.sql          # one file per change, never edit a shipped one
│   └── seeds/                 # entity spine load (92-deal dataset) etc.
├── workers/
│   ├── lib/                   # db, queues, signal_score, llm, batch, storage
│   ├── normalize.py           # Stage 1+2
│   ├── preprocess.py          # Stage 3  (Phase 1)
│   ├── extract_submit.py      # Stage 4 submitter  (Phase 1)
│   ├── extract_poll.py        # Stage 4 result poller  (Phase 1)
│   ├── embed_batch.py         # Stage 5  (Phase 1)
│   ├── resolve.py             # Stage 6  (Phase 4)
│   ├── index.py               # Stage 6  (Phase 4)
│   ├── sweeper.py             # orphaned-raw backstop
│   └── connectors/            # gmail.py, calendar.py, drive.py pollers (Phase 2–3)
├── n8n/                       # exported workflow JSON, version-controlled
│   └── whapi_receiver.json
├── tests/
│   ├── test_dedup.py          # Phase 0 acceptance
│   ├── conftest.py            # spins docker pg+pgmq+pgvector
│   └── ...
├── ops/
│   ├── docker-compose.yml     # workers + (optional) local pg for dev
│   ├── systemd/               # unit files for prod workers
│   └── Makefile               # migrate, test, run, fmt, lint
├── .env.example
├── pyproject.toml             # deps, ruff, mypy, pytest config
└── README.md
```

> [!important] Practices this layout enforces
> - **Migrations are append-only.** A merged `00N_*.sql` is never edited; corrections ship as a new file. This is the only way `status`-machine state survives a redeploy.
> - **n8n workflows live in git.** Export after every change. The n8n UI is the editor, the repo is the truth — otherwise the receiver silently drifts.
> - **`workers/lib` is the shared contract.** Queue names, the envelope shape, the DB connection rules live in exactly one place so a connector and the normalize worker can't disagree about the schema.

---

## 2. Environments & configuration

Three environments, one Supabase project per environment (cheapest clean isolation; Supabase branches optional for ephemeral test).

| Env | Supabase | n8n | Workers | Purpose |
|---|---|---|---|---|
| **dev** | local docker pg (pgmq+pgvector) or a free Supabase project | local n8n on M4 | run on M4 | fast iteration, no real data |
| **staging** | dedicated Supabase project | staging n8n instance | on the n8n host | full e2e against a scoped test WhatsApp group |
| **prod** | prod Supabase project | prod n8n | on the n8n host | live |

**Config rules.**
- All config via env vars; nothing hard-coded. `.env` is git-ignored; `.env.example` is the documented contract.
- **One secret store.** Use Doppler (or 1Password/SOPS) for the team; the worker host pulls env at boot. Never paste the DB password into more than one place — n8n credentials and worker env both reference the secret store.
- Workers connect on the **direct/session** Supabase connection (port 5432), **not** transaction-mode pooling — pgmq visibility timeouts and long-lived loops need session semantics.
- The `service_role` key never leaves the server; PostgREST stays locked (RLS enabled, no policies) so the brain tables are unreachable from the anon API.

---

## 3. Cross-cutting engineering practices

These apply to every worker, every phase.

> [!key] Idempotency is the non-negotiable
> Every worker, before doing expensive work, **re-reads `status`** and writes with conflict-safe upserts (`ON CONFLICT DO NOTHING` / status guards). A redelivered pgmq message must be a no-op. This is what makes "replay without re-paying" literally true, and it's tested in Phase 0.

- **Stateless workers.** No in-memory state survives a message. Everything needed is in the envelope row + the queue payload. A worker can be killed at any instant and restarted with no recovery logic beyond pgmq redelivery.
- **Visibility timeout = retry budget.** Set `vt` per stage to comfortably exceed worst-case work time (60s normalize, 600s batch reads). Too short → premature redelivery + duplicate work; too long → slow crash recovery.
- **Bounded retries → DLQ.** After `MAX_READS` (≈5) a poisoned message goes to `gb_dlq` with stage + error and is archived. Nothing loops forever; nothing is silently dropped.
- **Structured logging.** One log line per message: `[stage] <id> → <outcome>`. JSON logs in prod so they're queryable. No print-debugging left in.
- **Type + lint gates.** `ruff` + `mypy` in CI; a worker doesn't merge if it doesn't type-check. The envelope is a typed dataclass, not a loose dict, at the boundaries.
- **Connectors never call the LLM, never block.** Land raw → enqueue → return 200. Any deviation reintroduces the old Notes Agent failure modes.
- **Money-spending code is gated upstream.** No worker downstream of the gate ever re-decides whether to spend — the gate already did. This keeps the cost-control logic in exactly one place (`signal_score` + the dedup constraints).

---

## 4. Schema & migration governance

- **Tooling.** `dbmate` (single binary, plain SQL up-migrations, tracks applied versions in a table). Lighter than sqitch, no ORM. `make migrate` applies pending files to the target env.
- **Forward-only.** No down-migrations relied on in prod; a mistake is corrected by a new forward migration. Down-migrations exist only for local resets.
- **Schema version in the envelope.** `schema_version` lets a future envelope-shape change coexist with old rows during a migration rather than forcing a backfill.
- **The embedding-dimension decision is a hard gate.** `gb_chunk.embedding vector(N)` must match the chosen model **before Phase 1**. Changing it later means drop + recreate the column and HNSW index and re-embed everything. Default `768` (text-embedding-005/Vertex); decide explicitly (see [[#14. Open decisions]]).
- **Every vector carries `embed_model`.** A future model swap is then selective, not wholesale.

---

## 5. The n8n / code-worker boundary (resolved)

Open decision #5 from the cost note is settled: **orchestration in n8n, durable delivery in pgmq, continuous processing in code workers.**

| Runs in **n8n** (event/schedule-shaped) | Runs as **code workers** (loop-shaped) |
|---|---|
| Whapi webhook receiver (insert + enqueue, return 200) | normalize + gate |
| Gmail/Calendar/Drive incremental pollers (cron) | preprocess (OCR / whisper.cpp / chunk) |
| Watch-channel renewals; Whapi health-check | extract batch submitter + result poller |
| Backfill kickoff; sweeper schedule | embed batch |
| Outbound delivery (notes back to WhatsApp/email) | resolve + index |
| DLQ-replay trigger (manual) | the sweeper itself (invoked by n8n schedule) |

Rationale: n8n executions are discrete runs, so a "read the queue forever" loop becomes an awkward per-minute cron with per-tick overhead; and assembling one Batch API request from 50 queue messages with a cached prefix is painful in nodes and trivial in 50 lines of Python. Stateful logic in Code nodes is exactly where the old bugs lived.

> [!warning] The receiver stays dumb
> Three nodes, no intelligence. The moment a Gemini call or a Sheets lookup creeps into the Whapi receiver, the batched/cached architecture is bypassed and we're back to the old pattern. Enforce this in review.

---

## 6. Phase plan with acceptance gates

Each phase is independently shippable and has a **gate**: it isn't "done" until the gate's checks pass. Mirrors the build spec §15 but adds the practices and the explicit pass/fail criteria.

### Phase 0 — Foundation  ·  _(scaffolded)_

**Build:** extensions, all `gb_*` tables + indexes + RLS, all 7 pgmq queues, normalize worker + gate + `signal_score`, sweeper, the dumb Whapi receiver, dedup test.

**Best practices wired in:** idempotent normalize, DLQ path, status check-constraint, observability view, RLS lockdown, sweeper backstop for lost handoffs.

> [!success] Gate 0 (must all pass)
> - `make migrate` applies cleanly to a fresh DB; re-running is a no-op.
> - `tests/test_dedup.py` passes: native-id dedup, idempotency-key dedup, replay no-op, gate skips junk / queues deal content.
> - `select * from gb_pipeline_status` and `pgmq.metrics_all()` return.
> - A message sent to a scoped WhatsApp group lands in `gb_raw` via the imported receiver.

### Phase 1 — PDF + WhatsApp end-to-end, levers ON from day one

**Build:** preprocess (text-layer detect → PyMuPDF/pdfplumber; Tesseract only if scanned; whisper.cpp for voice notes; page-aware chunking); **extract submitter + result poller** (Batch API, cached prefix, `custom_id`↔envelope mapping via `gb_batch_item`); confidence-based Tier-2 escalation; **embed batch**; `gb_cost_log` populated.

**Best practices:** batch + cache + gate are **built in now, not retrofitted** (the #1 way these pipelines go 20× over budget); media downloaded in preprocess by reference (hash-deduped); the existing Notes Agent runs **in parallel** pointing at the same tables until output parity is confirmed.

> [!success] Gate 1
> - Same deck via WhatsApp + email → **one** row in `gb_attachment`, **one** extraction (assert on `gb_cost_log`).
> - Extraction runs through Batch API with a cached prefix — verify `cached_in > 0` in `gb_cost_log`.
> - A scanned PDF triggers OCR; a text PDF does not (assert no Tesseract call).
> - Cost-per-deck logged and within the §12 envelope.
> - Output notes match the legacy Notes Agent on a 10-deck sample.

### Phase 2 — Gmail + Calendar incremental

**Build:** `users.watch()` → Pub/Sub → webhook; **7-day watch-renewal cron** (store `watch_expiry`, renew if < 48h); `historyId` deltas; Calendar `syncToken` + structured-only path (no LLM); label routing (call-notes → auto-extract; newsletters/receipts → skipped).

**Best practices:** deltas-only (never re-scan a mailbox); the renewal cron is mandatory — a silent watch lapse forces an expensive re-backfill; calendar is prioritized because it links people↔companies↔deals at near-zero cost.

> [!success] Gate 2
> - Watch renewal proven: simulate expiry, confirm renewal fires before lapse.
> - A call-notes-labelled email auto-routes to extraction; a newsletter is skipped.
> - Calendar events create entities/edges with **zero** `gb_cost_log` rows.
> - Freshness metric per source is live and non-stale.

### Phase 3 — Drive/Docs + dashboard spine

**Build:** Drive `changes.list` + `pageToken`; Docs export to clean text; **content-hash gate** (permission/rename changes re-index metadata but do **not** re-run the LLM); dashboard CDC via Supabase Realtime/triggers → `kind: record`; load the [[92-Deal Dataset]] as the canonical entity spine.

**Best practices:** ACL capture for retrieval scoping; the dashboard is authoritative for identity resolution — resolve fuzzy mentions against canonical deal records, never ask the LLM to disambiguate what a join can answer.

> [!success] Gate 3
> - A Drive permission-only change re-indexes metadata with **no** new extraction.
> - The 92-deal spine is queryable as `gb_entity` records.
> - A WhatsApp mention of a known deal resolves deterministically against the spine.

### Phase 4 — Identity resolution + graph

**Build:** deterministic joins (phone↔email↔attendee↔author; domain↔company; mention↔deal); residual-only Haiku resolver; Postgres edge tables with `envelope_id` provenance + `occurred_at`.

**Best practices:** deterministic-first ($0 for the majority); Haiku only on the still-ambiguous remainder, never as the default resolver; [[Graphiti]]-on-Postgres deferred until relationship queries strain SQL.

> [!success] Gate 4
> - ≥90% of entity links resolved deterministically (measure the Haiku-call rate).
> - Edges carry provenance + timestamp; a temporal query ("who attended Acme calls in Q2") returns.

### Phase 5 — Retrieval, serving & governance

**Build:** hybrid retrieval (Postgres FTS + pgvector + graph traversal), **permission-filtered before** the LLM sees anything, cached retrieval system prompt, Haiku/Sonnet model split; DPDP/ACL/**delete-propagation**; budget caps + kill switches + dashboards.

**Best practices:** always cite source chunks (source, timestamp, page); cache the retrieval prompt (~90% off the repeated portion); don't send a simple lookup to Opus.

> [!success] Gate 5
> - A restricted-visibility document never surfaces to an unauthorized query.
> - A deletion in a source propagates to chunks/embeddings/edges (DPDP).
> - A runaway backfill hits the daily cap and **pauses itself**.

---

## 7. Cost-control implementation

Where each lever physically lives in the code, so none of them is "a later optimization":

| Lever | Saving | Implemented in |
|---|---|---|
| **Gate** (dedup + signal) | skips most spend entirely | `normalize.py` + the 3 unique constraints |
| **Batch API** | 50% | `extract_submit.py` / `embed_batch.py` accumulator pattern |
| **Prompt caching** | ~90% of repeated input | cached system prefix in the submitter |
| **Local OCR/transcribe** | $0 vs API | `preprocess.py` (PyMuPDF/Tesseract/whisper.cpp) |
| **Model cascade** | avoids defaulting high | confidence check in `extract_poll.py` |
| **Embed once** | no re-embed | `embed_model` per chunk + content-hash gate |
| **Credits routing** | pushes variable → ~0 | provider base URL config (Vertex/Bedrock) |

> [!important] The accumulator is the heart
> `gb_q_extract` and `gb_q_embed` are **not** drained one-at-a-time. The submitter reads up to `MAX_BATCH` (or after `MAX_WAIT` minutes), builds **one** Batch request, stores `batch_id`; a poller writes results back. Get this and the cache breakpoint right and the same workload that would cost $X interactively costs ~5% of $X.

---

## 8. Observability, SLOs & alerting

Instrument from day one — these pay for themselves the first time a backfill misbehaves.

| Metric | Source | Alert when | SLO |
|---|---|---|---|
| Cost per document | `gb_cost_log` | > threshold (Tier-2 loop) | p95 within §12 |
| Per-source spend | `gb_cost_log` × source | spikes vs baseline | flat as volume grows |
| Dedup collision rate | conflict counts | drops to ~0 (dedup not firing) | > 0 when dups exist |
| Skip rate | `skipped` / total | near 0 (gate too loose) | tuned band |
| Batch fill rate | `item_count` / `MAX_BATCH` | consistently tiny | ≥ 70% |
| Freshness per source | `max(occurred_at)` vs now | stale (watch lapse) | < poll interval |
| Stage depth | `pgmq.metrics_all()` | a stage backing up | drains steadily |
| DLQ size | `gb_dlq` count | rising | ~0 |

Wire **hard budget caps with kill switches** to the backfill router and batch submitters. Alerts to a Slack/WhatsApp ops channel. A simple cron exports these to a dashboard (Grafana, or a Supabase view + a small page).

---

## 9. Security, privacy & DPDP

- **Scope WhatsApp to business numbers/groups only** — excludes personal chats; cuts spend, noise, and is the correct DPDP posture.
- **RLS on every `gb_*` table** with no policies → unreachable from the anon/authenticated PostgREST API; workers use the postgres role over the direct connection.
- **ACL capture** (`permissions.acl`) on Drive/Docs for retrieval scoping; **permission-filter before** the LLM in Phase 5.
- **Delete-propagation** (Phase 5): a deletion at source cascades to envelope → chunks → embeddings → edges. Build the cascade as a tested function, not an afterthought.
- **Secrets** in one store; least-privilege DB roles where practical; raw bronze in a cold, access-controlled bucket.
- **Data minimization:** `body_clean` strips signatures/quotes; only what's needed is embedded.

---

## 10. Deployment & operations

- **Where workers run.** Co-located with self-hosted n8n (own-the-infra thesis) via **docker-compose** with `restart: unless-stopped`, or **systemd** units with `Restart=always`. Each stage worker is its own process so one crash is isolated; scale by running N replicas of a stage (pgmq visibility timeout makes this safe).
- **Schedulers.** The batch submitter/poller, watch-renewals, sweeper, and pollers run as cron-style triggers — either n8n Schedule nodes calling `Execute Command`, or host cron. Keep all schedules in `ops/` under version control.
- **Backups/DR.** Supabase PITR on; bronze bucket is the WhatsApp system-of-record (Whapi keeps no history) — verify its backup explicitly. A full replay from bronze must be possible and is part of the DR test.
- **Releases.** `make` targets for `migrate`, `test`, `deploy`. Migrations run before workers restart. n8n workflows re-imported from the repo on change.
- **Runbook.** One page: how to read `gb_pipeline_status`, drain the DLQ, pause a backfill, rotate the Whapi token, renew a lapsed watch.

---

## 11. Testing strategy

- **Unit** — `signal_score`, mappers, `clean_body`, idempotency-key construction. Pure functions, no DB (already passing for Phase 0).
- **Integration** — `conftest.py` spins a docker Postgres with pgmq + pgvector; tests run the real workers against real queues. `test_dedup.py` is the Phase 0 acceptance gate; each phase adds its gate as a test.
- **Contract** — the envelope shape and queue payloads are asserted so a connector can't drift from the normalize worker.
- **Load/backfill** — replay a few thousand historic items through `gb_q_backfill`; assert the rate-limiter holds, the budget cap pauses it, and dedup keeps double-spend at zero.
- **CI** — GitHub Actions: ruff + mypy + pytest against the docker pg on every PR. No merge on red.

---

## 12. Risk register & rollback

| Risk | Likelihood | Mitigation | Rollback |
|---|---|---|---|
| Backfill blows the budget | med | rate-limited queue + hard cap + self-pause | cap halts it; resume next window |
| Silent watch lapse → re-backfill | med | renewal cron + freshness alert | re-establish watch; throttled catch-up |
| Embedding-dim chosen wrong | low | decide before Phase 1; `embed_model` per row | selective re-embed, not wholesale |
| n8n→pgmq handoff lost | low | non-200 retry + sweeper backstop | sweeper re-enqueues orphaned raw |
| Notes Agent vs new pipeline divergence | med | parallel run + 10-deck parity gate | keep Notes Agent live until Gate 1 |
| Poisoned PDF loops Tier-2 | low | per-doc cap + cost-anomaly alert → force-skip + DLQ | DLQ replay after fix |
| pgmq under transaction-pooler | low | enforce direct/session connection | switch connection string |

Every phase ships behind its gate, so rollback is "stop deploying the next phase" — the prior phase keeps running.

---

## 13. Sequenced milestones

| Milestone | Phases | Outcome |
|---|---|---|
| **M1 — Foundation live** | 0 | DB + queues + normalize + receiver; dedup proven |
| **M2 — Brain ingests (the proof)** | 1 | WhatsApp + PDF e2e, batched + cached; Notes Agent parity |
| **M3 — Mailbox + calendar** | 2 | Gmail/Calendar deltas; call-notes auto-extract |
| **M4 — Docs + the spine** | 3 | Drive/Docs; 92-deal spine; deterministic resolution |
| **M5 — The graph** | 4 | Entity/edge graph; temporal queries |
| **M6 — Ask the brain** | 5 | Hybrid retrieval, governed, capped; queryable |

Each milestone is demoable on its own. M2 is the one that proves the whole thesis (cost + automation) and de-risks everything after it.

---

## 14. Open decisions

> [!question] Resolve before the phase that needs them
> 1. **Embedding model + dim** — text-embedding-005/Vertex (`768`, default) vs OpenAI 3-small (`1536`)? _Needed before Phase 1; it's a hard schema gate._
> 2. **Credits routing** — run embeddings/LLM through Vertex/Bedrock/Azure credits while they last? _Phase 1 config._
> 3. **Worker host** — co-locate on the n8n box (recommended) or a separate small VM? _Phase 0/1 deploy._
> 4. **Migration tool** — `dbmate` (recommended) vs ordered files + a tiny custom runner? _Phase 0._
> 5. **Secret store** — Doppler vs SOPS vs host env files? _Phase 0._
> 6. **Dashboard source** (cost note #1) — internal Postgres CDC (preferred) vs external BI API? _Phase 3._
> 7. **Graph timing** (cost note #4) — Postgres edges now, Graphiti when SQL strains? _Phase 4._

---

## Related notes

- [[gbrain - Cost-Optimized Ingestion Pipeline]] — strategy / cost
- [[gbrain - Processing Pipeline & Data Ingestion Plan]] — build spec / wiring
- [[Dexter Venture Notes]] — the workflow this absorbs
- [[92-Deal Dataset]] — the identity spine
- [[Supabase]] · [[Whapi]] · [[pgmq]] · [[n8n Workflows]]
