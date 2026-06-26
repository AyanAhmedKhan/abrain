# Briefing for Claude Code on the VPS — Tracxn → gbrain extractor

You are operating on a Linux VPS. Your job is to **deploy and run an existing
Python extractor** (already in this directory) that pulls company data from
Tracxn and pushes it to "gbrain". **Do not rewrite it** — install it, wire up the
secrets the human gives you, verify it with a dry run, then run it cautiously.

## Context — what this is

- The human is at an investment-advisory firm with a paid **Tracxn** subscription
  (platform.tracxn.com). Tracxn's official API is a paid add-on they don't have, so
  this tool instead **replays Tracxn's internal JSON API using the human's own
  logged-in session**. It's for internal research on their own licensed account.
- **gbrain** is the human's downstream system. It receives each company as JSON over
  a **REST webhook** (`GBRAIN_WEBHOOK_URL`). A local JSONL file is always written as
  backup, regardless of gbrain.
- This was built and validated against live data (Lenskart, Paytm, Stripe, Zerodha).
  The normalizer is unit-tested; the network + login paths can only be exercised here
  with the human's real session.

## The codebase (already present — read before acting)

```
tracxn_pull.py        # CLI entry point
tracxn/config.py      # all config from env vars (no secrets in code)
tracxn/client.py      # auth (cookie + Playwright login fallback) + API calls
tracxn/normalize.py   # flattens a profile into one row (validated)
tracxn/sinks.py       # GbrainSink (REST webhook) + JsonlSink + FanoutSink
tests/test_normalize.py   # 25 assertions, must stay green
tests/smoke_offline.py    # pipeline test, no network
.env.example          # the full list of settings
README.md             # full runbook — follow it
systemd/              # timer + service for scheduling
```

## Validated facts (rely on these; don't re-discover)

- Auth is the **ambient session cookie** — `POST /api/4.0/companies` with the right
  cookies returns 200; **no CSRF/token header needed**. (Same call a page view makes →
  credit-neutral. Never call any "download profile" endpoint — that one costs a credit.)
- Endpoints used:
  - `POST /api/4.0/companies` body `{"view":"profile","filter":{"id":[ID]},"from":0,"size":1}`
    → `{"result":[{…profile…}],"total_count":N}`. Profile already contains headline
    financials (`latestRevenue/EBITDA/NetProfit/Valuation` with multi-currency, `asOnDate`,
    growth CAGRs), `investors`, `keyPeople`, `legalEntities`.
  - `POST /api/2.2/autocomplete` body `{"term":"<name>","query":{"name":"company","size":10}}`
    → list of `{payload:{…}}`; the company id is **`payload.domainProfileId`** (NOT `payload.id`).
  - Detailed MCA financials (optional, `--financials`): `/api/4.0/statutoryfilings/aggregation`
    (by `legalEntityId` → filing ids) then `/api/4.0/statutoryfilings/india` (by filing ids).
- Money is normalized to `*_inr_cr` (INR ÷ 1e7) and `*_usd_m` (USD ÷ 1e6) with `as_on` dates.
- Output row schema: `id, name, website, founded, stage, city, country, sector,
  short_description, revenue_inr_cr, revenue_usd_m, revenue_as_on, revenue_growth_1y/3y,
  ebitda_inr_cr, net_profit_inr_cr, valuation_inr_cr, valuation_usd_m, employee_count,
  total_equity_funding_usd_m, tracxn_score, investors, key_people, legal_entity_ids, tracxn_url`.

## Secrets the human must give you (ask — never invent, never commit)

Set these in `.env` (copied to `/etc/tracxn.env`, mode 0600). If any are missing, **stop
and ask the human**; do not guess values or fabricate a cookie/token.

- `TRACXN_STORAGE_STATE` (a `storage_state.json` the human captured in their browser) **or**
  `TRACXN_COOKIE` (raw Cookie header). One of these is required.
- `TRACXN_EMAIL` / `TRACXN_PASSWORD` — only for the headless login-refresh fallback.
- `GBRAIN_WEBHOOK_URL` (+ `GBRAIN_API_KEY`, `GBRAIN_AUTH_HEADER`, `GBRAIN_AUTH_SCHEME`, `GBRAIN_BATCH`).
- `TRACXN_PROXY` — strongly recommended (see safety).
- A **company universe**: a `universe.txt` of ids, or names to resolve, or a `filter.json`.

## Your task (do these in order, with checkpoints)

1. **Read** `README.md` and skim the four `tracxn/*.py` files so you know what exists.
2. **Install**: create a venv, `pip install -r requirements.txt`. Install Playwright
   chromium only if the login fallback will be used (`python -m playwright install chromium`).
3. **Run the offline tests** — both must pass before you touch the network:
   `python tests/test_normalize.py` and `python tests/smoke_offline.py`.
4. **Get secrets from the human**, write `.env`, export it. Confirm `storage_state.json`
   (or `TRACXN_COOKIE`) is present.
5. **Connectivity check**: `python -m tracxn.client` should print resolved ids for "Lenskart".
   - If it returns an auth error / empty: the session is invalid or **IP-bound** (see below).
     Stop and tell the human; do not brute-force logins.
6. **Dry run** the sink: `GBRAIN_DRY_RUN=1 python tracxn_pull.py --names "Lenskart" "Paytm"`.
   Inspect the JSONL output. Confirm the gbrain envelope shape matches what gbrain expects;
   if not, edit `tracxn/sinks.py::GbrainSink._envelope` to match and note the change.
7. **Small real batch** (10–20 companies) with gbrain live. Verify gbrain received them
   (ask the human, or check gbrain's logs). Only then scale up.
8. **Scale + schedule**: run the full universe with `--resume`; install the systemd timer
   per the README if the human wants recurring runs.

After each network-touching step, **report what happened** (counts, failures, sample row)
before proceeding.

## Hard constraints / safety (do not violate)

- This replays the human's own session for internal research, but it **is against Tracxn's
  ToS** and a **VPS datacenter IP is high-risk for account flagging**. Your posture is
  *cautious operation, not maximum throughput*.
- Keep `TRACXN_DELAY_MS ≥ 1500`. **Never parallelize** Tracxn requests. The client backs
  off on 429/503 — respect it; if you see repeated 429s, **stop and ask**, don't hammer.
- **Do not bypass or solve CAPTCHAs, MFA, or any bot-detection.** If headless login is
  blocked, stop and ask the human to capture `storage_state.json` manually in a real browser.
- **Never print, log, or commit** secrets (cookie, password, API keys). Keep `.env` out of git.
- Do not call any Tracxn "download/export" endpoint (those cost credits). Stick to the
  validated read endpoints above.
- Don't change the normalizer's output schema without telling the human — gbrain depends on it.

## Known failure modes & fixes

- **Session dies immediately from the VPS** → Tracxn likely binds the session to the
  capture IP. Fix: set `TRACXN_PROXY` to a residential proxy, or have the human re-capture
  the session from a context closer to the VPS. Tell the human; don't loop retrying.
- **Login selectors don't match / MFA prompt** → don't fight it; the human runs
  `python -m tracxn.client login` locally (headful) and copies `storage_state.json` over.
- **gbrain rejects the payload** → adjust `GbrainSink._envelope` and the auth header vars to
  match gbrain's contract; rows are safe in the JSONL backup meanwhile.
- **Some companies have empty financials** → expected (private/foreign/no filing). The
  normalizer leaves those fields blank by design; not an error.

## Definition of done

Offline tests green; a dry run produces correct JSONL; a small live batch is confirmed
received by gbrain; the full universe runs to completion with `--resume`; (optionally) the
systemd timer is enabled. You've reported final counts (ok/failed) and the JSONL path.
