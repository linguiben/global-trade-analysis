from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen


@dataclass
class _CacheEntry:
    value: Dict[str, Any]
    expires_at: float


_CACHE: Dict[str, _CacheEntry] = {}


def _get_cached(key: str) -> Optional[Dict[str, Any]]:
    e = _CACHE.get(key)
    if not e or time.time() >= e.expires_at:
        return None
    return e.value


def _set_cached(key: str, value: Dict[str, Any], ttl_seconds: int) -> None:
    _CACHE[key] = _CacheEntry(value=value, expires_at=time.time() + ttl_seconds)


def _to_number(s: str) -> Optional[float]:
    s = (s or "").strip()
    if not s:
        return None
    s = s.replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def fetch_disposable_income_latest(ttl_seconds: int = 24 * 60 * 60, force: bool = False) -> Dict[str, Any]:
    """Best-effort scrape from WorldPopulationReview country rankings page.

    IMPORTANT: This is a secondary source; structure may change.
    This returns latest point only (no 5Y history).

    Page used (current): disposable-income-by-country
    """

    url = "https://worldpopulationreview.com/country-rankings/disposable-income-by-country"
    key = "wpr:disposable_income_latest"
    cached = None if force else _get_cached(key)
    if cached:
        return {**cached, "cached": True}

    req = Request(url, headers={"User-Agent": "GTA dashboard"})

    try:
        with urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        payload = {
            "ok": False,
            "source": "worldpopulationreview.com",
            "link": url,
            "rows": {},
            "error": str(e),
        }
        _set_cached(key, payload, ttl_seconds)
        return {**payload, "cached": False}

    # Extract the embedded JSON blob used by Next.js if present.
    rows: Dict[str, Dict[str, Any]] = {}

    # Try to find a JSON object containing a table.
    m = re.search(r"__NEXT_DATA__" r"\s*type=\"application/json\"[^>]*>(\{.*?\})</script>", html, re.DOTALL)
    if m:
        # As a minimal parser, just look for country names near 'disposable' values.
        # This is intentionally conservative; if it fails, we still return ok=True with empty rows.
        pass

    # Fallback: scrape from visible table rows (very best-effort)
    # Look for patterns like: <td>Singapore</td> ... <td>$xx,xxx</td>
    # We only keep the countries we care about.
    targets = {
        "India": ["India"],
        "Mexico": ["Mexico"],
        "Singapore": ["Singapore"],
        "Hong Kong": ["Hong Kong", "Hong Kong SAR", "Hong Kong (China)", "Hong Kong SAR, China"],
        "Global": ["World", "Global"],
    }

    def find_value_for(aliases):
        for name in aliases:
            # capture up to 3 <td> after the country cell
            pat = re.compile(rf">\s*{re.escape(name)}\s*<.*?</td>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
            mm = pat.search(html)
            if not mm:
                continue
            chunk = mm.group(1)
            # take first two numbers as per-capita / per-household if present
            nums = re.findall(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)", chunk)
            if nums:
                vals = [float(x.replace(",", "")) for x in nums[:2]]
                per_capita = vals[0] if len(vals) >= 1 else None
                per_household = vals[1] if len(vals) >= 2 else None
                return per_capita, per_household
        return None, None

    for k, aliases in targets.items():
        pc, hh = find_value_for(aliases)
        if pc is not None or hh is not None:
            rows[k] = {"per_capita_usd": pc, "per_household_usd": hh}

    payload = {
        "ok": True,
        "source": "worldpopulationreview.com (scrape)",
        "link": url,
        "note": "Secondary source; best-effort parsing; latest point only (no guaranteed history).",
        "rows": rows,
    }
    _set_cached(key, payload, ttl_seconds)
    return {**payload, "cached": False}
