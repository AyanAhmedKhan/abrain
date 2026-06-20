"""gbrain · Gemini client (analysis + embeddings).

Auth, either of:
  GEMINI_API_KEY=...                          (Google AI Studio key — simplest)
  GOOGLE_GENAI_USE_VERTEXAI=true              (Vertex — burns credits)
    + GOOGLE_CLOUD_PROJECT=... GOOGLE_CLOUD_LOCATION=asia-south1
    + GOOGLE_APPLICATION_CREDENTIALS=/path/sa.json

Models (env-overridable):
  EXTRACT_MODEL   default gemini-2.5-flash    (2.0-flash is SHUT DOWN — do not use)
  ESCALATE_MODEL  default gemini-2.5-pro      (used when extraction confidence is low)
  EMBED_MODEL     default gemini-embedding-001 @ 768 dims (matches gb_chunk vector(768))

GBRAIN_FAKE_LLM=1 short-circuits both calls with deterministic outputs so the
pipeline can be tested end-to-end without tokens or credentials.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

EXTRACT_MODEL = os.environ.get("EXTRACT_MODEL", "gemini-2.5-flash")
ESCALATE_MODEL = os.environ.get("ESCALATE_MODEL", "gemini-2.5-pro")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIMS = int(os.environ.get("EMBED_DIMS", "768"))

FAKE = os.environ.get("GBRAIN_FAKE_LLM") == "1"

_FAKE_NOTE = {
    "company_name": "Acme Robotics", "sector": "DeepTech", "sub_sector": "Robotics",
    "stage": "Series A", "round_type": "Series A", "ask_inr_cr": 40,
    "valuation_inr_cr": 160, "revenue_inr_cr": 6, "revenue_period": "FY26",
    "ebitda_inr_cr": None, "founders": [{"name": "Test Founder", "role": "CEO"}],
    "key_metrics": ["ARR ₹6 Cr"], "summary": "Fake-mode extraction for pipeline tests.",
    "risks": ["fake"], "action_items": [], "confidence": "high",
}

_client = None


def _coerce(data):
    """The pipeline expects ONE note object. If the model returns an array
    (e.g. a forwarded thread naming several companies), keep the first as the
    primary note and record the rest under 'also_mentioned'."""
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        objs = [d for d in data if isinstance(d, dict)]
        if not objs:
            return {}
        primary = dict(objs[0])
        extra = [d.get("company_name") for d in objs[1:] if d.get("company_name")]
        if extra:
            primary["also_mentioned"] = extra
        return primary
    return {}


def client():
    global _client
    if _client is None:
        from google import genai  # deferred so FAKE mode needs no credentials
        _client = genai.Client()  # reads GEMINI_API_KEY or Vertex env automatically
    return _client


@dataclass
class LLMResult:
    data: dict
    model: str
    tokens_in: int
    tokens_out: int


def generate_json(prompt: str, text: str, model: str | None = None) -> LLMResult:
    """One structured-JSON analysis call."""
    mdl = model or EXTRACT_MODEL
    if FAKE:
        return LLMResult(dict(_FAKE_NOTE), "fake-llm", 0, 0)
    resp = client().models.generate_content(
        model=mdl,
        contents=f"{prompt}\n\n<document>\n{text}\n</document>",
        config={"response_mime_type": "application/json", "temperature": 0.1},
    )
    return _result(resp, mdl)


def generate_json_from_pdf(prompt: str, pdf_bytes: bytes, model: str | None = None) -> LLMResult:
    """Structured analysis straight from a PDF (image/scanned decks) via Gemini
    multimodal — no local text layer needed."""
    mdl = model or EXTRACT_MODEL
    if FAKE:
        return LLMResult({**_FAKE_NOTE, "_multimodal": True}, "fake-llm", 0, 0)
    from google.genai import types
    resp = client().models.generate_content(
        model=mdl,
        contents=[types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"), prompt],
        config={"response_mime_type": "application/json", "temperature": 0.1},
    )
    return _result(resp, mdl)


def _result(resp, mdl: str) -> LLMResult:
    raw = (resp.text or "").strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = _coerce(json.loads(raw))
    except (json.JSONDecodeError, ValueError) as e:
        # salvage: grab the first {...} block; else low-confidence stub (no DLQ)
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            data = _coerce(json.loads(m.group(0))) if m else {}
        except Exception:
            data = {}
        if not data:
            print(f"[gemini] JSON parse failed ({e}); raw[:120]={raw[:120]!r}", flush=True)
            data = {"company_name": None, "confidence": "low", "_parse_error": str(e)}
    usage = getattr(resp, "usage_metadata", None)
    return LLMResult(
        data, mdl,
        getattr(usage, "prompt_token_count", 0) or 0,
        getattr(usage, "candidates_token_count", 0) or 0,
    )


def generate_text(prompt: str, model: str | None = None) -> str:
    """A plain prose completion (used by 'ask the brain' Q&A)."""
    mdl = model or EXTRACT_MODEL
    if FAKE:
        return "[fake-llm answer] " + prompt.split("Question:", 1)[-1].strip()[:80]
    resp = client().models.generate_content(
        model=mdl, contents=prompt, config={"temperature": 0.2})
    return (resp.text or "").strip()


def embed(texts: list[str]) -> list[list[float]]:
    """Batch-embed texts → EMBED_DIMS-dim vectors."""
    if FAKE:
        return [[(hash(t[:64]) % 1000) / 1000.0] * EMBED_DIMS for t in texts]
    from google.genai import types
    resp = client().models.embed_content(
        model=EMBED_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(output_dimensionality=EMBED_DIMS),
    )
    return [e.values for e in resp.embeddings]
