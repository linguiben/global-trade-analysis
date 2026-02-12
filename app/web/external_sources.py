from __future__ import annotations

import json
import re
import time
import html as _html
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen


DREWRY_WCI_URL = "https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry"


@dataclass
class _CacheEntry:
    value: Dict[str, Any]
    expires_at: float


# Very small in-process cache to avoid hammering upstream.
_CACHE: Dict[str, _CacheEntry] = {}


def _get_cached(key: str) -> Optional[Dict[str, Any]]:
    e = _CACHE.get(key)
    if not e:
        return None
    if time.time() >= e.expires_at:
        return None
    return e.value


def _set_cached(key: str, value: Dict[str, Any], ttl_seconds: int) -> None:
    _CACHE[key] = _CacheEntry(value=value, expires_at=time.time() + ttl_seconds)


def _strip_html(s: str) -> str:
    # Remove tags and decode entities; keep it simple and dependency-free.
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _shorten_text(s: str, max_chars: int = 260, max_sentences: int = 2) -> str:
    s = (s or "").strip()
    if not s:
        return s

    # Prefer keeping the first N sentences.
    # Split on ". " while keeping simple abbreviations risk acceptable for MVP.
    parts = re.split(r"(?<=[.!?])\s+", s)
    if len(parts) > 1:
        s2 = " ".join(parts[:max_sentences]).strip()
    else:
        s2 = s

    if len(s2) > max_chars:
        s2 = s2[: max_chars - 1].rstrip() + "…"

    return s2


def fetch_drewry_wci(ttl_seconds: int = 6 * 60 * 60, force: bool = False) -> Dict[str, Any]:
    """Fetch Drewry WCI headline value from the public page.

    Notes:
    - Best-effort parsing (page structure may change).
    - Cached for ttl_seconds.
    """

    cache_key = "drewry_wci"
    cached = None if force else _get_cached(cache_key)
    if cached:
        return {**cached, "cached": True}

    req = Request(
        DREWRY_WCI_URL,
        headers={
            "User-Agent": "GTA (Global Trade Analysis) dashboard bot; contact: admin",
            "Accept": "text/html,application/xhtml+xml",
        },
    )

    try:
        with urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        # Fall back to stale cached value if present.
        stale = _CACHE.get(cache_key)
        if stale:
            return {**stale.value, "cached": True, "stale": True, "error": str(e)}
        return {
            "source": "Drewry WCI (auto)",
            "link": DREWRY_WCI_URL,
            "period": None,
            "value_usd_per_40ft": None,
            "commentary": "Fetch failed; showing placeholder.",
            "error": str(e),
        }

    # Extract period from title-like text: "World Container Index - 05 Feb"
    period = None
    m_period = re.search(r"World\s+Container\s+Index\s*-\s*(\d{1,2}\s+[A-Za-z]{3})", html, re.IGNORECASE)
    if m_period:
        period = m_period.group(1)

    # Extract the headline: "decreased 7% to $1,959 per 40ft container"
    value = None
    direction = None  # 'up' | 'down'
    change_pct = None

    m_headline = re.search(
        r"World\s+Container\s+Index\s+(?:increased|decreased)\s+([0-9]+)%\s+to\s*\$\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)\s*per\s*40ft",
        html,
        re.IGNORECASE,
    )
    if m_headline:
        change_pct = int(m_headline.group(1))
        value = int(m_headline.group(2).replace(",", ""))
        direction = "down" if "decreased" in m_headline.group(0).lower() else "up"
    else:
        m_value = re.search(r"to\s*\$\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)\s*per\s*40ft", html, re.IGNORECASE)
        if m_value:
            value = int(m_value.group(1).replace(",", ""))

    # Extract a few lane quotes if present (best-effort)
    lanes = []
    lane_patterns = [
        ("Shanghai→Los Angeles", r"Los Angeles.*?(?:dropping|rising)\s*([0-9]+)%\s*to\s*\$\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"),
        ("Shanghai→New York", r"New York.*?(?:dropping|rising)\s*([0-9]+)%\s*to\s*\$\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"),
        ("Shanghai→Rotterdam", r"Shanghai[–-]Rotterdam.*?(?:dropping|rising)\s*([0-9]+)%\s*to\s*\$\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"),
        ("Shanghai→Genoa", r"Shanghai[–-]Genoa.*?(?:dropping|rising)\s*([0-9]+)%\s*to\s*\$\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"),
    ]
    for name, pat in lane_patterns:
        m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if m:
            pct = int(m.group(1))
            price = int(m.group(2).replace(",", ""))
            dir2 = "down" if "dropp" in m.group(0).lower() else "up"
            lanes.append({"route": name, "direction": dir2, "change_pct": pct, "usd_per_40ft": price})

    # Extract assessment paragraph (best-effort)
    assessment = None
    m_assess = re.search(r"Our detailed assessment.*?(The\s+Drewry.*?)(?:Related Research|Featured Services)", html, re.IGNORECASE | re.DOTALL)
    if m_assess:
        assessment = _shorten_text(_strip_html(m_assess.group(1)))

    # Extract expectation sentence if present
    expectation = None
    m_expect = re.search(r"Hence, we expect.*?\.|Drewry expects.*?\.\s*", html, re.IGNORECASE)
    if m_expect:
        expectation = _strip_html(m_expect.group(0))

    # Build analysis-style commentary in English (derived only from extracted text)
    parts = []
    if value is not None:
        if change_pct is not None and direction:
            sign = "-" if direction == "down" else "+"
            parts.append(f"WCI {sign}{change_pct}% to ${value:,}/40ft ({period or 'latest'}).")
        else:
            parts.append(f"WCI at ${value:,}/40ft ({period or 'latest'}).")

    if lanes:
        lane_bits = []
        for ln in lanes[:4]:
            sign = "-" if ln["direction"] == "down" else "+"
            lane_bits.append(f"{ln['route']} {sign}{ln['change_pct']}% to ${ln['usd_per_40ft']:,}")
        parts.append("Key lanes: " + "; ".join(lane_bits) + ".")

    if expectation:
        parts.append(expectation)

    analysis_commentary = " ".join(parts) if parts else None

    payload = {
        "source": "Drewry World Container Index (auto) · public page",
        "link": DREWRY_WCI_URL,
        "period": period,
        "value_usd_per_40ft": value,
        "direction": direction,
        "change_pct": change_pct,
        "lanes": lanes,
        "commentary": assessment or "Auto-extracted from public Drewry WCI page.",
        "analysis_commentary": analysis_commentary,
    }

    _set_cached(cache_key, payload, ttl_seconds=ttl_seconds)
    return {**payload, "cached": False}
