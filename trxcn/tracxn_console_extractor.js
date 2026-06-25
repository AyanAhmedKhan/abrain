/* ============================================================================
 * Tracxn Console Extractor  (in-browser, uses your logged-in session)
 * ----------------------------------------------------------------------------
 * HOW TO RUN
 *   1. Log into https://platform.tracxn.com in Chrome.
 *   2. Open DevTools (F12) -> Console tab.
 *   3. Paste this whole file, press Enter (defines TRACXN.* helpers).
 *   4. Run one of:
 *        await TRACXN.run(["52bfc960e4b0420b03968ee8"])      // by company id(s)
 *        await TRACXN.fromSearch("Lenskart")                  // find an id by name
 *        await TRACXN.runList(MY_IDS, {financials:true})      // many ids + detailed financials
 *
 * WHY IN-BROWSER (not Python): Tracxn auth is an ambient session cookie. Running
 * here means the secret never leaves the browser and never expires mid-run. The
 * calls below are the SAME requests the page makes when you browse a company, so
 * they are credit-neutral (viewing a profile does not spend a download credit).
 *
 * SAFETY: keep DELAY_MS polite and run during normal hours. Bulk automated calls
 * can still trip Tracxn's rate limits / account flags regardless of credits.
 * ============================================================================ */
(function () {
  const BASE = "https://platform.tracxn.com";
  const DELAY_MS = 1500;            // pause between companies (be polite)
  const RETRY = 2;                  // retries on transient failure
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // --- low-level POST against the internal API, on the current session -------
  async function api(path, body) {
    let lastErr;
    for (let attempt = 0; attempt <= RETRY; attempt++) {
      try {
        const res = await fetch(BASE + path, {
          method: "POST",
          headers: { "content-type": "application/json" },
          credentials: "include",
          body: JSON.stringify(body),
        });
        if (res.status === 429 || res.status === 503) {
          // rate limited -> back off and retry
          await sleep(DELAY_MS * (attempt + 2));
          continue;
        }
        if (!res.ok) throw new Error("HTTP " + res.status + " on " + path);
        return await res.json();
      } catch (e) {
        lastErr = e;
        await sleep(DELAY_MS * (attempt + 1));
      }
    }
    throw lastErr;
  }

  // --- helpers to flatten Tracxn's nested money / location / taxonomy --------
  const fy = (d) => (d && d.year ? `${d.year}-${String(d.month).padStart(2, "0")}-${String(d.day).padStart(2, "0")}` : "");
  function money(m) {
    if (!m || !m.amount) return {};
    const inr = m.amount.INR && m.amount.INR.value;
    const usd = m.amount.USD && m.amount.USD.value;
    const g = m.growthDetails || {};
    return {
      inr_cr: inr != null ? +(inr / 1e7).toFixed(2) : "",      // INR -> crore
      usd_m: usd != null ? +(usd / 1e6).toFixed(2) : "",        // USD -> million
      as_on: fy(m.asOnDate),
      growth_1y: g.oneYear && g.oneYear.CAGR,
      growth_3y: g.threeYear && g.threeYear.CAGR,
      growth_5y: g.fiveYear && g.fiveYear.CAGR,
    };
  }
  function sectorPath(tax) {
    try {
      const path = tax[0]; // primaryTaxonomy is an array of path-arrays
      return path.map((n) => n.name).join(" > ");
    } catch (e) { return ""; }
  }
  function loc(locations) {
    const l = (locations && locations[0]) || {};
    return {
      city: l.city && l.city.name,
      state: l.state && l.state.name,
      country: l.country && l.country.name,
    };
  }
  const names = (arr, fn, n = 5) => {
    if (!Array.isArray(arr)) return "";
    return arr.slice(0, n).map(fn).filter(Boolean).join("; ");
  };

  // --- fetch ONE company profile (core record incl. headline financials) -----
  async function profile(id) {
    const j = await api("/api/4.0/companies", {
      view: "profile",
      filter: { id: [id] },
      from: 0,
      size: 1,
    });
    return j.result && j.result[0];
  }

  // --- flatten a profile record into a single flat row -----------------------
  function flatten(c) {
    if (!c) return null;
    const rev = money(c.latestRevenue);
    const ebitda = money(c.latestEBITDA);
    const np = money(c.latestNetProfit);
    const val = money(c.latestValuation);
    const L = loc(c.locations);
    const emp = c.latestEmployeeCount;
    return {
      id: c.id,
      name: c.name,
      website: (c.website && c.website[0] && c.website[0].url) || "",
      founded: c.foundedYear || "",
      stage: c.stage || "",
      city: L.city || "",
      country: L.country || "",
      sector: sectorPath(c.primaryTaxonomy),
      short_description: (c.shortDescription || "").replace(/\s+/g, " ").trim(),
      revenue_inr_cr: rev.inr_cr ?? "",
      revenue_usd_m: rev.usd_m ?? "",
      revenue_as_on: rev.as_on || "",
      revenue_growth_1y: rev.growth_1y ?? "",
      revenue_growth_3y: rev.growth_3y ?? "",
      ebitda_inr_cr: ebitda.inr_cr ?? "",
      ebitda_as_on: ebitda.as_on || "",
      net_profit_inr_cr: np.inr_cr ?? "",
      net_profit_as_on: np.as_on || "",
      valuation_inr_cr: val.inr_cr ?? "",
      valuation_usd_m: val.usd_m ?? "",
      valuation_as_on: val.as_on || "",
      employee_count: (emp && (emp.value ?? emp)) || "",
      total_equity_funding_usd_m:
        c.totalEquityFunding && c.totalEquityFunding.amount && c.totalEquityFunding.amount.USD
          ? +(c.totalEquityFunding.amount.USD.value / 1e6).toFixed(2)
          : "",
      tracxn_score: c.tracxnScore && (c.tracxnScore.value ?? c.tracxnScore) || "",
      investors: names(c.investors, (i) => i.name || (i.institutionalInvestor && i.institutionalInvestor.name)),
      key_people: names(c.keyPeople, (p) => {
        const nm = p.name || (p.person && p.person.name);
        const role = p.designation || p.role || (p.roles && p.roles[0]);
        return nm ? (role ? `${nm} (${role})` : nm) : "";
      }),
      legal_entity_ids: (c.legalEntities || []).map((e) => e.id).join("; "),
      tracxn_url: c.tracxnPlatformUrl || "",
    };
  }

  // --- OPTIONAL: detailed statutory (MCA) financials for an Indian entity -----
  // Returns the raw filing records; wire into your own parser if you need the
  // full year-by-year P&L / balance sheet line items.
  async function statutoryFinancials(legalEntityId) {
    const agg = await api("/api/4.0/statutoryfilings/aggregation", {
      dataset: "query",
      filter: {
        documentType: ["Financial Documents", "Annual Reports"],
        legalEntityId: [legalEntityId],
        tracxnUrl: "t_all",
      },
      aggMap: [
        { field: "documentType", includeBucket: ["Financial Documents"],
          aggMap: [{ field: "id", size: 5, operation: "sort",
            sort: [{ sortField: "metaPropertiesCurrentYearStartDate", order: "DESC" }] }] },
      ],
    });
    // pull filing ids out of the aggregation buckets (best-effort)
    const ids = [];
    JSON.stringify(agg, (k, v) => { if (k === "id" && typeof v === "string" && v.length === 24) ids.push(v); return v; });
    if (!ids.length) return { filings: [], note: "no filing ids found" };
    const filings = await api("/api/4.0/statutoryfilings/india", {
      dataset: "query",
      filter: { id: Array.from(new Set(ids)).slice(0, 10) },
    });
    return filings;
  }

  // --- CSV + download ---------------------------------------------------------
  function toCSV(rows) {
    if (!rows.length) return "";
    const cols = Object.keys(rows[0]);
    const esc = (v) => {
      v = v == null ? "" : String(v);
      return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
    };
    return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
  }
  function download(text, filename, type) {
    const blob = new Blob([text], { type: type || "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // --- MAIN: loop over ids, flatten, download CSV + JSON ----------------------
  async function runList(ids, opts) {
    opts = opts || {};
    const rows = [];
    const errors = [];
    console.log(`%cTRACXN extractor: ${ids.length} companies, ${DELAY_MS}ms apart`, "color:#c60;font-weight:bold");
    for (let i = 0; i < ids.length; i++) {
      const id = ids[i];
      try {
        const c = await profile(id);
        const row = flatten(c);
        if (opts.financials && row && row.legal_entity_ids) {
          row._statutory = await statutoryFinancials(row.legal_entity_ids.split("; ")[0]);
        }
        rows.push(row);
        console.log(`  [${i + 1}/${ids.length}] ${row ? row.name : "(empty)"}  rev ₹${row && row.revenue_inr_cr || "-"}Cr`);
      } catch (e) {
        errors.push({ id, error: String(e) });
        console.warn(`  [${i + 1}/${ids.length}] ${id} FAILED: ${e}`);
      }
      if (i < ids.length - 1) await sleep(DELAY_MS);
    }
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    download(toCSV(rows), `tracxn_${stamp}.csv`, "text/csv");
    download(JSON.stringify(rows, null, 2), `tracxn_${stamp}.json`, "application/json");
    console.log(`%cDONE: ${rows.length} ok, ${errors.length} failed. Files downloaded.`, "color:green;font-weight:bold");
    if (errors.length) console.table(errors);
    return { rows, errors };
  }

  // --- discover ids in bulk by paging a filtered company query ---------------
  // Pass a Tracxn filter object (copy one from a list/sector page's network
  // request) and this pages through every match, returning all company ids.
  async function discover(filter, opts) {
    opts = opts || {};
    const pageSize = opts.pageSize || 50;
    const cap = opts.max || 1000;
    let from = 0, all = [];
    while (from < cap) {
      const j = await api("/api/4.0/companies", { view: "profile", filter, from, size: pageSize });
      const batch = (j.result || []).map((c) => ({ id: c.id, name: c.name }));
      all = all.concat(batch);
      console.log(`  discovered ${all.length}${j.total_count ? "/" + j.total_count : ""}`);
      if (batch.length < pageSize) break;
      from += pageSize;
      await sleep(DELAY_MS);
    }
    console.log(`%cdiscover: ${all.length} ids`, "color:#06c");
    return all;
  }

  // --- convenience: resolve a company id from a name -------------------------
  // Uses the autocomplete endpoint. The company id for /api/4.0/companies is
  // payload.domainProfileId (NOT payload.id, which is a search token).
  async function fromSearch(query, size) {
    const r = await api("/api/2.2/autocomplete", {
      term: query,
      query: { name: "company", size: size || 10 },
    });
    const hits = (Array.isArray(r) ? r : [])
      .map((x) => x.payload)
      .filter((p) => p && p.domainProfileId)
      .map((p) => ({
        id: p.domainProfileId,
        name: p.companyName,
        stage: p.companyStage,
        country: p.location && p.location.country,
        website: p.domainName,
      }));
    console.table(hits);
    return hits;
  }

  // resolve just the top-match id for a name (handy for scripting)
  async function idOf(query) {
    const hits = await fromSearch(query, 1);
    return hits[0] && hits[0].id;
  }

  window.TRACXN = {
    run: runList,           // alias
    runList,
    discover,
    profile,
    flatten,
    fromSearch,
    idOf,
    statutoryFinancials,
    toCSV,
    config: { BASE, DELAY_MS, RETRY },
  };
  console.log("%cTRACXN ready. Try:  await TRACXN.run([\"52bfc960e4b0420b03968ee8\"])", "color:#06c;font-weight:bold");
})();
