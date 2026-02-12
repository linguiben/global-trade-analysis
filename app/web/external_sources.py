from __future__ import annotations

import json
import re
import time
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


def fetch_drewry_wci(ttl_seconds: int = 6 * 60 * 60) -> Dict[str, Any]:
    """Fetch Drewry WCI headline value from the public page.

    Notes:
    - Best-effort parsing (page structure may change).
    - Cached for ttl_seconds.
    """

    cache_key = "drewry_wci"
    cached = _get_cached(cache_key)
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
    m_value = re.search(r"to\s*\$\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)\s*per\s*40ft", html, re.IGNORECASE)
    if m_value:
        value = int(m_value.group(1).replace(",", ""))

    # Extract first sentence after chart; fallback to trimmed summary.
    commentary = None
    m_commentary = re.search(
        r"Our detailed assessment.*?(The\s+Drewry.*?\.)",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if m_commentary:
        commentary = re.sub(r"\s+", " ", m_commentary.group(1)).strip()

    payload = {
        "source": "Drewry World Container Index (auto) · public page",
        "link": DREWRY_WCI_URL,
        "period": period,
        "value_usd_per_40ft": value,
        "commentary": commentary or "Auto-extracted from public Drewry WCI page.",
    }

    _set_cached(cache_key, payload, ttl_seconds=ttl_seconds)
    return {**payload, "cached": False}
