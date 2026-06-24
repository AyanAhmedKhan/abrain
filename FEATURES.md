# gbrain — Feature Backlog & Roadmap

A living menu of what we *could* build next, prioritized by leverage. Each item
notes **what / why / effort (S·M·L) / extra cost / what it reuses**. Nothing here
is committed — it's a decision menu.

> Effort: **S** ≈ hours · **M** ≈ a day · **L** ≈ multi-day.
> Cost = incremental ₹ at $1≈₹85 (Gemini/Apify/Scrappa); "free" = deterministic, no API.

---

## ✅ Already built (for context)
- **Ingestion**: Gmail → gate (dedup + signal) → Gemini extract → embed (pgvector) → resolve → graph. Name-quality gate; founders **and** `key_people` separated.
- **Entities**: `company`, `person`, `deal`, `investor`, `org` (past employers), `school`. **Edges**: `works_at` (current/past via props), `invests_in`, `studied_at`, `mentions`, `about`, `sent_by`, `involves`.
- **Enrichment** (decoupled, negative-cached): Scrappa → LinkedIn URL; Apify → rich person + company profiles; free company-URL/logo harvest from person scrapes; current/past team, colleagues, alumni, grads.
- **Identity**: verified dedup (company/person/investor/org/school) + dedup-on-write by LinkedIn slug; transaction-safe merges.
- **Dashboard** (Next.js, Tailscale-private): Companies, Company detail (LinkedIn block, **financial trends**, current/past team, **warm-intro paths**: referrer + shared-employer + classmate + investors), People + Person detail (full profile, current/former colleagues), Deals, **Pipeline Kanban** (drag + owner), **Inbox** (follow-ups + signals), **Investors** + detail, **Ask-the-brain RAG**.
- **Obsidian vault**: References (companies/people) + **Organizations** + **Schools** folders, interconnected **Bases** (People/Companies/Team/PastEmployees/Grads/Organizations/Schools, with "Hubs 2+" filters), Categories MOCs, Email notes; LinkedIn URL **+ id** + logo on every node; capped/cached **AI org summaries**.
- **Ops**: systemd workers + queues + DLQ; weekly **digest** generator; image proxy; graph viewer.

---

## ⚡ Tier 0 — the biggest lever (do this first)
- **Upgrade the harvestapi (Apify) plan.** Free tier caps at **10 runs** — only ~7 of ~108 people are scraped, so alumni/team/grad/warm-intro graphs are sparse. Backfill of everyone ≈ **₹40 one-time**; then every feature below operates on a dense graph. *(Config + restart; the workers auto-resume.)*

---

## Tier 1 — Deal intelligence (highest IB value, reuses existing data)
- **Auto IC memo / one-pager** ⭐ — one click on a company → Gemini composes a structured investment memo (thesis · traction · financial trend · team · cap table · existing investors · risks · comparables · ask). **M**, ~₹3–5/memo (capped+cached), reuses extraction + observations + graph + `gemini.generate_text`.
- **Comparables / "similar companies"** — pgvector similarity over company text → "deals like X"; + sector-peer **valuation/revenue multiple** benchmarking. **M**, free (embeddings exist) + cheap.
- **Deal scoring** — deterministic score from signals (revenue growth, fit, POC, sector momentum) surfaced on cards/pipeline. **S–M**, free.

## Tier 2 — Smarter search & analytics
- **RAG upgrades** — conversational follow-ups (chat memory), clickable `[n]` citations that open the source note, and a **scheduled weekly market brief** folded into the digest. **M**, ~₹0.3/query.
- **Sector / market landscape** page — deal volume, avg ask/valuation, multiples, most-active investors per sector. **M**, free.
- **Talent / expert finder** — query the people+org+school graph: *"who do we know in fintech / ex-Flipkart / IIT grads"* (sourcing + reference checks). **M**, free (graph exists).
- **Saved searches / smart lists** — pin filtered views (e.g. "Seed fintech, POC high, quiet 30d+"). **S**, free.

## Tier 3 — More coverage (more deal flow in)
- **WhatsApp ingestion** — `whapi_receiver` connector already in repo (M2); route into the same pipeline. **M**, free pipeline (LLM per message gated).
- **Calendar / meetings** (M3) — meeting notes + attendees → graph. **M**.
- **News / funding tracker** — watchlist alerts when a tracked company raises or hits the news. **M**, small API.
- **PDF/deck re-link on company page** — surface the source deck from bronze storage (provenance). **S**, free.

## Tier 4 — Relationship & network intelligence
- **Network graph refresh** — show the new investor/org/school layers in the graph viewer; filter by edge type. **S–M**, free.
- **Strongest-path intros** — rank warm-intro routes by tie strength (recency, shared count, Dexter-proximity). **M**, free.
- **Co-investment network** — investor↔investor graph + "who's active with whom in sector X". **S–M**, free (views exist).
- **Cap table / ownership** tracking per company (rounds, stakes). **M**.

## Tier 5 — Proactivity & delivery
- **Real notifications** — wire the weekly digest to actually send (SMTP), + Slack/WhatsApp alerts for new deals & overdue follow-ups. **S**, free.
- **Per-owner daily digest** — each Dexter member gets their deals/follow-ups. **S**, free.
- **Nudges** — auto "going quiet" reminders into the Inbox/owner. **S**, free.

## Tier 6 — Data quality, ops & governance
- **Data-quality dashboard** — DLQ, unresolved entities, dedup candidates for review, missing-data gaps. **M**, free.
- **Scheduled self-healing** — periodic dedup / enrich / summarize / vault-regen timers. **S**, free.
- **Backups** — pg dump + bronze snapshot on a timer. **S**.
- **Governance (M5)** — access roles, audit log, PII handling/retention; tighten confidential-mail handling. **M–L**.

## Tier 7 — UX polish
- **Global command palette (⌘K)** — jump to any company/person/deal/investor. **S**.
- **CSV / memo export** anywhere; print-friendly company one-pager. **S**.
- **Mobile-friendly** dashboard pass. **S–M**.

---

## Suggested sequence
1. **Tier 0** (upgrade scraper plan) — unlocks density for everything.
2. **Auto IC memo** + **Comparables** (Tier 1) — turns the brain into one-click analyst output.
3. **RAG upgrades** + **Sector landscape** + **Talent finder** (Tier 2).
4. **WhatsApp/Calendar** (Tier 3) for breadth, then **notifications** (Tier 5).
5. **Data-quality + scheduled self-healing** (Tier 6) as the graph grows.

*Owner: tech@discoverventures.in · costs in ₹ at $1≈₹85 · update as items ship.*
