"""
Offline pipeline smoke test — no network, no Playwright.
Exercises: normalize -> FanoutSink -> (JsonlSink + GbrainSink dry-run + batching).

Run:  python tests/smoke_offline.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# configure BEFORE importing config (it reads env at construction)
tmp = tempfile.mkdtemp(prefix="tracxn_smoke_")
os.environ["TRACXN_JSONL"] = os.path.join(tmp, "out.jsonl")
os.environ["GBRAIN_WEBHOOK_URL"] = "https://gbrain.example/ingest"
os.environ["GBRAIN_DRY_RUN"] = "1"
os.environ["GBRAIN_BATCH"] = "2"

from tracxn.config import Config            # noqa: E402
from tracxn.normalize import flatten        # noqa: E402
from tracxn.sinks import JsonlSink, GbrainSink, FanoutSink  # noqa: E402

cfg = Config()
records = json.load(open(os.path.join(HERE, "fixture_live.json"), encoding="utf-8"))

sinks = FanoutSink([JsonlSink(cfg.jsonl_path), GbrainSink(cfg)])
for r in records:
    sinks.push(flatten(r))
sinks.close()

lines = [json.loads(l) for l in open(cfg.jsonl_path, encoding="utf-8")]
assert len(lines) == len(records), f"jsonl rows {len(lines)} != {len(records)}"
assert {l["name"] for l in lines} == {"Lenskart", "Paytm", "Stripe", "Zerodha"}
assert lines[1]["net_profit_inr_cr"] == -663.2          # negative survived JSONL round-trip
assert lines[2]["valuation_usd_m"] == 159000.0           # foreign/USD
assert all("revenue_inr_cr" in l for l in lines)         # schema present
print(f"PASS — {len(lines)} rows written to JSONL; gbrain dry-run batched at {cfg.gbrain_batch}.")
print("JSONL sample:", json.dumps(lines[0], ensure_ascii=False)[:160], "...")
