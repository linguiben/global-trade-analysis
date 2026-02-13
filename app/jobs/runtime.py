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
from app.db.models import JobDefinition, JobRun, WidgetSnapshot
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
) -> None:
    db.add(
        WidgetSnapshot(
            widget_key=widget_key,
            scope=scope,
            payload=payload,
            source=source,
            is_stale=is_stale,
            fetched_at=_now_utc(),
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
    _record_snapshot(
        db,
        widget_key="trade_corridors",
        scope="global",
        payload=payload,
        source=payload.get("source", ""),
        is_stale=wci_error,
        job_run_id=job_run_id,
    )
    return "trade corridors snapshot saved"


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
        )
        count += 1
    return f"wealth indicator snapshots saved: {count}, stale: {failed}"


def _run_wealth_disposable(db: Session, params: dict[str, Any], job_run_id: int | None) -> str:
    payload = fetch_disposable_income_latest(force=params["force"])
    stale = not bool(payload.get("ok"))
    _record_snapshot(
        db,
        widget_key="wealth_disposable_latest",
        scope="global",
        payload=payload,
        source=payload.get("source", ""),
        is_stale=stale,
        job_run_id=job_run_id,
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
        )
        count += 1
    return f"wealth age-structure snapshots saved: {count}, stale: {failed}"


def _run_finance_industry(db: Session, params: dict[str, Any], job_run_id: int | None) -> str:
    payload = fetch_ma_by_industry(force=params["force"])
    stale = not bool(payload.get("ok"))
    _record_snapshot(
        db,
        widget_key="finance_ma_industry",
        scope="global",
        payload=payload,
        source=payload.get("source", ""),
        is_stale=stale,
        job_run_id=job_run_id,
    )
    return "finance industry snapshot saved"


def _run_finance_country(db: Session, params: dict[str, Any], job_run_id: int | None) -> str:
    payload = fetch_ma_by_country(force=params["force"])
    stale = not bool(payload.get("ok"))
    _record_snapshot(
        db,
        widget_key="finance_ma_country",
        scope="global",
        payload=payload,
        source=payload.get("source", ""),
        is_stale=stale,
        job_run_id=job_run_id,
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


JOB_SPECS: dict[str, JobSpec] = {
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
