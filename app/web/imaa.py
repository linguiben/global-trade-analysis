from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen


IMAA_INDUSTRY_URL = "https://imaa-institute.org/mergers-and-acquisitions-statistics/ma-statistics-by-industries/"
IMAA_COUNTRY_URL = "https://imaa-institute.org/mergers-and-acquisitions-statistics/ma-statistics-by-countries/"


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


def _fetch_html(url: str) -> str:
    req = Request(url, headers={"User-Agent": "GTA dashboard"})
    with urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def fetch_ma_by_industry(ttl_seconds: int = 24 * 60 * 60, force: bool = False) -> Dict[str, Any]:
    """Parse IMAA industry ranking table (number of deals + value).

    Returns top rows as list.
    """

    key = "imaa:industry"
    cached = None if force else _get_cached(key)
    if cached:
        return {**cached, "cached": True}

    try:
        html = _fetch_html(IMAA_INDUSTRY_URL)
    except Exception as e:
        payload = {"ok": False, "source": "IMAA", "link": IMAA_INDUSTRY_URL, "rows": [], "error": str(e)}
        _set_cached(key, payload, ttl_seconds)
        return {**payload, "cached": False}

    # Find table rows: <tr> <td>rank</td><td>Industry</td><td>Number</td><td>Value USD</td> ...
    rows: List[Dict[str, Any]] = []

    # Use a fairly permissive regex for td values.
    for m in re.finditer(r"<tr[^>]*>\s*<td[^>]*>\s*(\d+)\s*</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>\s*([0-9'’,,]+)\s*</td>\s*<td[^>]*>\s*([0-9.,]+)\s*</td>", html, re.IGNORECASE | re.DOTALL):
        rank = int(m.group(1))
        industry = _strip_tags(m.group(2))
        num_s = m.group(3).replace("'", "").replace("’", "").replace(",", "").strip()
        try:
            deals = int(num_s)
        except Exception:
            deals = None
        try:
            value_usd_bil = float(m.group(4))
        except Exception:
            value_usd_bil = None

        rows.append({"rank": rank, "industry": industry, "deals": deals, "value_usd_bil": value_usd_bil})

    rows.sort(key=lambda r: r.get("rank", 10**9))

    payload = {
        "ok": True,
        "source": "IMAA (industry ranking)",
        "link": IMAA_INDUSTRY_URL,
        "currency": "USD",
        "unit": "bil.",
        "rows": rows,
        "note": "Parsed from public IMAA table (best-effort).",
    }
    _set_cached(key, payload, ttl_seconds)
    return {**payload, "cached": False}


def fetch_ma_by_country(ttl_seconds: int = 24 * 60 * 60, force: bool = False) -> Dict[str, Any]:
    """Extract per-country cumulative deals and value from IMAA country sections.

    IMPORTANT: The page provides narrative paragraphs by country; we derive a ranking by parsing
    the 'Since YEAR, COUNTRY has ... X deals ... value ... USD/EUR' sentence.
    """

    key = "imaa:country"
    cached = None if force else _get_cached(key)
    if cached:
        return {**cached, "cached": True}

    try:
        html = _fetch_html(IMAA_COUNTRY_URL)
    except Exception as e:
        payload = {"ok": False, "source": "IMAA", "link": IMAA_COUNTRY_URL, "rows": [], "error": str(e)}
        _set_cached(key, payload, ttl_seconds)
        return {**payload, "cached": False}

    text = _strip_tags(html)

    # Find headings like "M&A Australia" and capture following sentence.
    # We'll search the original HTML for the specific pattern to avoid losing structure.
    rows: List[Dict[str, Any]] = []

    # Pattern examples:
    # Since 1989, a total of approximately 53,972 M&A deals have been announced in Australia, reflecting a cumulative value exceeding 3.5 trillion USD.
    # Since 1985, Austria has witnessed over 9,164 announced M&A deals, amounting to a total value of more than 299.3 billion EUR.
    pat = re.compile(
        r"Since\s+(\d{4}).{0,80}?([0-9]{1,3}(?:[,'’][0-9]{3})+|\d{1,7}).{0,80}?deal.{0,120}?(?:in|for)\s+([A-Z][A-Za-z .&()-]+?),\s+.{0,120}?(?:value|valued?).{0,120}?([0-9]+(?:\.[0-9]+)?)\s*(trillion|billion|bil\.|million)?\s*(USD|EUR)",
        re.IGNORECASE,
    )

    for m in pat.finditer(text):
        since_year = int(m.group(1))
        deals_s = m.group(2).replace(",", "").replace("'", "").replace("’", "")
        try:
            deals = int(deals_s)
        except Exception:
            continue

        country = m.group(3).strip()
        val = float(m.group(4))
        scale = (m.group(5) or "").lower()
        ccy = (m.group(6) or "").upper()

        mult = 1.0
        if "trillion" in scale:
            mult = 1_000.0  # trillion -> billion
        elif "billion" in scale or "bil" in scale:
            mult = 1.0
        elif "million" in scale:
            mult = 0.001

        value_bil = val * mult

        rows.append({
            "country": country,
            "since_year": since_year,
            "deals": deals,
            "value_bil": value_bil,
            "currency": ccy,
            "value_unit": "bil.",
        })

    # Deduplicate by country keeping the max deals entry.
    dedup: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        k = r["country"].lower()
        if k not in dedup or (r.get("deals") or 0) > (dedup[k].get("deals") or 0):
            dedup[k] = r

    out = list(dedup.values())
    out.sort(key=lambda r: (r.get("deals") or 0), reverse=True)

    payload = {
        "ok": True,
        "source": "IMAA (country narratives)",
        "link": IMAA_COUNTRY_URL,
        "rows": out,
        "note": "Derived by parsing narrative text; best-effort and may miss countries or use mixed currencies.",
        "warnings": [
            "Value is normalized to billions of the stated currency (USD/EUR).",
            "Some country sections may use EUR; cross-country value comparisons are indicative only unless converted.",
        ],
    }

    _set_cached(key, payload, ttl_seconds)
    return {**payload, "cached": False}
