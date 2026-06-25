# Tracxn Extractor — Runbook

Pulls full company data from Tracxn using **your logged-in browser session** — no
password handling, no cookie export, no download credits. It replays the exact
internal API calls your browser already makes when you view a company page.

## Why this design

| | |
|---|---|
| **Auth** | Ambient session cookie. The secret never leaves your browser. Confirmed live: a `POST /api/4.0/companies` with `credentials:"include"` returns `200`. |
| **Credits** | These are the same calls a normal page view makes → **credit-neutral**. The "1 credit" charge is only on the explicit *Download profile* button, which this never touches. |
| **Robustness** | Runs inside the authenticated tab, so nothing expires mid-run. No Python session to keep alive. |

## How to run

1. Log into <https://platform.tracxn.com> in Chrome.
2. `F12` → **Console**.
3. Paste the entire contents of [`tracxn_console_extractor.js`](tracxn_console_extractor.js), press Enter.
4. Run one of:

```js
// A) Find a company id by name  (uses the autocomplete endpoint)
await TRACXN.fromSearch("Lenskart");     // prints a table of {id,name,stage,country,website}
await TRACXN.idOf("Lenskart");           // -> just the top-match company id

// B) Extract specific companies by id  -> downloads CSV + JSON
await TRACXN.run(["52bfc960e4b0420b03968ee8"]);

// C) Extract many, with detailed MCA financials attached
await TRACXN.run(MY_IDS, { financials: true });

// D) Discover a whole universe, then extract it
const ids = (await TRACXN.discover({ /* paste a filter from a list page */ })).map(x => x.id);
await TRACXN.run(ids);
```

Two files download automatically: `tracxn_<timestamp>.csv` and `.json`.

## Getting the company-id universe

You iterate over **company ids**. Three ways to get them:

1. **By name** — `TRACXN.fromSearch("name")` prints a table of `{id, name, website}`.
2. **From a list/sector page** — open the list in Tracxn, then in DevTools → Network
   find the `POST /api/4.0/companies` request, copy its `filter` object, and pass it to
   `TRACXN.discover(filter)`. It pages through every match.
3. **By URL** — a company page URL is `…/a/d/company/<COMPANY_ID>/<domain>`. The 24-char
   hex is the id.

## Fields produced (per company)

`id, name, website, founded, stage, city, country, sector,
short_description, revenue_inr_cr, revenue_usd_m, revenue_as_on,
revenue_growth_1y/3y, ebitda_inr_cr, net_profit_inr_cr, valuation_inr_cr,
valuation_usd_m, employee_count, total_equity_funding_usd_m, tracxn_score,
investors, key_people, legal_entity_ids, tracxn_url`

Money is normalised: `*_inr_cr` = ₹ crore, `*_usd_m` = US$ million, each with an
`as_on` fiscal date. (Matches the vault rule: store INR-crore standardised.)

## Endpoint reference (captured live)

| Endpoint | Method | Body shape | Returns |
|---|---|---|---|
| `/api/4.0/companies` | POST | `{view:"profile", filter:{id:[…]}, from, size}` | core profile + headline financials |
| `/api/2.2/autocomplete` | POST | `{term:"name", query:{name:"company", size:N}}` | name→id search; company id is `payload.domainProfileId` |
| `/api/4.0/statutoryfilings/aggregation` | POST | `{dataset:"query", filter:{legalEntityId:[…], documentType:[…]}, aggMap:[…]}` | filing doc ids |
| `/api/4.0/statutoryfilings/india` | POST | `{dataset:"query", filter:{id:[filingIds]}}` | year-by-year MCA P&L / balance sheet |

Response envelope: `{ result: [ … ], total_count: N }`.

## Safety

- Keep `DELAY_MS` (default 1500ms) polite; run serial during normal hours.
- Bulk automated calls can still trip Tracxn rate limits / account flags **regardless of
  credits**, and automated extraction is against Tracxn's ToS. This is an internal-research
  tool on your own licensed account — keep volume reasonable.
- The script backs off automatically on HTTP 429/503.

## Note on the discovery session

While capturing the endpoints, a small `fetch`/`XHR` logger and a `window.__cap`
array were injected into the Lenskart tab. They are harmless and vanish on page
refresh — just reload the tab to clear them.
