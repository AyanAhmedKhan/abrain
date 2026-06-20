# gbrain — Progress

Status of the build. Last updated **2026-06-15**.

Legend: ✅ done & verified · 🟡 partial / in progress · ⬜ not started

---

## Milestone 0 — Foundation ✅
- ✅ Supabase project `gilnemnskdbyecilsvux`: Postgres + pgvector + pgmq + Storage.
- ✅ Migrations **001–005** applied (foundation, queues, entities, graph, auto-enqueue trigger).
- ✅ Private bronze bucket `gbrain-bronze`.
- ✅ Repo at `/opt/gbrain`, venv, runs as `gbrain` user.
- ✅ `normalize` + `sweeper` workers; **Gate 0 (`test_dedup`) passing**.

## Milestone 1 — Gmail call notes → notes + graph ✅ (live)
**Pipeline**
- ✅ Full worker pipeline deployed & running: `normalize → preprocess → extract → embed → resolve` (systemd, always-on) + `sweeper.timer`.
- ✅ Gemini wired via **Vertex service account** (`vertex-sa.json`, project `sunny-bastion-498008-g1`, `location=global`), `gemini-2.5-flash` → `gemini-2.5-pro` escalation, `gemini-embedding-001` @ 768d. Smoke-tested.
- ✅ Bronze upload/download verified with the `service_role` key.
- ✅ **Gate M1 (`test_pipeline`) passing** — both fake (`GBRAIN_FAKE_LLM=1`) and **real Gemini** (`=0`).
- ✅ Fixed a real bug: UUID JSON-serialization in the Gmail normalize path (would have stuck call notes at `normalized`).
- ✅ Fixed systemd crash-loop guard placement (`StartLimitIntervalSec` → `[Unit]`).

**Gmail connector**
- ✅ Wrote the standalone connector (`workers/connectors/gmail.py`) + auth helper (`gmail_auth.py`) — *these did not exist before; claude.md wrongly listed them as built.*
- ✅ **Multi-mailbox** via OAuth user tokens (`GMAIL_TOKEN_DIR`), per-mailbox cursors.
- ✅ Connected first mailbox `ayan@dextercapital.in` (OAuth, Desktop client, project `n8n-data-ingstion`).
- ✅ `gbrain-gmail.service`/`.timer` authored & installed.

**Verified on real data**
- ✅ Live poll ingested **50 real call-note emails**; classifier correctly indexed them (`Call Notes | <Company>`).
- ✅ ~48 indexed into structured notes (Chara Technologies, Park+, Capital Trust, Lawyered, QpiAI, OUTZIDR, Mount Judi…); auto-escalation to Pro working; cost ~$0.07.
- ✅ Knowledge graph built: ~27 companies, ~27 people, ~21 deals, financial observations, 200+ edges.
- ✅ **Semantic search** verified (e.g. "rare-earth-free EV motors" → Chara).

**Graph viewer**
- ✅ Modern radial viewer (Dexter hub → sector rings → companies → people/deals/docs), filters (entity types / sectors / relationships), Radial⇄Force, detail cards, search.
- ✅ Served as a service (`gbrain-viewer`, `127.0.0.1:8099`); `graph.json` auto-refresh (`gbrain-graph.timer`).

**Docs**
- ✅ `docs/RUNBOOK.md`, `docs/PIPELINE.md`, `docs/PROGRESS.md`.

---

## 🟡 / ⬜ Remaining

### Decisions / actions pending the user
- 🟡 **Turn on continuous ingestion:** `systemctl enable --now gbrain-gmail.timer` (currently off — run it when ready to go live every minute).
- ⬜ **Add more mailboxes** (each: add as Test user → run `gmail_auth`).
- ⬜ **Backfill older history** (widen `GMAIL_INITIAL_DAYS`, reset cursor).
- ⬜ **Seed the 92-deal spine** — `python -m workers.seed_spine <CSV>` (need the CSV).
- ⬜ **Rotate the DB password** (`AyanKhan@2026`) — it's in `.env.example`/screenshots.

### Recently fixed (2026-06-15)
- ✅ **Multimodal PDF extraction** — image-only/scanned decks (no text layer) now go straight to Gemini multimodal instead of dead-lettering. Verified on the real **Zumy deck** (image-only, 14 pages): extracted Zumy · Consumer · Pre-Seed · ask ₹2.5cr · 3 founders, plus a synthetic chunk so it's semantically searchable. (`preprocess.py` routes no-text PDFs to a multimodal-pending state; `extract.py` reads the PDF via `gemini.generate_json_from_pdf`.)
- ✅ **Forwarded-email noise** — `normalize.clean_body` now strips "Forwarded message" separators, mail-client header blocks (From/To/Sent/Subject…), and forwarder promos ("Forwarded using cloudHQ…"). Contentless reply threads now correctly produce no chunks (skipped, $0) instead of polluting embeddings.
- ✅ **`company_name = "?"` / JSON-array extractions** — root cause was Gemini returning a JSON **array** for multi-company forwarded threads, which crashed `fan_out`/`resolve` and left items stuck. Fixed three ways: (1) the prompt now demands a single object and derives the name from the subject ("Call Notes | Acme" → "Acme"); (2) `gemini._coerce` collapses any array to the primary note; (3) `extract`/`resolve` defensively coerce non-dict extractions. Subject is now prepended to the extract input so names resolve on thin threads.
- ✅ **Stuck items cleared** — the 2 (then 6) affected forwarded threads were re-ingested cleanly; **all 51 items indexed** (50 call notes + the Zumy deck), 0 array extractions, 0 failed, DLQ clear.
- ✅ **Test safety** — `tests/test_pipeline.py` cleanup was deleting *all* `source='gmail'` rows (would wipe real data); now scoped to test rows only and FK-safe.

### Obsidian vault + dashboard + DB enrichment (2026-06-20)
- ✅ **Obsidian vault generator** (`workers/obsidian_export.py`) → `/opt/gbrain/vault`, matching Yash's vault conventions: `References/` company+people notes, `Email/` call notes, `Categories/` MOCs, scaffold (all 32 Bases, `.obsidian`, `Schema`, templates) copied verbatim. Auto-refresh `gbrain-vault.timer` (10 min). 106 companies, 176 people, 195 emails, 25 categories.
- ✅ **DB enrichment** — extraction prompt now captures `poc`, `fitment`, `hq`, `website`, `founded`, `aliases`, `existing_investors`, `referred_by` (+ richer founders); stored in `extraction` JSONB and `gb_entity.attrs`. **All 218 call notes re-extracted** (41 now carry POC). Cost to date ~₹88 of ₹25,500.
- ✅ **Dashboard gold views** (`sql/006`, `sql/007`): `gb_company_card`, `gb_deal_card`, `gb_person_card`, `gb_email_log`, `gb_dashboard_stats` — clean columnar `select *` for a web dashboard; sectors canonicalized via `gb_canon_sector` (verified consistent with `taxonomy.canon_sector`, 0 mismatches).
- ✅ **Taxonomy rules** (`workers/lib/taxonomy.py`): canonical sectors/stages, VC/PE/VD/AM/IB/Law-Firm typing, Dexter team roster + email detection, alias generation — applied in both the vault and the DB layer.
- ✅ **Bug-fix pass** (independent review): FK-safe test cleanup, safe numeric rendering, deterministic observation ordering, unquoted ISO dates for Bases, RFC-2822 contact parsing, PDF note labeling, Dexter-team People rows, investor `stage_focus`. Gate 0 + Gate M1 green.

### Edge-case hardening (2026-06-20)
Full reliability pass; `tests/test_edges.py` + Gate 0 + Gate M1 all green.
- **Self-healing pipeline**: `sweeper.py` now re-enqueues envelopes stuck in any
  non-terminal status (the manual-recovery gap) — `STUCK_GRACE_MINUTES` (20).
- **Gemini drift tolerated**: `workers/lib/num.py:safe_num` coerces "40-60"/"$5M"/"~40"
  before numeric inserts (no more DLQ); `gemini._result` salvages/falls back to a
  low-confidence stub on bad JSON; `_coerce` handles arrays.
- **Embedding safety**: `preprocess.chunk_text` hard-splits oversized paragraphs;
  `embed.py` truncates any chunk over the model limit — one big chunk can't strand an item.
- **Cost rail**: `extract.py` daily LLM budget cap (`LLM_DAILY_BUDGET_USD`, default $25 ≈ ₹2,100) + escalation logging; retry backoff in every worker.
- **Connector resilience**: per-mailbox auth isolation (one revoked token can't blind the
  rest) + refresh persisted to disk; per-message try/except with cursor advanced only after
  full land; safe internalDate; backfill-cap warning; advisory lock vs overlapping polls;
  DB reconnect; attachment size cap.
- **Atomic vault**: generated into a temp dir and swapped in — a mid-run crash never leaves
  Syncthing an empty/partial vault; per-row try/except; long-name hash suffix.
- **Dashboard resilience**: `app/error.tsx` + `app/not-found.tsx`; `lib/data.ts` fails soft
  (graceful empty state, not a 500); guarded URL decode + NaN-safe spend formatting.

### Future milestones
- ⬜ **M2 — WhatsApp** (Whapi) into the same pipeline; run alongside the legacy Notes Agent until a 10-deck parity check.
- ⬜ **M3 — Calendar + Drive + internal dashboard** spine.
- ⬜ **M4 — Residual identity resolver** (Gemini) only if deterministic edge coverage < 90%.
- 🟡 **M5 — "Ask the brain"** — v1 shipped (`workers/ask.py`); remaining: UI surface, conversation memory, governance + budget caps.
- ⬜ **Viewer enrichment** — company logos / LinkedIn avatars on graph nodes.

### Ideas / backlog to evaluate
- ⬜ **Headroom (context compression)** — [github.com/chopratejas/headroom](https://github.com/chopratejas/headroom), Apache-2.0, local-first, reversible. Compresses LLM inputs (RAG chunks/history) 60–95%. **Evaluate at M5** for compressing retrieval context in the Q&A layer — only if context size becomes a cost/latency issue there. NOT a fit for the `extract` step today: inputs are already tiny/cheap on Gemini Flash, lossy compression risks dropping exact figures (valuation/revenue/founders), and its proxy/wrap modes assume OpenAI-compatible endpoints while gbrain uses `google-genai`/Vertex (library `compress()` only). The real cost lever — the classifier/gate skipping junk+confidential before any token — is already built.
- ⬜ **Cheaper extract** (if LLM spend ever matters): batch several short call notes per Gemini call; skip re-extraction more aggressively via hash dedup.

---

## Quick health check

```bash
sudo -u gbrain /opt/gbrain/.venv/bin/python - <<'PY'
from workers.lib.db import connect
c=connect()
print("status:", dict(c.execute("select status,count(*) from gb_envelope group by status").fetchall()))
print("entities:", dict(c.execute("select type,count(*) from gb_entity group by type").fetchall()))
print("cost:", [(r['model'],r['n'],r['usd']) for r in c.execute("select model,count(*) n,round(sum(coalesce(usd,0)),4) usd from gb_cost_log group by model").fetchall()])
PY
```

See `docs/RUNBOOK.md` (operate) and `docs/PIPELINE.md` (how it works).
