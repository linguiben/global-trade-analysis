from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from app.db.models import PublicContext


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _strip_tags(html: str) -> str:
    # Remove scripts/styles
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
    # Drop tags
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    t = _strip_tags(m.group(1))
    return t[:240]


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    url: str
    title: str
    excerpt: str
    fetched_at: datetime
    error: str | None = None


def fetch_url_excerpt(url: str, *, timeout_seconds: int = 20, max_chars: int = 1800) -> FetchResult:
    req = Request(url, headers={"User-Agent": "GTA-insight-job"})
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        title = _extract_title(raw)
        text = _strip_tags(raw)
        excerpt = text[:max_chars]
        return FetchResult(ok=True, url=url, title=title, excerpt=excerpt, fetched_at=_now_utc())
    except Exception as e:  # noqa: BLE001
        return FetchResult(ok=False, url=url, title="", excerpt="", fetched_at=_now_utc(), error=str(e))


def get_or_refresh_context(
    db: Session,
    *,
    url: str,
    ttl_minutes: int = 360,
) -> PublicContext:
    """Get cached public context excerpt; refresh if missing/expired.

    ttl_minutes default 6h to reduce upstream load while keeping insights reasonably fresh.
    """

    row: PublicContext | None = (
        db.query(PublicContext)
        .filter(PublicContext.url == url)
        .order_by(PublicContext.fetched_at.desc())
        .first()
    )

    if row and row.fetched_at and row.fetched_at > (_now_utc() - timedelta(minutes=ttl_minutes)):
        return row

    fr = fetch_url_excerpt(url)
    db.add(
        PublicContext(
            url=url,
            title=fr.title,
            excerpt=fr.excerpt,
            ok=bool(fr.ok),
            error=fr.error or "",
            fetched_at=fr.fetched_at,
        )
    )
    db.flush()

    # Return the newly inserted one
    new_row: PublicContext | None = (
        db.query(PublicContext)
        .filter(PublicContext.url == url)
        .order_by(PublicContext.fetched_at.desc())
        .first()
    )
    return new_row or row  # type: ignore[return-value]


def to_prompt_block(row: PublicContext) -> dict[str, Any]:
    return {
        "url": row.url,
        "title": row.title,
        "excerpt": row.excerpt,
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        "ok": bool(row.ok),
        "error": row.error,
    }
