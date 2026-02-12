from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode
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


def fetch_wdi_indicator(
    country: str,
    indicator: str,
    *,
    date: str,
    ttl_seconds: int = 24 * 60 * 60,
    force: bool = False,
) -> Dict[str, Any]:
    """Fetch World Bank WDI time series.

    country: e.g. 'WLD', 'IND', 'MEX', 'SGP', 'HKG'
    indicator: e.g. 'NE.EXP.GNFS.CD'
    date: '2020:2025'
    """

    key = f"wdi:{country}:{indicator}:{date}"
    cached = None if force else _get_cached(key)
    if cached:
        return {**cached, "cached": True}

    params = {
        "format": "json",
        "per_page": 200,
        "date": date,
    }
    url = f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "GTA dashboard"})

    try:
        with urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        j = json.loads(raw)
    except Exception as e:
        payload = {
            "ok": False,
            "country": country,
            "indicator": indicator,
            "date": date,
            "series": [],
            "error": str(e),
        }
        _set_cached(key, payload, ttl_seconds=ttl_seconds)
        return {**payload, "cached": False}

    series = []
    # expected: [meta, data[]]
    if isinstance(j, list) and len(j) >= 2 and isinstance(j[1], list):
        for row in j[1]:
            if not isinstance(row, dict):
                continue
            yr = row.get("date")
            val = row.get("value")
            if yr is None:
                continue
            # keep None values; front-end can handle gaps
            series.append({"period": str(yr), "value": val})

    # sort ascending by year
    series.sort(key=lambda x: x["period"])

    payload = {
        "ok": True,
        "country": country,
        "indicator": indicator,
        "date": date,
        "series": series,
    }
    _set_cached(key, payload, ttl_seconds=ttl_seconds)
    return {**payload, "cached": False}


def fetch_trade_exim_5y(
    country: str,
    *,
    end_year: int,
    years: int = 5,
    ttl_seconds: int = 24 * 60 * 60,
    force: bool = False,
) -> Dict[str, Any]:
    start_year = end_year - years + 1
    date = f"{start_year}:{end_year}"

    exp = fetch_wdi_indicator(
        country,
        "NE.EXP.GNFS.CD",
        date=date,
        ttl_seconds=ttl_seconds,
        force=force,
    )
    imp = fetch_wdi_indicator(
        country,
        "NE.IMP.GNFS.CD",
        date=date,
        ttl_seconds=ttl_seconds,
        force=force,
    )

    # merge by period
    periods = sorted({p["period"] for p in exp.get("series", [])} | {p["period"] for p in imp.get("series", [])})
    exp_map = {p["period"]: p.get("value") for p in exp.get("series", [])}
    imp_map = {p["period"]: p.get("value") for p in imp.get("series", [])}

    series = []
    for per in periods:
        e = exp_map.get(per)
        i = imp_map.get(per)
        bal = None
        if e is not None and i is not None:
            bal = e - i
        series.append({"period": per, "export_usd": e, "import_usd": i, "balance_usd": bal})

    return {
        "source": "World Bank WDI",
        "frequency": "annual",
        "country": country,
        "date": date,
        "ok": bool(exp.get("ok")) and bool(imp.get("ok")),
        "errors": [x for x in [exp.get("error"), imp.get("error")] if x],
        "series": series,
    }
