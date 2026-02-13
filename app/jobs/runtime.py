from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import JobDefinition, JobRun, WidgetInsight, WidgetSnapshot
from app.db.session import SessionLocal
from app.web import widget_data
from app.web.imaa import fetch_ma_by_country, fetch_ma_by_industry
from app.web.worldbank import fetch_age_structure_latest, fetch_trade_exim_5y, fetch_wealth_indicators_5y
from app.web.worldpopreview import fetch_disposable_income_latest

ALLOWED_GEOS = ["Global", "India", "Mexico", "Singapore", "Hong Kong"]
GEO_TO_WDI = {
    "Global": "WLD",
    "India": "IND",
    "Mexico": "MEX",
    "Singapore": "SGP",
    "Hong Kong": "HKG",
}

RUNNABLE_STATUSES = {"success", "failed", "skipped"}
JOB_RUN_BY = {"scheduler", "manual", "startup", "api"}
DEFAULT_CRON_EVERY_10_MIN = "*/10 * * * *"
LEGACY_CRON_BY_JOB = {
    "trade_corridors": "0 */6 * * *",
    "trade_exim_5y": "15 2 * * *",
    "wealth_indicators_5y": "30 2 * * *",
    "wealth_disposable_latest": "45 2 * * *",
    "finance_ma_industry": "10 3 * * *",
    "finance_ma_country": "20 3 * * *",
    "cleanup_snapshots": "0 4 * * *",
}

_SCHEDULER: BackgroundScheduler | None = None
_LOCKS: dict[str, threading.Lock] = {}
_SCHED_LOCK = threading.Lock()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "y", "on"}:
            return True
        if v in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _as_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        iv = int(value)
    except Exception:
        return default
    if iv < min_value:
        return min_value
    if iv > max_value:
        return max_value
    return iv


def _as_geo_list(value: Any) -> list[str]:
    if value is None:
        return list(ALLOWED_GEOS)
    items: list[str]
    if isinstance(value, str):
        items = [x.strip() for x in value.split(",") if x.strip()]
    elif isinstance(value, list):
        items = [str(x).strip() for x in value if str(x).strip()]
    else:
        return list(ALLOWED_GEOS)

    canonical_map = {g.lower(): g for g in ALLOWED_GEOS}
    out: list[str] = []
    for raw in items:
        key = raw.lower()
        if key not in canonical_map:
            continue
        geo = canonical_map[key]
        if geo not in out:
            out.append(geo)
    return out or list(ALLOWED_GEOS)


def _parse_json_object(raw: str | None, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if raw is None or raw.strip() == "":
        return fallback or {}
    try:
        data = json.loads(raw)
    except Exception:
        return fallback or {}
    if not isinstance(data, dict):
        return fallback or {}
    return data


def _record_snapshot(
    db: Session,
    *,
    widget_key: str,
    scope: str,
    payload: dict[str, Any],
    source: str,
    is_stale: bool,
    job_run_id: int | None,
    source_updated_at: datetime | None = None,
    source_updated_at_note: str = "",
) -> None:
    db.add(
        WidgetSnapshot(
            widget_key=widget_key,
            scope=scope,
            payload=payload,
            source=source,
            is_stale=is_stale,
            fetched_at=_now_utc(),
            source_updated_at=source_updated_at,
            source_updated_at_note=source_updated_at_note or "",
            job_run_id=job_run_id,
        )
    )


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    name: str
    description: str
    cron_expr: str
    timezone: str
    default_params: dict[str, Any]
    normalize_params: Callable[[dict[str, Any]], dict[str, Any]]
    runner: Callable[[Session, dict[str, Any], int | None], str]


def _normalize_trade_corridors(raw: dict[str, Any]) -> dict[str, Any]:
    return {"force_wci": _as_bool(raw.get("force_wci"), False)}


def _normalize_trade_exim(raw: dict[str, Any]) -> dict[str, Any]:
    end_year = raw.get("end_year")
    if end_year is None:
        normalized_end_year = _now_utc().year - 1
    else:
        normalized_end_year = _as_int(end_year, _now_utc().year - 1, 1960, _now_utc().year)
    return {
        "geo_list": _as_geo_list(raw.get("geo_list")),
        "years": _as_int(raw.get("years"), 5, 2, 20),
        "end_year": normalized_end_year,
        "force": _as_bool(raw.get("force"), False),
    }


def _normalize_wealth_indicators(raw: dict[str, Any]) -> dict[str, Any]:
    end_year = raw.get("end_year")
    if end_year is None:
        normalized_end_year = _now_utc().year - 1
    else:
        normalized_end_year = _as_int(end_year, _now_utc().year - 1, 1960, _now_utc().year)
    return {
        "geo_list": _as_geo_list(raw.get("geo_list")),
        "years": _as_int(raw.get("years"), 5, 2, 20),
        "end_year": normalized_end_year,
        "force": _as_bool(raw.get("force"), False),
    }


def _normalize_wealth_disposable(raw: dict[str, Any]) -> dict[str, Any]:
    return {"force": _as_bool(raw.get("force"), False)}


def _normalize_wealth_age_structure(raw: dict[str, Any]) -> dict[str, Any]:
    end_year = raw.get("end_year")
    if end_year is None:
        normalized_end_year = _now_utc().year - 1
    else:
        normalized_end_year = _as_int(end_year, _now_utc().year - 1, 1960, _now_utc().year)
    return {
        "geo_list": _as_geo_list(raw.get("geo_list")),
        "end_year": normalized_end_year,
        "lookback_years": _as_int(raw.get("lookback_years"), 20, 5, 60),
        "force": _as_bool(raw.get("force"), False),
    }


def _normalize_finance(raw: dict[str, Any]) -> dict[str, Any]:
    return {"force": _as_bool(raw.get("force"), False)}


def _normalize_cleanup(raw: dict[str, Any]) -> dict[str, Any]:
    return {"keep_days": _as_int(raw.get("keep_days"), settings.JOB_RETENTION_DAYS, 1, 365)}


def _run_trade_corridors(db: Session, params: dict[str, Any], job_run_id: int | None) -> str:
    payload = widget_data.trade_corridors_mvp(force_wci=params["force_wci"])
    wci_error = bool((payload.get("wci") or {}).get("error"))

    # MVP stub has no real source time; keep NULL.
    src_at = None
    src_note = "MVP stub; source time not applicable"

    _record_snapshot(
        db,
        widget_key="trade_corridors",
        scope="global",
        payload=payload,
        source=payload.get("source", ""),
        is_stale=wci_error,
        job_run_id=job_run_id,
        source_updated_at=src_at,
        source_updated_at_note=src_note,
    )
    return "trade corridors snapshot saved"


def _infer_annual_source_updated_at(period: str | None) -> tuple[datetime | None, str]:
    """Infer a reasonable 'source updated' time for annual series.

    If the source only provides a year (e.g. '2024'), we infer it as year-end (Dec 31) in UTC.
    """
    if not period:
        return None, "source does not declare an as-of date"
    s = str(period).strip()
    if not s.isdigit():
        return None, f"unrecognized period format: {s}"
    y = int(s)
    if y < 1900 or y > 2200:
        return None, f"out-of-range year: {y}"
    return datetime(y, 12, 31, tzinfo=timezone.utc), "inferred from annual period year-end"


def _run_trade_exim(db: Session, params: dict[str, Any], job_run_id: int | None) -> str:
    count = 0
    failed = 0
    for geo in params["geo_list"]:
        code = GEO_TO_WDI.get(geo)
        if not code:
            continue
        payload = fetch_trade_exim_5y(
            code,
            end_year=params["end_year"],
            years=params["years"],
            force=params["force"],
        )
        payload["geo"] = geo

        # choose the latest non-null period from the merged series
        latest_period = None
        for row in reversed(payload.get("series") or []):
            if row.get("export_usd") is not None or row.get("import_usd") is not None:
                latest_period = row.get("period")
                break
        src_at, src_note = _infer_annual_source_updated_at(latest_period)

        stale = not bool(payload.get("ok"))
        if stale:
            failed += 1
        _record_snapshot(
            db,
            widget_key="trade_exim_5y",
            scope=geo,
            payload=payload,
            source=payload.get("source", ""),
            is_stale=stale,
            job_run_id=job_run_id,
            source_updated_at=src_at,
            source_updated_at_note=src_note,
        )
        count += 1
    return f"trade exim snapshots saved: {count}, stale: {failed}"


def _run_wealth_indicators(db: Session, params: dict[str, Any], job_run_id: int | None) -> str:
    count = 0
    failed = 0
    for geo in params["geo_list"]:
        code = GEO_TO_WDI.get(geo)
        if not code:
            continue
        payload = fetch_wealth_indicators_5y(
            code,
            end_year=params["end_year"],
            years=params["years"],
            force=params["force"],
        )
        payload["geo"] = geo

        latest_period = None
        for row in reversed(payload.get("series") or []):
            if row.get("gdp_per_capita_usd") is not None or row.get("consumption_expenditure_usd") is not None:
                latest_period = row.get("period")
                break
        src_at, src_note = _infer_annual_source_updated_at(latest_period)

        stale = not bool(payload.get("ok"))
        if stale:
            failed += 1
        _record_snapshot(
            db,
            widget_key="wealth_indicators_5y",
            scope=geo,
            payload=payload,
            source=payload.get("source", ""),
            is_stale=stale,
            job_run_id=job_run_id,
            source_updated_at=src_at,
            source_updated_at_note=src_note,
        )
        count += 1
    return f"wealth indicator snapshots saved: {count}, stale: {failed}"


def _run_wealth_disposable(db: Session, params: dict[str, Any], job_run_id: int | None) -> str:
    payload = fetch_disposable_income_latest(force=params["force"])

    # WPR does not reliably declare an update timestamp in the HTML table; keep NULL and explain.
    src_at = None
    src_note = "source update time not declared by WPR page; kept NULL"

    stale = not bool(payload.get("ok"))
    _record_snapshot(
        db,
        widget_key="wealth_disposable_latest",
        scope="global",
        payload=payload,
        source=payload.get("source", ""),
        is_stale=stale,
        job_run_id=job_run_id,
        source_updated_at=src_at,
        source_updated_at_note=src_note,
    )
    return "wealth disposable snapshot saved"


def _run_wealth_age_structure(db: Session, params: dict[str, Any], job_run_id: int | None) -> str:
    count = 0
    failed = 0
    for geo in params["geo_list"]:
        code = GEO_TO_WDI.get(geo)
        if not code:
            continue
        payload = fetch_age_structure_latest(
            code,
            end_year=params["end_year"],
            lookback_years=params["lookback_years"],
            force=params["force"],
        )
        payload["geo"] = geo

        src_at, src_note = _infer_annual_source_updated_at(payload.get("period"))

        stale = not bool(payload.get("ok"))
        if stale:
            failed += 1
        _record_snapshot(
            db,
            widget_key="wealth_age_structure_latest",
            scope=geo,
            payload=payload,
            source=payload.get("source", ""),
            is_stale=stale,
            job_run_id=job_run_id,
            source_updated_at=src_at,
            source_updated_at_note=src_note,
        )
        count += 1
    return f"wealth age-structure snapshots saved: {count}, stale: {failed}"


def _run_finance_industry(db: Session, params: dict[str, Any], job_run_id: int | None) -> str:
    payload = fetch_ma_by_industry(force=params["force"])

    # IMAA public table does not clearly expose a last-updated timestamp; keep NULL.
    src_at = None
    src_note = "source update time not declared by IMAA page; kept NULL"

    stale = not bool(payload.get("ok"))
    _record_snapshot(
        db,
        widget_key="finance_ma_industry",
        scope="global",
        payload=payload,
        source=payload.get("source", ""),
        is_stale=stale,
        job_run_id=job_run_id,
        source_updated_at=src_at,
        source_updated_at_note=src_note,
    )
    return "finance industry snapshot saved"


def _run_finance_country(db: Session, params: dict[str, Any], job_run_id: int | None) -> str:
    payload = fetch_ma_by_country(force=params["force"])

    src_at = None
    src_note = "source update time not declared by IMAA page; kept NULL"

    stale = not bool(payload.get("ok"))
    _record_snapshot(
        db,
        widget_key="finance_ma_country",
        scope="global",
        payload=payload,
        source=payload.get("source", ""),
        is_stale=stale,
        job_run_id=job_run_id,
        source_updated_at=src_at,
        source_updated_at_note=src_note,
    )
    return "finance country snapshot saved"


def _run_cleanup_snapshots(db: Session, params: dict[str, Any], job_run_id: int | None) -> str:
    del job_run_id
    cutoff = _now_utc() - timedelta(days=params["keep_days"])
    snapshots_deleted = (
        db.query(WidgetSnapshot).filter(WidgetSnapshot.fetched_at < cutoff).delete(synchronize_session=False)
    )
    runs_deleted = db.query(JobRun).filter(JobRun.started_at < cutoff).delete(synchronize_session=False)
    return f"cleanup done: snapshots={snapshots_deleted}, runs={runs_deleted}, keep_days={params['keep_days']}"


def _save_insight(
    db: Session,
    *,
    card_key: str,
    tab_key: str,
    scope: str,
    lang: str,
    content: str,
    reference_list: list[dict[str, Any]] | None,
    source_updated_at: datetime | None,
    generated_by: str,
    job_run_id: int | None,
) -> None:
    db.add(
        WidgetInsight(
            card_key=card_key,
            tab_key=tab_key,
            scope=scope,
            lang=lang,
            content=content,
            reference_list=reference_list or [],
            source_updated_at=source_updated_at,
            generated_by=generated_by,
            job_run_id=job_run_id,
        )
    )


def _run_generate_homepage_insights(db: Session, params: dict[str, Any], job_run_id: int | None) -> str:
    """Generate Insights for homepage cards/tabs.

    This job must not run in web requests; it reads latest widget snapshots and writes insights to DB.
    """
    del params

    # Trade Flow
    trade = get_latest_snapshot(db, "trade_corridors", "global")
    if trade and isinstance(trade.payload, dict):
        # corridors
        _save_insight(
            db,
            card_key="trade_flow",
            tab_key="corridors",
            scope="global",
            lang="en",
            content="Top corridors are a directional signal; compare value vs volume leaders to spot reroutes or mix changes.",
            reference_list=[],
            source_updated_at=trade.source_updated_at,
            generated_by="job",
            job_run_id=job_run_id,
        )
        # wci
        wci = (trade.payload.get("wci") or {}) if isinstance(trade.payload.get("wci"), dict) else {}
        wci_val = wci.get("value_usd_per_40ft")
        if wci_val is not None:
            wci_text = f"Freight costs (WCI) are {wci_val} USD/40ft in the latest scrape; interpret as shipping-cost pressure rather than customs trade value."
        else:
            wci_text = "Freight (WCI) is unavailable in the latest run; check Drewry page structure and scraping caveats."
        _save_insight(
            db,
            card_key="trade_flow",
            tab_key="wci",
            scope="global",
            lang="en",
            content=wci_text,
            reference_list=[],
            source_updated_at=trade.source_updated_at,
            generated_by="job",
            job_run_id=job_run_id,
        )
        _save_insight(
            db,
            card_key="trade_flow",
            tab_key="portwatch",
            scope="global",
            lang="en",
            content="PortWatch signals are nowcast/proxy indicators; always present them with explicit caveats (not final customs statistics).",
            reference_list=[],
            source_updated_at=trade.source_updated_at,
            generated_by="job",
            job_run_id=job_run_id,
        )

    # Trade Exim insight per geo
    for geo in ALLOWED_GEOS:
        exim = get_latest_snapshot(db, "trade_exim_5y", geo)
        if not exim or not isinstance(exim.payload, dict):
            continue
        s = (exim.payload.get("series") or [])
        s = [r for r in s if isinstance(r, dict) and r.get("export_usd") is not None and r.get("import_usd") is not None]
        if len(s) >= 1:
            last = s[-1]
            bal = last.get("balance_usd")
            if bal is None:
                txt = "Latest export/import values are present but balance could not be computed (missing data)."
            else:
                txt = f"Latest year shows a {'surplus' if bal >= 0 else 'deficit'}; monitor whether exports and imports diverge as a macro signal."
        else:
            txt = "Not enough data points to compute a meaningful export/import insight yet."
        _save_insight(
            db,
            card_key="trade_flow",
            tab_key="exim",
            scope=geo,
            lang="en",
            content=txt,
            reference_list=[],
            source_updated_at=exim.source_updated_at,
            generated_by="job",
            job_run_id=job_run_id,
        )
        _save_insight(
            db,
            card_key="trade_flow",
            tab_key="balance",
            scope=geo,
            lang="en",
            content="Trade balance is computed as export minus import; treat it as an identity check and watch for large year-over-year moves.",
            reference_list=[],
            source_updated_at=exim.source_updated_at,
            generated_by="job",
            job_run_id=job_run_id,
        )

    # Wealth
    for geo in ALLOWED_GEOS:
        w = get_latest_snapshot(db, "wealth_indicators_5y", geo)
        if w:
            _save_insight(
                db,
                card_key="wealth",
                tab_key="gdp_pc",
                scope=geo,
                lang="en",
                content="GDP per capita (nominal USD) can be noisy due to FX; interpret trends with caveats and consider constant-price alternatives if needed.",
                reference_list=[],
                source_updated_at=w.source_updated_at,
                generated_by="job",
                job_run_id=job_run_id,
            )
            _save_insight(
                db,
                card_key="wealth",
                tab_key="cons",
                scope=geo,
                lang="en",
                content="Household consumption helps cross-check domestic-demand momentum; combine with trade indicators for a fuller demand picture.",
                reference_list=[],
                source_updated_at=w.source_updated_at,
                generated_by="job",
                job_run_id=job_run_id,
            )

        age = get_latest_snapshot(db, "wealth_age_structure_latest", geo)
        if age and isinstance(age.payload, dict):
            rows = age.payload.get("rows") or []
            work = None
            for r in rows:
                if isinstance(r, dict) and r.get("label") == "15-64":
                    work = r.get("pct")
            if work is not None:
                txt = f"Working-age share (15–64) is {float(work):.1f}% in the latest year; demographic structure affects labor supply and demand composition."
            else:
                txt = "Age structure snapshot is present; use it as demographic context (not income-by-age)."
            _save_insight(
                db,
                card_key="wealth",
                tab_key="age",
                scope=geo,
                lang="en",
                content=txt,
                reference_list=[],
                source_updated_at=age.source_updated_at,
                generated_by="job",
                job_run_id=job_run_id,
            )

    disp = get_latest_snapshot(db, "wealth_disposable_latest", "global")
    if disp:
        _save_insight(
            db,
            card_key="wealth",
            tab_key="disp_pc",
            scope="global",
            lang="en",
            content="Disposable income is best-effort: primary WPR scrape + World Bank proxy fallback; treat as an indicative latest-point snapshot.",
            reference_list=[],
            source_updated_at=disp.source_updated_at,
            generated_by="job",
            job_run_id=job_run_id,
        )
        _save_insight(
            db,
            card_key="wealth",
            tab_key="disp_hh",
            scope="global",
            lang="en",
            content="Per-household disposable values may be missing for many geos; consider OECD SDMX for household-level measures where coverage exists.",
            reference_list=[],
            source_updated_at=disp.source_updated_at,
            generated_by="job",
            job_run_id=job_run_id,
        )

    # Finance
    fin_i = get_latest_snapshot(db, "finance_ma_industry", "global")
    if fin_i:
        _save_insight(
            db,
            card_key="finance",
            tab_key="industry",
            scope="global",
            lang="en",
            content="Industry rankings reflect disclosed-deal reporting; treat as a directional view of deal activity concentration.",
            reference_list=[],
            source_updated_at=fin_i.source_updated_at,
            generated_by="job",
            job_run_id=job_run_id,
        )

    fin_c = get_latest_snapshot(db, "finance_ma_country", "global")
    if fin_c:
        _save_insight(
            db,
            card_key="finance",
            tab_key="country",
            scope="global",
            lang="en",
            content="Country narratives may mix currencies (USD/EUR). Use normalized currency conversion if you need strict cross-country value comparisons.",
            reference_list=[],
            source_updated_at=fin_c.source_updated_at,
            generated_by="job",
            job_run_id=job_run_id,
        )

    return "homepage insights saved"


JOB_SPECS: dict[str, JobSpec] = {
    "generate_homepage_insights": JobSpec(
        job_id="generate_homepage_insights",
        name="Generate Homepage Insights",
        description="Generate Insights text for homepage cards/tabs and save to DB.",
        cron_expr=DEFAULT_CRON_EVERY_10_MIN,
        timezone=settings.TZ,
        default_params={},
        normalize_params=lambda raw: {},
        runner=_run_generate_homepage_insights,
    ),
    "trade_corridors": JobSpec(
        job_id="trade_corridors",
        name="Trade Corridors Snapshot",
        description="Refresh trade corridors summary (includes WCI extraction).",
        cron_expr=DEFAULT_CRON_EVERY_10_MIN,
        timezone=settings.TZ,
        default_params={"force_wci": False},
        normalize_params=_normalize_trade_corridors,
        runner=_run_trade_corridors,
    ),
    "trade_exim_5y": JobSpec(
        job_id="trade_exim_5y",
        name="Trade Exim 5Y by Geo",
        description="Refresh export/import series from World Bank WDI for configured geos.",
        cron_expr=DEFAULT_CRON_EVERY_10_MIN,
        timezone=settings.TZ,
        default_params={"geo_list": ALLOWED_GEOS, "years": 5, "end_year": None, "force": False},
        normalize_params=_normalize_trade_exim,
        runner=_run_trade_exim,
    ),
    "wealth_indicators_5y": JobSpec(
        job_id="wealth_indicators_5y",
        name="Wealth Indicators 5Y by Geo",
        description="Refresh GDP per capita and consumption 5Y series for configured geos.",
        cron_expr=DEFAULT_CRON_EVERY_10_MIN,
        timezone=settings.TZ,
        default_params={"geo_list": ALLOWED_GEOS, "years": 5, "end_year": None, "force": False},
        normalize_params=_normalize_wealth_indicators,
        runner=_run_wealth_indicators,
    ),
    "wealth_disposable_latest": JobSpec(
        job_id="wealth_disposable_latest",
        name="Disposable Income Latest",
        description="Refresh latest disposable-income-like snapshot from WPR with WB fallback.",
        cron_expr=DEFAULT_CRON_EVERY_10_MIN,
        timezone=settings.TZ,
        default_params={"force": False},
        normalize_params=_normalize_wealth_disposable,
        runner=_run_wealth_disposable,
    ),
    "wealth_age_structure_latest": JobSpec(
        job_id="wealth_age_structure_latest",
        name="Age Structure Latest",
        description="Refresh latest age-structure (% population) snapshot from World Bank WDI.",
        cron_expr=DEFAULT_CRON_EVERY_10_MIN,
        timezone=settings.TZ,
        default_params={"geo_list": ALLOWED_GEOS, "end_year": None, "lookback_years": 20, "force": False},
        normalize_params=_normalize_wealth_age_structure,
        runner=_run_wealth_age_structure,
    ),
    "finance_ma_industry": JobSpec(
        job_id="finance_ma_industry",
        name="Finance M&A by Industry",
        description="Refresh IMAA industry ranking snapshot.",
        cron_expr=DEFAULT_CRON_EVERY_10_MIN,
        timezone=settings.TZ,
        default_params={"force": False},
        normalize_params=_normalize_finance,
        runner=_run_finance_industry,
    ),
    "finance_ma_country": JobSpec(
        job_id="finance_ma_country",
        name="Finance M&A by Country",
        description="Refresh IMAA country snapshot.",
        cron_expr=DEFAULT_CRON_EVERY_10_MIN,
        timezone=settings.TZ,
        default_params={"force": False},
        normalize_params=_normalize_finance,
        runner=_run_finance_country,
    ),
    "cleanup_snapshots": JobSpec(
        job_id="cleanup_snapshots",
        name="Cleanup Snapshots",
        description="Delete snapshot and run logs older than configured retention days.",
        cron_expr=DEFAULT_CRON_EVERY_10_MIN,
        timezone=settings.TZ,
        default_params={"keep_days": settings.JOB_RETENTION_DAYS},
        normalize_params=_normalize_cleanup,
        runner=_run_cleanup_snapshots,
    ),
}


def _seed_job_definitions(db: Session) -> None:
    for spec in JOB_SPECS.values():
        row = db.get(JobDefinition, spec.job_id)
        if row is None:
            db.add(
                JobDefinition(
                    job_id=spec.job_id,
                    name=spec.name,
                    description=spec.description,
                    cron_expr=spec.cron_expr,
                    timezone=spec.timezone,
                    enabled=True,
                    default_params=spec.default_params,
                )
            )
            continue

        # Enforce every-10-minute cadence (product requirement).
        # If you later need per-job cadence, relax this to only migrate legacy schedules.
        if row.cron_expr != spec.cron_expr:
            row.cron_expr = spec.cron_expr
    db.commit()


def _get_lock(job_id: str) -> threading.Lock:
    if job_id not in _LOCKS:
        _LOCKS[job_id] = threading.Lock()
    return _LOCKS[job_id]


def run_job_now(job_id: str, params_override: dict[str, Any] | None = None, triggered_by: str = "manual") -> dict[str, Any]:
    if job_id not in JOB_SPECS:
        return {"ok": False, "job_id": job_id, "status": "failed", "error": "unknown job"}

    if not settings.JOBS_ENABLED:
        return {
            "ok": False,
            "job_id": job_id,
            "status": "skipped",
            "message": "jobs are disabled by JOBS_ENABLED=false",
        }

    if triggered_by not in JOB_RUN_BY:
        triggered_by = "manual"

    lock = _get_lock(job_id)
    if not lock.acquire(blocking=False):
        return {"ok": False, "job_id": job_id, "status": "skipped", "message": "job is already running"}

    started = _now_utc()
    run_id: int | None = None
    status = "failed"
    error = None
    message = ""

    try:
        with SessionLocal() as db:
            _seed_job_definitions(db)
            spec = JOB_SPECS[job_id]
            job_def = db.get(JobDefinition, job_id)
            if job_def is None:
                raise RuntimeError(f"job definition not found: {job_id}")

            raw = dict(job_def.default_params or {})
            if params_override:
                raw.update(params_override)
            params = spec.normalize_params(raw)

            run = JobRun(
                job_id=job_id,
                status="running",
                triggered_by=triggered_by,
                params=params,
                started_at=started,
            )
            db.add(run)
            db.flush()
            run_id = int(run.id)

            job_def.last_scheduled_at = started
            db.flush()

            try:
                message = spec.runner(db, params, run_id)
                status = "success"
                job_def.last_success_at = _now_utc()
            except Exception as exc:  # noqa: BLE001
                status = "failed"
                error = str(exc)
                message = "job failed"

            finished = _now_utc()
            run.status = status
            run.message = message
            run.error = error
            run.finished_at = finished
            run.duration_ms = int((finished - started).total_seconds() * 1000)
            db.commit()
    finally:
        lock.release()

    return {
        "ok": status == "success",
        "job_id": job_id,
        "run_id": run_id,
        "status": status,
        "message": message,
        "error": error,
    }


def init_scheduler() -> None:
    global _SCHEDULER
    with _SCHED_LOCK:
        if _SCHEDULER is not None:
            return
        with SessionLocal() as db:
            _seed_job_definitions(db)

        if not settings.JOBS_ENABLED:
            return

        scheduler = BackgroundScheduler(timezone=settings.TZ)
        scheduler.start()
        _SCHEDULER = scheduler
        reload_scheduler_jobs()
        _schedule_startup_warmup()


def shutdown_scheduler() -> None:
    global _SCHEDULER
    with _SCHED_LOCK:
        if _SCHEDULER is None:
            return
        _SCHEDULER.shutdown(wait=False)
        _SCHEDULER = None


def reload_scheduler_jobs() -> None:
    scheduler = _SCHEDULER
    if scheduler is None:
        return

    scheduler.remove_all_jobs()

    with SessionLocal() as db:
        rows = (
            db.query(JobDefinition)
            .order_by(JobDefinition.job_id.asc())
            .all()
        )

    for row in rows:
        if not row.enabled:
            continue
        try:
            trigger = CronTrigger.from_crontab(row.cron_expr, timezone=row.timezone or settings.TZ)
        except Exception:
            continue
        scheduler.add_job(
            run_job_now,
            trigger=trigger,
            id=f"job:{row.job_id}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=120,
            args=[row.job_id, None, "scheduler"],
        )


def _schedule_startup_warmup() -> None:
    scheduler = _SCHEDULER
    if scheduler is None or not settings.JOB_WARMUP_ON_START:
        return
    with SessionLocal() as db:
        has_any = db.query(func.count(WidgetSnapshot.id)).scalar() or 0
    if has_any:
        return

    delay_seconds = 2
    for job_id in JOB_SPECS:
        if job_id == "cleanup_snapshots":
            continue
        scheduler.add_job(
            run_job_now,
            id=f"warmup:{job_id}",
            replace_existing=True,
            next_run_time=_now_utc() + timedelta(seconds=delay_seconds),
            args=[job_id, None, "startup"],
        )
        delay_seconds += 2


def get_next_run_time(job_id: str) -> datetime | None:
    scheduler = _SCHEDULER
    if scheduler is None:
        return None
    job = scheduler.get_job(f"job:{job_id}")
    if job is None:
        return None
    return job.next_run_time


def list_job_definitions(db: Session) -> list[JobDefinition]:
    return db.query(JobDefinition).order_by(JobDefinition.job_id.asc()).all()


def list_recent_job_runs(db: Session, limit: int = 100) -> list[JobRun]:
    return (
        db.query(JobRun)
        .order_by(desc(JobRun.started_at))
        .limit(limit)
        .all()
    )


def update_job_definition(
    db: Session,
    *,
    job_id: str,
    cron_expr: str,
    timezone_name: str,
    enabled: bool,
    default_params: dict[str, Any],
) -> tuple[bool, str]:
    row = db.get(JobDefinition, job_id)
    if row is None:
        return False, "job not found"
    if job_id not in JOB_SPECS:
        return False, "unknown job"

    cron_expr = (cron_expr or "").strip()
    timezone_name = (timezone_name or "").strip() or settings.TZ
    try:
        CronTrigger.from_crontab(cron_expr, timezone=timezone_name)
    except Exception as exc:  # noqa: BLE001
        return False, f"invalid cron/timezone: {exc}"

    spec = JOB_SPECS[job_id]
    normalized = spec.normalize_params(default_params or {})
    row.cron_expr = cron_expr
    row.timezone = timezone_name
    row.enabled = enabled
    row.default_params = normalized
    db.commit()
    reload_scheduler_jobs()
    return True, "updated"


def get_latest_snapshot(db: Session, widget_key: str, scope: str = "global") -> WidgetSnapshot | None:
    return (
        db.query(WidgetSnapshot)
        .filter(WidgetSnapshot.widget_key == widget_key, WidgetSnapshot.scope == scope)
        .order_by(desc(WidgetSnapshot.fetched_at))
        .first()
    )


def get_latest_snapshots_by_key(db: Session, widget_key: str) -> dict[str, WidgetSnapshot]:
    rows = (
        db.query(WidgetSnapshot)
        .filter(WidgetSnapshot.widget_key == widget_key)
        .order_by(WidgetSnapshot.scope.asc(), desc(WidgetSnapshot.fetched_at))
        .all()
    )
    out: dict[str, WidgetSnapshot] = {}
    for row in rows:
        if row.scope not in out:
            out[row.scope] = row
    return out


def parse_params_json(raw: str | None, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    return _parse_json_object(raw, fallback=fallback)
