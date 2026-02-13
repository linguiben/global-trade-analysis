from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen

from app.config import settings


def _extract_json_object(text: str) -> dict:
    """Best-effort extraction of a JSON object from LLM text."""
    if not text:
        return {}
    t = text.strip()
    # Strip markdown code fences
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)
    # Direct parse
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    # Find first {...} block
    m = re.search(r"\{[\s\S]*\}", t)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def digest_for_inputs(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class LLMResult:
    ok: bool
    content: str
    references: list[dict[str, Any]]
    provider: str
    model: str
    error: str | None = None


def generate_insight_with_llm(*, system: str, user: str) -> LLMResult:
    """Generate insight text using an optional LLM provider.

    Provider is controlled via env:
    - INSIGHT_LLM_PROVIDER=openai|gemini|none
    - OPENAI_API_KEY / GEMINI_API_KEY

    Notes:
    - Keys are secrets. Never log or print them.
    - This function returns JSON-parsed {insight, references[]}.
    """

    provider = (settings.INSIGHT_LLM_PROVIDER or "").strip().lower()
    model = (settings.INSIGHT_LLM_MODEL or "").strip() or "gpt-4o-mini"

    if provider in {"", "none", "off"}:
        return LLMResult(ok=False, content="", references=[], provider=provider, model=model, error="llm disabled")

    if provider == "openai":
        api_key = (settings.OPENAI_API_KEY or "").strip()
        if not api_key:
            return LLMResult(ok=False, content="", references=[], provider=provider, model=model, error="OPENAI_API_KEY missing")

        payload = {
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }

        req = Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "GTA-insight-job",
            },
            method="POST",
        )

        try:
            with urlopen(req, timeout=40) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            j = json.loads(raw)
            text = j["choices"][0]["message"]["content"]
            out = _extract_json_object(text)
            content = str(out.get("insight") or "").strip()
            refs = out.get("references")
            references = refs if isinstance(refs, list) else []
            if not content:
                return LLMResult(ok=False, content="", references=references, provider=provider, model=model, error="empty insight")
            return LLMResult(ok=True, content=content, references=references, provider=provider, model=model)
        except Exception as e:  # noqa: BLE001
            return LLMResult(ok=False, content="", references=[], provider=provider, model=model, error=str(e))

    if provider == "gemini":
        api_key = (settings.GEMINI_API_KEY or "").strip()
        if not api_key:
            return LLMResult(ok=False, content="", references=[], provider=provider, model=model, error="GEMINI_API_KEY missing")

        # Google Generative Language API (REST). Model id example: gemini-3-flash-preview
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": user},
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json",
            },
        }

        req = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "GTA-insight-job"},
            method="POST",
        )

        try:
            with urlopen(req, timeout=40) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            j = json.loads(raw)
            # candidates[0].content.parts[0].text
            text = (
                (((j.get("candidates") or [])[0] or {}).get("content") or {}).get("parts") or [{}]
            )[0].get("text")
            if not text:
                return LLMResult(ok=False, content="", references=[], provider=provider, model=model, error="empty response")
            out = _extract_json_object(text)
            content = str(out.get("insight") or "").strip()
            refs = out.get("references")
            references = refs if isinstance(refs, list) else []
            if not content:
                return LLMResult(ok=False, content="", references=references, provider=provider, model=model, error="empty insight")
            return LLMResult(ok=True, content=content, references=references, provider=provider, model=model)
        except Exception as e:  # noqa: BLE001
            return LLMResult(ok=False, content="", references=[], provider=provider, model=model, error=str(e))

    return LLMResult(ok=False, content="", references=[], provider=provider, model=model, error=f"unsupported provider: {provider}")


def now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
