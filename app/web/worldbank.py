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


def fetch_wealth_indicators_5y(
    country: str,
    *,
    end_year: int,
    years: int = 5,
    ttl_seconds: int = 24 * 60 * 60,
    force: bool = False,
) -> Dict[str, Any]:
    """GDP per capita + household consumption expenditure (nominal USD), annual fallback."""

    start_year = end_year - years + 1
    date = f"{start_year}:{end_year}"

    gdp_pc = fetch_wdi_indicator(
        country,
        "NY.GDP.PCAP.CD",
        date=date,
        ttl_seconds=ttl_seconds,
        force=force,
    )
    cons = fetch_wdi_indicator(
        country,
        "NE.CON.PRVT.CD",
        date=date,
        ttl_seconds=ttl_seconds,
        force=force,
    )

    periods = sorted({p["period"] for p in gdp_pc.get("series", [])} | {p["period"] for p in cons.get("series", [])})
    gdp_map = {p["period"]: p.get("value") for p in gdp_pc.get("series", [])}
    cons_map = {p["period"]: p.get("value") for p in cons.get("series", [])}

    series = []
    for per in periods:
        series.append(
            {
                "period": per,
                "gdp_per_capita_usd": gdp_map.get(per),
                "consumption_expenditure_usd": cons_map.get(per),
            }
        )

    return {
        "source": "World Bank WDI",
        "frequency": "annual",
        "country": country,
        "date": date,
        "ok": bool(gdp_pc.get("ok")) and bool(cons.get("ok")),
        "errors": [x for x in [gdp_pc.get("error"), cons.get("error")] if x],
        "series": series,
        "definitions": {
            "gdp_per_capita": "NY.GDP.PCAP.CD (current US$)",
            "consumption_expenditure": "NE.CON.PRVT.CD (current US$)",
        },
    }


def fetch_age_structure_latest(
    country: str,
    *,
    end_year: int,
    lookback_years: int = 20,
    ttl_seconds: int = 24 * 60 * 60,
    force: bool = False,
) -> Dict[str, Any]:
    """Age structure (% of total population), latest non-null point.

    Indicators:
    - SP.POP.0014.TO.ZS  (0-14)
    - SP.POP.1564.TO.ZS  (15-64)
    - SP.POP.65UP.TO.ZS  (65+)
    """

    start_year = max(1960, end_year - lookback_years + 1)
    date = f"{start_year}:{end_year}"

    s0014 = fetch_wdi_indicator(country, "SP.POP.0014.TO.ZS", date=date, ttl_seconds=ttl_seconds, force=force)
    s1564 = fetch_wdi_indicator(country, "SP.POP.1564.TO.ZS", date=date, ttl_seconds=ttl_seconds, force=force)
    s65up = fetch_wdi_indicator(country, "SP.POP.65UP.TO.ZS", date=date, ttl_seconds=ttl_seconds, force=force)

    def latest_non_null(series):
        for row in reversed(series or []):
            v = row.get("value")
            if v is not None:
                return row.get("period"), float(v)
        return None, None

    p1, v1 = latest_non_null(s0014.get("series"))
    p2, v2 = latest_non_null(s1564.get("series"))
    p3, v3 = latest_non_null(s65up.get("series"))

    # choose a period if they differ: prefer the minimum common/latest available
    periods = [p for p in [p1, p2, p3] if p]
    period = max(periods) if periods else None

    ok = bool(s0014.get("ok")) and bool(s1564.get("ok")) and bool(s65up.get("ok")) and (v1 is not None and v2 is not None and v3 is not None)

    rows = []
    if v1 is not None:
        rows.append({"label": "0-14", "pct": v1})
    if v2 is not None:
        rows.append({"label": "15-64", "pct": v2})
    if v3 is not None:
        rows.append({"label": "65+", "pct": v3})

    return {
        "source": "World Bank WDI",
        "frequency": "annual",
        "country": country,
        "date": date,
        "period": period,
        "ok": ok,
        "errors": [x for x in [s0014.get("error"), s1564.get("error"), s65up.get("error")] if x],
        "rows": rows,
        "definitions": {
            "0_14": "SP.POP.0014.TO.ZS (% of total population)",
            "15_64": "SP.POP.1564.TO.ZS (% of total population)",
            "65_up": "SP.POP.65UP.TO.ZS (% of total population)",
        },
    }
