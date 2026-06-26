# Tracxn → gbrain extractor (VPS)

Server-side extractor: pulls full company data from Tracxn's internal API and
pushes each company to **gbrain** over REST, with a local JSONL backup. No paid
Tracxn API/credits — it replays the same calls a logged-in browser makes.

```
  company ids ──► TracxnClient ──► normalize ──► FanoutSink ──┬─► JSONL (local backup)
   (names/        (cookie auth,      (flatten)                └─► gbrain REST webhook
    ids/           login fallback,
    discover)      throttle+retry)
```

## 1. Install

```bash
cd vps
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# only if you use the headless-login fallback:
python -m playwright install chromium
```

## 2. Authenticate (cookie-first, login-fallback)

**Recommended — capture a session once in a real browser** (handles MFA), then copy
the file to the VPS:

```bash
python -m tracxn.client login         # opens a browser; log in; writes storage_state.json
scp storage_state.json vps:/opt/tracxn/vps/
```

Alternatively set `TRACXN_COOKIE` to a raw Cookie header. Either way, set
`TRACXN_EMAIL`/`TRACXN_PASSWORD` so the extractor can **auto-refresh** headlessly
when the session expires (set `TRACXN_LOGIN_FALLBACK=0` to disable).

> ⚠ **IP binding.** Tracxn may tie a session to the IP it was created on. If a
> cookie captured on your laptop dies instantly when used from the VPS, that's why
> — route the VPS through a residential proxy (`TRACXN_PROXY`) or run on a normal
> connection. See Safety.

## 3. Configure

```bash
cp .env.example .env      # fill in; keep 0600, never commit
set -a; . ./.env; set +a  # export into the environment
```

Key vars: `TRACXN_STORAGE_STATE` / `TRACXN_COOKIE`, `TRACXN_EMAIL` / `TRACXN_PASSWORD`,
`TRACXN_DELAY_MS`, `TRACXN_PROXY`, `GBRAIN_WEBHOOK_URL`, `GBRAIN_API_KEY`, `GBRAIN_BATCH`,
`GBRAIN_DRY_RUN`. Full list in [.env.example](.env.example).

## 4. Run

```bash
# by name(s) — resolved via autocomplete
python tracxn_pull.py --names "Lenskart" "Paytm" "Zerodha"

# by id(s), or a file of ids (one per line), resumable, with MCA financials
python tracxn_pull.py --ids-file universe.txt --financials --resume

# discover a universe from a saved Tracxn filter, then pull it
python tracxn_pull.py --discover-file filter.json --resume

# ALSO emit every statutory filing (metadata + viewer link) per company
python tracxn_pull.py --ids-file universe.txt --documents --resume
python tracxn_pull.py --names "Lenskart" --documents --docs-since 2018   # limit by filing year
```

### Documents (statutory filings)

`--documents` emits **one record per MCA filing** (all types) alongside each company,
to the same JSONL + gbrain sink:

```json
{ "kind": "document", "company_id": "52bfc960…", "company_name": "Lenskart",
  "id": "68dbe00a…", "name": "Form MGT-7", "document_type": "Annual Returns",
  "filing_date": "2025-09-24", "cin": "U33100DL2008PLC178355",
  "viewer_url": "https://platform.tracxn.com/a/d/document/68dbe00a…/formmgt-7" }
```

- **Credit-free** — these MCA filings download outside Tracxn's credit/export system.
- The link is the **viewer URL** (resolves the PDF through your session). The raw S3
  files are **pre-signed and expiring**, so we store the durable `id` + `viewer_url`
  and re-resolve the PDF on demand rather than caching a link that rots.
- **Volume:** a mature Indian company can have ~1,800 filings. It's only metadata (light),
  but that's ~36 list calls/company — use `--docs-since YEAR` to cap history, and mind the
  per-company time at `TRACXN_DELAY_MS`.
- Filter `kind == "document"` (vs `"company"`) downstream in gbrain.

### Fetching a PDF binary on demand (`tracxn.resolve`)

gbrain stores the lightweight document records; when it actually needs a PDF, it calls
the resolver. Because the real download URL is **pre-signed/expiring and varies by doc
type**, the resolver doesn't guess URLs — it opens Tracxn's own viewer page in your saved
session (Playwright) and intercepts the file response. Universal, and never caches a link
that rots.

```bash
# CLI: resolve one document to a PDF on disk
python -m tracxn.resolve 68dbe00a33632f05f4345ecd --name "Form MGT-7" --out out/docs
```
```python
# from gbrain / code
from tracxn.config import Config
from tracxn.resolve import fetch_pdf, fetch_many

pdf_bytes = fetch_pdf(Config(), document_id)                 # one, returns bytes
results   = fetch_many(Config(), [(id1, name1), id2], "out/docs")  # many, one browser
#           -> [(document_id, saved_path_or_None, error_or_None), ...]
```

Needs Playwright + chromium and a valid `storage_state.json`/`TRACXN_COOKIE`. `fetch_many`
reuses a single browser context for the batch; it honours `TRACXN_PROXY`. Failures are
returned per-item (never abort the batch).

First run tip: set `GBRAIN_DRY_RUN=1` to verify the JSONL output before POSTing to gbrain.

### Getting a company-id universe
- **By name:** `--names` resolves each via `/api/2.2/autocomplete` (company id = `payload.domainProfileId`).
- **By filter:** open a list/sector in Tracxn, copy the `POST /api/4.0/companies` `filter`
  object from DevTools → Network into `filter.json`, then `--discover-file filter.json`.
- **By URL:** the 24-char hex in `…/a/d/company/<ID>/<domain>` is the id.

## 5. gbrain payload

Per company (`GBRAIN_BATCH=1`):
```json
{ "source": "tracxn", "company": { "id": "...", "name": "...", "revenue_inr_cr": 7009.28, ... } }
```
Batched (`GBRAIN_BATCH>1`): `{ "source": "tracxn", "companies": [ {...}, ... ] }`.
Auth header is configurable (`GBRAIN_AUTH_HEADER`/`GBRAIN_AUTH_SCHEME` + `GBRAIN_API_KEY`).
Change the wire schema in `tracxn/sinks.py::GbrainSink._envelope` if gbrain expects
something different. Failed POSTs are retried; rows are always in the JSONL backup.

## 6. Schedule (systemd)

```bash
sudo cp systemd/tracxn.service systemd/tracxn.timer /etc/systemd/system/
sudo cp .env /etc/tracxn.env && sudo chmod 600 /etc/tracxn.env
sudo systemctl enable --now tracxn.timer
systemctl list-timers tracxn.timer        # check next run
journalctl -u tracxn.service -f           # watch logs
```
The timer runs daily at 09:17 + up to 20 min jitter. `--resume` skips already-done ids,
so re-runs are cheap and a crash resumes where it stopped. (Cron equivalent:
`17 9 * * * cd /opt/tracxn/vps && .venv/bin/python tracxn_pull.py --ids-file universe.txt --resume`.)

## 7. Safety (read this)

- Running from a **VPS datacenter IP is the highest-risk** way to do this — automated
  login + bulk calls is a classic bot signature and can get the account flagged.
- Keep `TRACXN_DELAY_MS` ≥ 1500, use the **residential proxy** hook, run during normal
  hours, and don't parallelise. The client backs off on HTTP 429/503 automatically.
- This replays your own licensed session for internal research; it is still against
  Tracxn's ToS. Keep volume reasonable. The clean long-term path remains Tracxn's paid
  SFTP dump / official API (see the project root README).

## 8. Tests

```bash
python tests/test_normalize.py     # normalizer reproduces live numbers (25 assertions)
python tests/smoke_offline.py      # normalize -> sinks pipeline, no network
```

## Field dictionary

`id, name, website, founded, stage, city, country, sector, short_description,
revenue_inr_cr, revenue_usd_m, revenue_as_on, revenue_growth_1y/3y,
ebitda_inr_cr, ebitda_as_on, net_profit_inr_cr, net_profit_as_on,
valuation_inr_cr, valuation_usd_m, valuation_as_on, employee_count,
total_equity_funding_usd_m, tracxn_score, investors, key_people,
legal_entity_ids, tracxn_url` — money normalised to ₹-crore / US$-million with `as_on`
fiscal dates. With `--financials`, a `_statutory` object (raw MCA filings) is attached.
