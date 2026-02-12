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

    rows: List[Dict[str, Any]] = []

    # Extract rows from the first HTML table.
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.IGNORECASE | re.DOTALL):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.IGNORECASE | re.DOTALL)
        if len(tds) < 4:
            continue

        rank_s = _strip_tags(tds[0])
        if not rank_s.isdigit():
            continue

        rank = int(rank_s)
        industry = _strip_tags(tds[1])

        deals_s = _strip_tags(tds[2]).replace("'", "").replace("’", "").replace(",", "")
        # Sometimes deals cell contains a <br/> with extra notes; take first token.
        deals_s = deals_s.split()[0] if deals_s else ""
        try:
            deals = int(deals_s)
        except Exception:
            deals = None

        val_s = _strip_tags(tds[3]).replace(",", "")
        val_s = val_s.split()[0] if val_s else ""
        try:
            value_usd_bil = float(val_s)
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

    The IMAA country page is narrative by country. We parse each "M&A <Country>" section and
    extract the first "Since YYYY ... deals ... value ..." sentence.
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

    # Preserve some structure by inserting markers for headings.
    # Elementor headings appear as <h2> / <h3> with text like "M&A Australia".
    headings = list(re.finditer(r"<h[23][^>]*>\s*(M&amp;A|M&A)\s+([^<]+)</h[23]>", html, re.IGNORECASE))

    rows: List[Dict[str, Any]] = []

    for idx, hm in enumerate(headings):
        country = _strip_tags(hm.group(2))
        start = hm.end()
        end = headings[idx + 1].start() if idx + 1 < len(headings) else start + 8000
        chunk = _strip_tags(html[start:end])

        # Look for sentence with deals + value in USD/EUR.
        m = re.search(
            r"Since\s+(\d{4}).{0,120}?([0-9]{1,3}(?:[,'’][0-9]{3})+|\d{1,7}).{0,80}?deal.{0,160}?(?:value|valued?).{0,120}?([0-9]+(?:\.[0-9]+)?)\s*(trillion|billion|bil\.|million)?\s*(USD|EUR)",
            chunk,
            re.IGNORECASE,
        )
        if not m:
            continue

        since_year = int(m.group(1))
        deals_s = m.group(2).replace(",", "").replace("'", "").replace("’", "")
        try:
            deals = int(deals_s)
        except Exception:
            continue

        val = float(m.group(3))
        scale = (m.group(4) or "").lower()
        ccy = (m.group(5) or "").upper()

        mult = 1.0
        if "trillion" in scale:
            mult = 1_000.0
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

    rows.sort(key=lambda r: (r.get("deals") or 0), reverse=True)

    payload = {
        "ok": True,
        "source": "IMAA (country narratives)",
        "link": IMAA_COUNTRY_URL,
        "rows": rows,
        "note": "Parsed from country section narratives (best-effort).",
        "warnings": [
            "Value is normalized to billions of the stated currency (USD/EUR).",
            "Some entries use EUR; cross-country value comparisons are indicative only unless converted.",
        ],
    }

    _set_cached(key, payload, ttl_seconds)
    return {**payload, "cached": False}
