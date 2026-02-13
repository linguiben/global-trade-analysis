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
ALLOWED_INSIGHT_CARD_KEYS = {"trade_flow", "wealth", "finance"}
ALLOWED_INSIGHT_TAB_KEYS = {
    "corridors",
    "wci",
    "portwatch",
    "exim",
    "balance",
    "gdp_pc",
    "cons",
    "age",
    "disp_pc",
    "disp_hh",
    "industry",
    "country",
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


def _canonical_scope(value: Any) -> str | None:
    s = str(value or "").strip()
    if not s:
        return None
    if s.lower() == "global":
        return "global"
    canonical_map = {g.lower(): g for g in ALLOWED_GEOS}
    return canonical_map.get(s.lower())


def _normalize_scope_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        items = value
    else:
        items = [value]
    out: list[str] = []
    for item in items:
        scope = _canonical_scope(item)
        if scope and scope not in out:
            out.append(scope)
    return out


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


def _normalize_generate_homepage_insights(raw: dict[str, Any]) -> dict[str, Any]:
    card_key = str(raw.get("card_key") or "").strip()
    if card_key not in ALLOWED_INSIGHT_CARD_KEYS:
        card_key = ""

    tab_key = str(raw.get("tab_key") or raw.get("type") or "").strip()
    if tab_key not in ALLOWED_INSIGHT_TAB_KEYS:
        tab_key = ""

    lang = str(raw.get("lang") or "en").strip().lower() or "en"

    return {
        "lang": lang,
        "geo_list": _as_geo_list(raw.get("geo_list")),
        "scope": _normalize_scope_list(raw.get("scope")),
        "card_key": card_key,
        "tab_key": tab_key,
        "force_regen": _as_bool(raw.get("force_regen"), False),
        "force_all": _as_bool(raw.get("force_all"), False),
    }


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


from app.jobs.insights_llm import digest_for_inputs, generate_insight_with_llm
from app.jobs.public_context import get_or_refresh_context, to_prompt_block


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
    job_run_id: int | None,
    data_digest: str,
    input_snapshot_keys: list[dict[str, Any]],
    llm_provider: str = "",
    llm_model: str = "",
    llm_prompt: str = "",
    llm_error: str = "",
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
            data_digest=data_digest,
            input_snapshot_keys=input_snapshot_keys or [],
            llm_provider=llm_provider or "",
            llm_model=llm_model or "",
            llm_prompt=llm_prompt or "",
            llm_error=llm_error or "",
            generated_by="llm",
            job_run_id=job_run_id,
        )
    )


def _latest_trade_year_row(exim_payload: dict[str, Any]) -> dict[str, Any] | None:
    series = exim_payload.get("series")
    if not isinstance(series, list):
        return None
    for row in reversed(series):
        if not isinstance(row, dict):
            continue
        if row.get("export_usd") is None and row.get("import_usd") is None:
            continue
        ex_raw = row.get("export_usd")
        im_raw = row.get("import_usd")
        try:
            ex = float(ex_raw) if ex_raw is not None else None
        except Exception:
            ex = None
        try:
            im = float(im_raw) if im_raw is not None else None
        except Exception:
            im = None
        bal = None
        if ex is not None or im is not None:
            bal = (ex or 0) - (im or 0)
        return {
            "period": row.get("period"),
            "export_usd": ex,
            "import_usd": im,
            "balance_usd": bal,
        }
    return None


def _display_data_for_llm(card_key: str, tab_key: str, scope: str, snapshot_inputs: list[WidgetSnapshot]) -> dict[str, Any]:
    if not snapshot_inputs:
        return {}
    payload = snapshot_inputs[0].payload if isinstance(snapshot_inputs[0].payload, dict) else {}

    if card_key == "trade_flow":
        if tab_key == "corridors":
            by_geo = payload.get("by_geo")
            row = {}
            if isinstance(by_geo, dict):
                g = by_geo.get("Global")
                if isinstance(g, dict):
                    row = g
            return {
                "geo": "Global",
                "period": row.get("period"),
                "value_usd_top": row.get("value_usd_top") or [],
                "volume_top": row.get("volume_top") or [],
                "export_usd": row.get("export_usd"),
                "import_usd": row.get("import_usd"),
                "trade_balance_usd": row.get("trade_balance_usd"),
                "source": payload.get("source"),
                "updated_at": payload.get("updated_at"),
            }
        if tab_key == "wci":
            wci = payload.get("wci")
            return {"wci": wci if isinstance(wci, dict) else {}, "source": payload.get("source"), "updated_at": payload.get("updated_at")}
        if tab_key == "portwatch":
            portwatch = payload.get("portwatch")
            return {"portwatch": portwatch if isinstance(portwatch, dict) else {}, "source": payload.get("source"), "updated_at": payload.get("updated_at")}
        if tab_key in {"exim", "balance"}:
            return {
                "geo": scope,
                "latest": _latest_trade_year_row(payload),
                "series": payload.get("series") if isinstance(payload.get("series"), list) else [],
                "source": payload.get("source"),
                "frequency": payload.get("frequency"),
                "date": payload.get("date"),
            }

    if card_key == "wealth":
        if tab_key in {"gdp_pc", "cons"}:
            return {
                "geo": scope,
                "series": payload.get("series") if isinstance(payload.get("series"), list) else [],
                "source": payload.get("source"),
                "frequency": payload.get("frequency"),
                "date": payload.get("date"),
            }
        if tab_key == "age":
            return {
                "geo": scope,
                "rows": payload.get("rows") if isinstance(payload.get("rows"), list) else [],
                "source": payload.get("source"),
                "frequency": payload.get("frequency"),
                "period": payload.get("period"),
            }
        if tab_key in {"disp_pc", "disp_hh"}:
            rows = payload.get("rows")
            row = {}
            if isinstance(rows, dict):
                one = rows.get(scope)
                if isinstance(one, dict):
                    row = one
            return {
                "geo": scope,
                "row": row,
                "source": payload.get("source"),
                "link": payload.get("link"),
                "note": "latest point only",
            }

    if card_key == "finance":
        if tab_key == "industry":
            rows = payload.get("rows")
            if not isinstance(rows, list):
                rows = []
            return {
                "rows_top10": rows[:10],
                "source": payload.get("source"),
                "link": payload.get("link"),
                "unit": payload.get("unit"),
                "currency": payload.get("currency"),
            }
        if tab_key == "country":
            rows = payload.get("rows")
            if not isinstance(rows, list):
                rows = []
            return {
                "rows_top10": rows[:10],
                "source": payload.get("source"),
                "link": payload.get("link"),
            }

    return {"payload": payload}


def _gen_insight(
    db: Session,
    *,
    card_key: str,
    tab_key: str,
    scope: str,
    lang: str,
    snapshot_inputs: list[WidgetSnapshot],
    extra_context: dict[str, Any],
    fallback_text: str,
    job_run_id: int | None,
) -> tuple[bool, str | None]:
    del fallback_text
    # Build a stable input object
    input_keys = []
    for s in snapshot_inputs:
        input_keys.append(
            {
                "widget_key": s.widget_key,
                "scope": s.scope,
                "snapshot_id": int(s.id),
                "fetched_at": s.fetched_at.isoformat() if s.fetched_at else None,
                "source_updated_at": s.source_updated_at.isoformat() if s.source_updated_at else None,
            }
        )

    input_obj = {
        "card_key": card_key,
        "tab_key": tab_key,
        "scope": scope,
        "lang": lang,
        "display_data": _display_data_for_llm(card_key, tab_key, scope, snapshot_inputs),
        "snapshots": [{"key": s.widget_key, "scope": s.scope, "payload": s.payload} for s in snapshot_inputs],
        "extra": extra_context,
    }
    data_digest = digest_for_inputs(input_obj)

    # Ask LLM to do research-style synthesis (optional). It should be grounded in provided data and cite sources.
    system = (
        "You are a macroeconomic analyst and corporate strategy advisor. Your readers are (1) economic analysts and "
        "(2) senior executives. Write a concise, decision-oriented Insight for the selected dashboard card/tab. "
        "Use ONLY the provided data, its source metadata, the declared/inferred source-updated time, and the provided public excerpts. "
        "Do NOT mention job execution times. Do NOT invent numbers. "
        "If data is proxy/nowcast/scraped, explicitly caveat. "
        "Style: 2-4 short bullet points max, each bullet actionable or interpretive. "
        "Keep the JSON output compact (<= ~1200 chars). "
        "Return STRICT JSON with keys: insight (string), references (array of {title,url,publisher,date})."
    )

    # Provide the model with candidate public URLs it may cite (no guarantee it can browse).
    public_urls: list[str] = []
    for s in snapshot_inputs:
        if isinstance(s.payload, dict):
            for k in ("link", "url"):
                v = s.payload.get(k)
                if isinstance(v, str) and v.startswith("http") and v not in public_urls:
                    public_urls.append(v)
    for v in extra_context.values():
        if isinstance(v, str) and v.startswith("http") and v not in public_urls:
            public_urls.append(v)

    user = json.dumps(
        {
            "task": "Generate dashboard Insight",
            "audience": ["economic analysts", "executives"],
            "card_key": card_key,
            "tab_key": tab_key,
            "scope": scope,
            "constraints": {
                "length": "2-4 bullets",
                "must_reference_data": True,
                "must_use_source_updated_at": True,
                "avoid_job_time": True,
                "no_fabrication": True,
                "json_max_chars": 1200,
            },
            "inputs": input_obj,
            "candidate_public_urls": public_urls,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )

    llm = generate_insight_with_llm(system=system, user=user)
    if not llm.ok:
        return False, llm.error or "llm generation failed"

    content = llm.content
    references = llm.references if isinstance(llm.references, list) else []

    # Prefer the freshest source_updated_at among inputs (NOT fetched_at)
    src_at = None
    for s in snapshot_inputs:
        if s.source_updated_at and (src_at is None or s.source_updated_at > src_at):
            src_at = s.source_updated_at

    _save_insight(
        db,
        card_key=card_key,
        tab_key=tab_key,
        scope=scope,
        lang=lang,
        content=content,
        reference_list=references,
        source_updated_at=src_at,
        job_run_id=job_run_id,
        data_digest=data_digest,
        input_snapshot_keys=input_keys,
        llm_provider=llm.provider,
        llm_model=llm.model,
        llm_prompt=user,
        llm_error="",
    )
    return True, None


def _run_generate_homepage_insights(db: Session, params: dict[str, Any], job_run_id: int | None) -> str:
    """Generate Insights for homepage cards/tabs.

    Requirement:
    - Insight must change with scope + tab.
    - Content should be synthesized from real widget data + sources + source update time and public excerpts.

    Time budget:
    - Must finish within ~5 minutes. We do batching: always generate global tabs + rotate 1 geo per run.
    """
    # Keep widget_insights strictly LLM-only.
    purged_non_llm = (
        db.query(WidgetInsight)
        .filter(WidgetInsight.generated_by != "llm")
        .delete(synchronize_session=False)
    )
    before_count = (
        db.query(func.count(WidgetInsight.id))
        .filter(WidgetInsight.generated_by == "llm")
        .scalar()
        or 0
    )

    lang = str((params or {}).get("lang") or "en").strip() or "en"
    requested_geos = (params or {}).get("geo_list")
    geo_list = _as_geo_list(requested_geos)
    force_regen = _as_bool((params or {}).get("force_regen"), False)

    # Optional manual filtering: scope/card/tab
    # - scope: 'global' or geo name (e.g. 'India') or list
    # - card_key: 'trade_flow'|'wealth'|'finance'
    # - tab_key: the tab key shown on homepage
    card_filter = ((params or {}).get("card_key") or "").strip()
    tab_filter = ((params or {}).get("tab_key") or (params or {}).get("type") or "").strip()
    scope_param = (params or {}).get("scope")
    scope_filters = _normalize_scope_list(scope_param)

    # Batching cursor (rotate geos across runs) when scopes not manually specified
    from app.db.models import WidgetInsightJobState

    cursor_key = f"generate_homepage_insights:{lang}"  # one cursor per language
    state = db.query(WidgetInsightJobState).filter(WidgetInsightJobState.key == cursor_key).first()
    if state is None:
        state = WidgetInsightJobState(key=cursor_key, value={"geo_idx": 0})
        db.add(state)
        db.flush()

    # If caller specifies scope(s), override geo batching
    if scope_filters:
        geos_to_process = [s for s in scope_filters if s != "global"]
    else:
        geo_idx = int((state.value or {}).get("geo_idx") or 0)
        # If caller explicitly passed geo_list, we still only process 1 geo per run unless forced.
        force_all = _as_bool((params or {}).get("force_all"), False)
        if force_all:
            geos_to_process = geo_list
        else:
            if not geo_list:
                geo_list = list(ALLOWED_GEOS)
            geos_to_process = [geo_list[geo_idx % len(geo_list)]]
            state.value = {"geo_idx": (geo_idx + 1) % len(geo_list)}
            state.updated_at = _now_utc()

    def want(card_key: str, tab_key: str, scope: str) -> bool:
        if card_filter and card_key != card_filter:
            return False
        if tab_filter and tab_key != tab_filter:
            return False
        if scope_filters and _canonical_scope(scope) not in scope_filters:
            return False
        return True

    # Public context URLs per card/tab (job-only fetch + DB cache)
    URLS = {
        ("trade_flow", "wci"): [
            "https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry",
        ],
        ("trade_flow", "portwatch"): [
            "https://portwatch.imf.org/pages/data-and-methodology",
        ],
        ("trade_flow", "exim"): [
            "https://data.worldbank.org/indicator/NE.EXP.GNFS.CD",
            "https://data.worldbank.org/indicator/NE.IMP.GNFS.CD",
        ],
        ("wealth", "gdp_pc"): [
            "https://data.worldbank.org/indicator/NY.GDP.PCAP.CD",
        ],
        ("wealth", "cons"): [
            "https://data.worldbank.org/indicator/NE.CON.PRVT.CD",
        ],
        ("wealth", "age"): [
            "https://data.worldbank.org/indicator/SP.POP.0014.TO.ZS",
            "https://data.worldbank.org/indicator/SP.POP.1564.TO.ZS",
            "https://data.worldbank.org/indicator/SP.POP.65UP.TO.ZS",
        ],
        ("wealth", "disp_pc"): [
            "https://worldpopulationreview.com/country-rankings/disposable-income-by-country",
            "https://data.worldbank.org/indicator/NE.CON.PRVT.PC.KD",
        ],
        ("wealth", "disp_hh"): [
            "https://worldpopulationreview.com/country-rankings/disposable-income-by-country",
            "https://data.worldbank.org/indicator/NE.CON.PRVT.PC.KD",
        ],
        ("finance", "industry"): [
            "https://imaa-institute.org/mergers-and-acquisitions-statistics/ma-statistics-by-industries/",
        ],
        ("finance", "country"): [
            "https://imaa-institute.org/mergers-and-acquisitions-statistics/ma-statistics-by-countries/",
        ],
    }

    def ctx(card_key: str, tab_key: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for url in URLS.get((card_key, tab_key), []):
            row = get_or_refresh_context(db, url=url)
            blocks.append(to_prompt_block(row))
        return blocks

    llm_attempted = 0
    llm_failed: list[str] = []

    def gen(
        *,
        card_key: str,
        tab_key: str,
        scope: str,
        lang: str,
        snapshot_inputs: list[WidgetSnapshot],
        extra_context: dict[str, Any],
        fallback_text: str,
    ) -> None:
        nonlocal llm_attempted
        llm_attempted += 1
        ok, err = _gen_insight(
            db,
            card_key=card_key,
            tab_key=tab_key,
            scope=scope,
            lang=lang,
            snapshot_inputs=snapshot_inputs,
            extra_context=extra_context,
            fallback_text=fallback_text,
            job_run_id=job_run_id,
        )
        if not ok:
            llm_failed.append(f"{card_key}/{tab_key}/{scope}: {err or 'llm generation failed'}")

    # Trade (global tabs)
    trade = get_latest_snapshot(db, "trade_corridors", "global")
    if trade:
        if want("trade_flow", "corridors", "global"):
            gen(
                card_key="trade_flow",
                tab_key="corridors",
                scope="global",
                lang=lang,
                snapshot_inputs=[trade],
                extra_context={"source": trade.source, "source_updated_at": trade.source_updated_at, "public_contexts": ctx("trade_flow", "corridors"), "force_regen": force_regen},
                fallback_text="Top corridors are a directional signal; compare value vs volume leaders to spot reroutes or mix changes.",
            )
        if want("trade_flow", "wci", "global"):
            gen(
                card_key="trade_flow",
                tab_key="wci",
                scope="global",
                lang=lang,
                snapshot_inputs=[trade],
                extra_context={"source": "Drewry WCI (scrape)", "note": "shipping cost proxy", "public_contexts": ctx("trade_flow", "wci"), "force_regen": force_regen},
                fallback_text="Freight (WCI) reflects shipping-cost pressure; treat it as a proxy signal rather than customs trade value.",
            )
        if want("trade_flow", "portwatch", "global"):
            gen(
                card_key="trade_flow",
                tab_key="portwatch",
                scope="global",
                lang=lang,
                snapshot_inputs=[trade],
                extra_context={"source": "IMF PortWatch", "note": "nowcast/proxy", "public_contexts": ctx("trade_flow", "portwatch"), "force_regen": force_regen},
                fallback_text="PortWatch signals are nowcast/proxy indicators; always present them with explicit caveats.",
            )

    # Trade per-geo tabs
    for geo in geos_to_process:
        exim = get_latest_snapshot(db, "trade_exim_5y", geo)
        if not exim:
            continue
        if want("trade_flow", "exim", geo):
            gen(
                card_key="trade_flow",
                tab_key="exim",
                scope=geo,
                lang=lang,
                snapshot_inputs=[exim],
                extra_context={"geo": geo, "source": exim.source, "source_updated_at": exim.source_updated_at, "public_contexts": ctx("trade_flow", "exim"), "force_regen": force_regen},
                fallback_text="Export/import snapshot is available; compare latest vs prior year to spot inflection points.",
            )
        if want("trade_flow", "balance", geo):
            gen(
                card_key="trade_flow",
                tab_key="balance",
                scope=geo,
                lang=lang,
                snapshot_inputs=[exim],
                extra_context={"geo": geo, "definition": "balance = export - import", "public_contexts": ctx("trade_flow", "exim"), "force_regen": force_regen},
                fallback_text="Trade balance is computed as export minus import; watch for large year-over-year moves.",
            )

    # Wealth per-geo
    disp = get_latest_snapshot(db, "wealth_disposable_latest", "global")
    for geo in geos_to_process:
        w = get_latest_snapshot(db, "wealth_indicators_5y", geo)
        if w:
            if want("wealth", "gdp_pc", geo):
                gen(
                    card_key="wealth",
                    tab_key="gdp_pc",
                    scope=geo,
                    lang=lang,
                    snapshot_inputs=[w],
                    extra_context={"geo": geo, "source": w.source, "source_updated_at": w.source_updated_at, "public_contexts": ctx("wealth", "gdp_pc"), "force_regen": force_regen},
                    fallback_text="GDP per capita (nominal USD) can be noisy due to FX; interpret trends with caveats.",
                )
            if want("wealth", "cons", geo):
                gen(
                    card_key="wealth",
                    tab_key="cons",
                    scope=geo,
                    lang=lang,
                    snapshot_inputs=[w],
                    extra_context={"geo": geo, "source": w.source, "source_updated_at": w.source_updated_at, "public_contexts": ctx("wealth", "cons"), "force_regen": force_regen},
                    fallback_text="Consumption can proxy domestic-demand momentum; compare with trade signals for context.",
                )

        age = get_latest_snapshot(db, "wealth_age_structure_latest", geo)
        if age and want("wealth", "age", geo):
            gen(
                card_key="wealth",
                tab_key="age",
                scope=geo,
                lang=lang,
                snapshot_inputs=[age],
                extra_context={"geo": geo, "source": age.source, "source_updated_at": age.source_updated_at, "public_contexts": ctx("wealth", "age"), "force_regen": force_regen},
                fallback_text="Age structure provides demographic context; treat it as population composition (not income-by-age).",
            )

        # Disposable insights should follow geo (scope)
        if disp:
            # We do not have per-geo snapshots for disposable; we still generate per-geo insights
            # by providing geo + per-geo row values in extra_context.
            row = None
            if isinstance(disp.payload, dict):
                rows = disp.payload.get("rows")
                if isinstance(rows, dict):
                    row = rows.get(geo)
            if want("wealth", "disp_pc", geo):
                gen(
                    card_key="wealth",
                    tab_key="disp_pc",
                    scope=geo,
                    lang=lang,
                    snapshot_inputs=[disp],
                    extra_context={"geo": geo, "disposable_row": row, "source": disp.source, "source_updated_at": disp.source_updated_at, "public_contexts": ctx("wealth", "disp_pc"), "force_regen": force_regen},
                    fallback_text="Disposable income is best-effort: WPR scrape + World Bank proxy fallback; treat as indicative latest point.",
                )
            if want("wealth", "disp_hh", geo):
                gen(
                    card_key="wealth",
                    tab_key="disp_hh",
                    scope=geo,
                    lang=lang,
                    snapshot_inputs=[disp],
                    extra_context={"geo": geo, "disposable_row": row, "source": disp.source, "source_updated_at": disp.source_updated_at, "public_contexts": ctx("wealth", "disp_hh"), "force_regen": force_regen},
                    fallback_text="Household disposable values may be missing; consider OECD SDMX where coverage exists.",
                )

    # Finance (global)
    fin_i = get_latest_snapshot(db, "finance_ma_industry", "global")
    if fin_i and want("finance", "industry", "global"):
        gen(
            card_key="finance",
            tab_key="industry",
            scope="global",
            lang=lang,
            snapshot_inputs=[fin_i],
            extra_context={"source": fin_i.source, "source_updated_at": fin_i.source_updated_at, "public_contexts": ctx("finance", "industry"), "force_regen": force_regen},
            fallback_text="Industry ranking reflects disclosed-deal reporting; treat as directional concentration of activity.",
        )

    fin_c = get_latest_snapshot(db, "finance_ma_country", "global")
    if fin_c and want("finance", "country", "global"):
        gen(
            card_key="finance",
            tab_key="country",
            scope="global",
            lang=lang,
            snapshot_inputs=[fin_c],
            extra_context={"source": fin_c.source, "source_updated_at": fin_c.source_updated_at, "public_contexts": ctx("finance", "country"), "force_regen": force_regen},
            fallback_text="Country narratives may mix currencies; use normalized FX conversion for strict comparisons.",
        )

    after_count = (
        db.query(func.count(WidgetInsight.id))
        .filter(WidgetInsight.generated_by == "llm")
        .scalar()
        or 0
    )
    added = int(after_count) - int(before_count)
    failed = len(llm_failed)
    if llm_attempted > 0 and failed == llm_attempted:
        raise RuntimeError("all LLM insight generations failed: " + " | ".join(llm_failed[:5]))
    msg = (
        f"homepage insights saved: +{added}, attempted={llm_attempted}, "
        f"failed={failed}, purged_non_llm={int(purged_non_llm)}"
    )
    if llm_failed:
        msg += " (partial llm failures logged)"
    return msg


JOB_SPECS: dict[str, JobSpec] = {
    "generate_homepage_insights": JobSpec(
        job_id="generate_homepage_insights",
        name="Generate Homepage Insights",
        description="Generate Insights text for homepage cards/tabs and save to DB.",
        # run once per day (Asia/Shanghai) to control cost
        cron_expr="0 7 * * *",
        timezone=settings.TZ,
        default_params={},
        normalize_params=_normalize_generate_homepage_insights,
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
        misfire_grace_time = 3600 if row.job_id == "generate_homepage_insights" else 120
        scheduler.add_job(
            run_job_now,
            trigger=trigger,
            id=f"job:{row.job_id}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=misfire_grace_time,
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

    warmup_jobs = [job_id for job_id in JOB_SPECS if job_id not in {"cleanup_snapshots", "generate_homepage_insights"}]
    warmup_jobs.append("generate_homepage_insights")

    delay_seconds = 2
    for job_id in warmup_jobs:
        run_at = _now_utc() + timedelta(seconds=delay_seconds)
        if job_id == "generate_homepage_insights":
            # Run insight generation after upstream snapshot jobs have had time to materialize.
            run_at = _now_utc() + timedelta(seconds=max(delay_seconds, 90))
        scheduler.add_job(
            run_job_now,
            id=f"warmup:{job_id}",
            replace_existing=True,
            next_run_time=run_at,
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
