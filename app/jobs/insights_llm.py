from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.config import settings

logger = logging.getLogger(__name__)


def _json_dump(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(obj)


def _redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        q = parse_qsl(parts.query, keep_blank_values=True)
        redacted = []
        for k, v in q:
            if k.lower() in {"key", "api_key", "apikey", "token", "access_token"}:
                redacted.append((k, "***"))
            else:
                redacted.append((k, v))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(redacted, doseq=True), parts.fragment))
    except Exception:
        return url


def _http_error_body(err: HTTPError) -> str:
    try:
        raw = err.read()
        if not raw:
            return ""
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _strip_code_fences(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _decode_escaped(s: str) -> str:
    try:
        return json.loads(f"\"{s}\"")
    except Exception:
        return s


def _extract_references_from_text(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    m = re.search(r"\"references\"\s*:\s*(\[[\s\S]*?\])", text)
    if not m:
        return []
    block = m.group(1)
    try:
        arr = json.loads(block)
    except Exception:
        return []
    return arr if isinstance(arr, list) else []


def _extract_json_object(text: str) -> dict:
    """Best-effort extraction of a JSON object from LLM text.

    Gemini sometimes returns almost-JSON with unescaped newlines inside strings; we add a regex fallback.
    """
    if not text:
        return {}
    t = _strip_code_fences(text)
    # Direct parse
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    # Find first {...} block
    m = re.search(r"\{[\s\S]*\}", t)
    block = m.group(0) if m else t
    try:
        obj = json.loads(block)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Regex fallback: insight is accepted even without references key.
    mm = re.search(r"\"insight\"\s*:\s*\"((?:\\.|[^\"\\])*)\"", block, flags=re.DOTALL)
    if mm:
        insight = _decode_escaped(mm.group(1)).strip()
        return {"insight": insight, "references": _extract_references_from_text(block)}

    mm2 = re.search(r"'insight'\s*:\s*'((?:\\.|[^'\\])*)'", block, flags=re.DOTALL)
    if mm2:
        insight = mm2.group(1).encode("utf-8", errors="ignore").decode("unicode_escape", errors="ignore").strip()
        return {"insight": insight, "references": _extract_references_from_text(block)}

    mm3 = re.search(r"(?is)\binsight\b\s*[:：]\s*(.+?)(?:\n\s*\breferences\b\s*[:：]|\Z)", t)
    if mm3:
        insight = mm3.group(1).strip()
        return {"insight": insight, "references": _extract_references_from_text(t)}

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
    endpoint: str = ""
    request_payload: dict[str, Any] | None = None
    response_status: int | None = None
    response_raw: str = ""
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
        logger.info("LLM skipped: provider disabled (provider=%s, model=%s)", provider, model)
        return LLMResult(ok=False, content="", references=[], provider=provider, model=model, error="llm disabled")

    if provider == "openai":
        api_key = (settings.OPENAI_API_KEY or "").strip()
        if not api_key:
            logger.error("LLM config error: OPENAI_API_KEY missing (provider=%s, model=%s)", provider, model)
            return LLMResult(ok=False, content="", references=[], provider=provider, model=model, error="OPENAI_API_KEY missing")

        endpoint = "https://api.openai.com/v1/chat/completions"
        redacted_endpoint = _redact_url(endpoint)
        payload = {
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }

        logger.info(
            "LLM request start provider=%s model=%s endpoint=%s system=%s user=%s payload=%s",
            provider,
            model,
            redacted_endpoint,
            system,
            user,
            _json_dump(payload),
        )
        started = time.perf_counter()
        req = Request(
            endpoint,
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
                status = getattr(resp, "status", None) or resp.getcode()
                headers = dict(resp.headers.items()) if getattr(resp, "headers", None) else {}
                raw = resp.read().decode("utf-8", errors="ignore")
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "LLM response provider=%s model=%s endpoint=%s status=%s duration_ms=%d headers=%s raw=%s",
                provider,
                model,
                redacted_endpoint,
                status,
                duration_ms,
                _json_dump(headers),
                raw,
            )
            j = json.loads(raw)
            text = j["choices"][0]["message"]["content"]
            out = _extract_json_object(text)
            content = str(out.get("insight") or out.get("Insight") or out.get("output") or out.get("result") or "").strip()
            refs = out.get("references")
            references = refs if isinstance(refs, list) else []
            logger.info(
                "LLM parsed provider=%s model=%s endpoint=%s content=%s references=%s",
                provider,
                model,
                redacted_endpoint,
                content,
                _json_dump(references),
            )
            if not content:
                snippet = (text or "")[:200].replace("\n", " ")
                return LLMResult(
                    ok=False,
                    content="",
                    references=references,
                    provider=provider,
                    model=model,
                    endpoint=redacted_endpoint,
                    request_payload=payload,
                    response_status=status,
                    response_raw=raw,
                    error=f"empty insight; raw={snippet}",
                )
            return LLMResult(
                ok=True,
                content=content,
                references=references,
                provider=provider,
                model=model,
                endpoint=redacted_endpoint,
                request_payload=payload,
                response_status=status,
                response_raw=raw,
            )
        except HTTPError as e:
            duration_ms = int((time.perf_counter() - started) * 1000)
            err_body = _http_error_body(e)
            logger.error(
                "LLM HTTP error provider=%s model=%s endpoint=%s status=%s reason=%s duration_ms=%d payload=%s error_body=%s",
                provider,
                model,
                redacted_endpoint,
                getattr(e, "code", ""),
                getattr(e, "reason", ""),
                duration_ms,
                _json_dump(payload),
                err_body,
            )
            msg = f"http {getattr(e, 'code', '')} {getattr(e, 'reason', '')}; body={err_body}"
            return LLMResult(
                ok=False,
                content="",
                references=[],
                provider=provider,
                model=model,
                endpoint=redacted_endpoint,
                request_payload=payload,
                response_status=getattr(e, "code", None),
                response_raw=err_body,
                error=msg,
            )
        except Exception as e:  # noqa: BLE001
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "LLM request exception provider=%s model=%s endpoint=%s duration_ms=%d payload=%s",
                provider,
                model,
                redacted_endpoint,
                duration_ms,
                _json_dump(payload),
            )
            return LLMResult(
                ok=False,
                content="",
                references=[],
                provider=provider,
                model=model,
                endpoint=redacted_endpoint,
                request_payload=payload,
                response_raw="",
                error=str(e),
            )

    if provider == "gemini":
        api_key = (settings.GEMINI_API_KEY or "").strip()
        if not api_key:
            logger.error("LLM config error: GEMINI_API_KEY missing (provider=%s, model=%s)", provider, model)
            return LLMResult(ok=False, content="", references=[], provider=provider, model=model, error="GEMINI_API_KEY missing")

        # Google Generative Language API (REST). Model id example: gemini-3-flash-preview
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        redacted_url = _redact_url(url)
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

        logger.info(
            "LLM request start provider=%s model=%s endpoint=%s system=%s user=%s payload=%s",
            provider,
            model,
            redacted_url,
            system,
            user,
            _json_dump(payload),
        )
        started = time.perf_counter()
        req = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "GTA-insight-job"},
            method="POST",
        )

        try:
            with urlopen(req, timeout=40) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                headers = dict(resp.headers.items()) if getattr(resp, "headers", None) else {}
                raw = resp.read().decode("utf-8", errors="ignore")
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "LLM response provider=%s model=%s endpoint=%s status=%s duration_ms=%d headers=%s raw=%s",
                provider,
                model,
                redacted_url,
                status,
                duration_ms,
                _json_dump(headers),
                raw,
            )
            j = json.loads(raw)
            # candidates[0].content.parts[0].text
            text = (
                (((j.get("candidates") or [])[0] or {}).get("content") or {}).get("parts") or [{}]
            )[0].get("text")
            if not text:
                return LLMResult(
                    ok=False,
                    content="",
                    references=[],
                    provider=provider,
                    model=model,
                    endpoint=redacted_url,
                    request_payload=payload,
                    response_status=status,
                    response_raw=raw,
                    error="empty response",
                )
            out = _extract_json_object(text)
            content = str(out.get("insight") or out.get("Insight") or out.get("output") or out.get("result") or "").strip()
            refs = out.get("references")
            references = refs if isinstance(refs, list) else []
            logger.info(
                "LLM parsed provider=%s model=%s endpoint=%s content=%s references=%s",
                provider,
                model,
                redacted_url,
                content,
                _json_dump(references),
            )
            if not content:
                snippet = (text or "")[:200].replace("\n", " ")
                return LLMResult(
                    ok=False,
                    content="",
                    references=references,
                    provider=provider,
                    model=model,
                    endpoint=redacted_url,
                    request_payload=payload,
                    response_status=status,
                    response_raw=raw,
                    error=f"empty insight; raw={snippet}",
                )
            return LLMResult(
                ok=True,
                content=content,
                references=references,
                provider=provider,
                model=model,
                endpoint=redacted_url,
                request_payload=payload,
                response_status=status,
                response_raw=raw,
            )
        except HTTPError as e:
            duration_ms = int((time.perf_counter() - started) * 1000)
            err_body = _http_error_body(e)
            logger.error(
                "LLM HTTP error provider=%s model=%s endpoint=%s status=%s reason=%s duration_ms=%d payload=%s error_body=%s",
                provider,
                model,
                redacted_url,
                getattr(e, "code", ""),
                getattr(e, "reason", ""),
                duration_ms,
                _json_dump(payload),
                err_body,
            )
            msg = f"http {getattr(e, 'code', '')} {getattr(e, 'reason', '')}; body={err_body}"
            return LLMResult(
                ok=False,
                content="",
                references=[],
                provider=provider,
                model=model,
                endpoint=redacted_url,
                request_payload=payload,
                response_status=getattr(e, "code", None),
                response_raw=err_body,
                error=msg,
            )
        except Exception as e:  # noqa: BLE001
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "LLM request exception provider=%s model=%s endpoint=%s duration_ms=%d payload=%s",
                provider,
                model,
                redacted_url,
                duration_ms,
                _json_dump(payload),
            )
            return LLMResult(
                ok=False,
                content="",
                references=[],
                provider=provider,
                model=model,
                endpoint=redacted_url,
                request_payload=payload,
                response_raw="",
                error=str(e),
            )

    logger.error("LLM config error: unsupported provider=%s model=%s", provider, model)
    return LLMResult(ok=False, content="", references=[], provider=provider, model=model, error=f"unsupported provider: {provider}")


def now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
