from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.web import widget_data
from app.jobs.runtime import (
    get_latest_snapshot,
    get_latest_snapshots_by_key,
    get_next_run_time,
    list_job_definitions,
    list_recent_job_runs,
    parse_params_json,
    run_job_now,
    update_job_definition,
)
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import JobRun, UserVisitLog, WidgetSnapshot
from app.db.session import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


def _client_ip(request: Request) -> str:
    # Prefer reverse-proxy header if present; otherwise fall back to peer.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _fmt_utc(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _snapshot_payload(snapshot: WidgetSnapshot | None, fallback: dict | None = None) -> dict:
    if snapshot and isinstance(snapshot.payload, dict):
        return snapshot.payload
    return fallback or {}


def _jobs_redirect_url(request: Request, msg: str) -> str:
    base = settings.BASE_PATH.rstrip("/")
    use_prefixed = bool(base) and request.url.path.startswith(f"{base}/")
    path = f"{base}/jobs" if use_prefixed else "/jobs"
    return f"{path}?msg={quote(msg)}"


def _dashboard_payload(db: Session) -> tuple[dict, datetime | None, bool]:
    trade = get_latest_snapshot(db, "trade_corridors", "global")
    trade_exim = get_latest_snapshots_by_key(db, "trade_exim_5y")
    wealth_ind = get_latest_snapshots_by_key(db, "wealth_indicators_5y")
    wealth_disp = get_latest_snapshot(db, "wealth_disposable_latest", "global")
    wealth_age = get_latest_snapshots_by_key(db, "wealth_age_structure_latest")
    fin_ind = get_latest_snapshot(db, "finance_ma_industry", "global")
    fin_cty = get_latest_snapshot(db, "finance_ma_country", "global")

    trade_payload = _snapshot_payload(trade)
    geos = trade_payload.get("geos") if isinstance(trade_payload.get("geos"), list) else []
    if not geos:
        geos = ["Global", "India", "Mexico", "Singapore", "Hong Kong"]

    trade_exim_by_geo = {}
    wealth_ind_by_geo = {}
    wealth_age_by_geo = {}
    for geo in geos:
        trade_exim_by_geo[geo] = _snapshot_payload(trade_exim.get(geo), fallback={"series": [], "source": "N/A", "frequency": "annual", "date": ""})
        wealth_ind_by_geo[geo] = _snapshot_payload(wealth_ind.get(geo), fallback={"series": [], "source": "N/A", "frequency": "annual", "date": ""})
        wealth_age_by_geo[geo] = _snapshot_payload(wealth_age.get(geo), fallback={"rows": [], "source": "N/A", "frequency": "annual", "period": ""})

    all_snaps: list[WidgetSnapshot] = [
        s for s in [trade, wealth_disp, fin_ind, fin_cty] if s is not None
    ] + [s for s in trade_exim.values() if s is not None] + [s for s in wealth_ind.values() if s is not None] + [s for s in wealth_age.values() if s is not None]

    latest_at = max((s.fetched_at for s in all_snaps), default=None)
    is_stale = any(bool(s.is_stale) for s in all_snaps)

    payload = {
        "trade_corridors": trade_payload,
        "trade_exim_by_geo": trade_exim_by_geo,
        "wealth_indicators_by_geo": wealth_ind_by_geo,
        "wealth_age_structure_by_geo": wealth_age_by_geo,
        "wealth_disposable_latest": _snapshot_payload(wealth_disp, fallback={"rows": {}, "source": "N/A", "link": ""}),
        "finance_ma_industry": _snapshot_payload(fin_ind, fallback={"rows": [], "source": "N/A", "link": ""}),
        "finance_ma_country": _snapshot_payload(fin_cty, fallback={"rows": [], "source": "N/A", "link": ""}),
    }
    return payload, latest_at, is_stale


@router.get("/", response_class=HTMLResponse)
def homepage(request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]

    db.add(UserVisitLog(ip=ip, user_agent=ua))
    db.commit()

    visited_count = db.query(func.count(UserVisitLog.id)).scalar() or 0
    dashboard_data, latest_at, is_stale = _dashboard_payload(db)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "base_path": settings.BASE_PATH.rstrip("/"),
            "visited_count": visited_count,
            "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "dashboard_data": dashboard_data,
            "data_updated_at": _fmt_utc(latest_at),
            "data_is_stale": is_stale,
        },
    )


@router.get("/v2", response_class=HTMLResponse)
def homepage_v2(request: Request, db: Session = Depends(get_db)):
    """New v2 homepage sample.

    Constraints (must-haves):
    - Web pages MUST NOT call external APIs directly.
    - External data acquisition MUST be done via scheduled jobs.
    - This page may call *internal* APIs that read DB snapshots (future enhancement).

    For now we render a static implementation based on app/web/test/20260213_t1.html.
    """
    # Still record visit for consistency.
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]
    db.add(UserVisitLog(ip=ip, user_agent=ua))
    db.commit()

    # Reuse dashboard snapshot freshness to display a consistent "Data updated at".
    _, latest_at, _ = _dashboard_payload(db)

    dashboard_data, latest_at, is_stale = _dashboard_payload(db)

    return templates.TemplateResponse(
        "dashboard_v2.html",
        {
            "request": request,
            "base_path": settings.BASE_PATH.rstrip("/"),
            "dashboard_data": dashboard_data,
            "data_updated_at": _fmt_utc(latest_at),
            "data_is_stale": is_stale,
        },
    )


@router.get("/health", response_class=HTMLResponse)
def health():
    return "OK"


# --- Widget APIs (MVP stubs) ---


@router.get("/api/trade/corridors")
def api_trade_corridors(db: Session = Depends(get_db)):
    snapshot = get_latest_snapshot(db, "trade_corridors", "global")
    if snapshot:
        return snapshot.payload
    return {"ok": False, "error": "snapshot not ready"}


@router.post("/api/trade/refresh")
def api_trade_refresh():
    results = [
        run_job_now("trade_corridors", {"force_wci": True}, triggered_by="api"),
        run_job_now("trade_exim_5y", {"force": True}, triggered_by="api"),
    ]
    return {
        "ok": all(x.get("ok") for x in results),
        "refreshed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "details": results,
    }


@router.get("/api/trade/exim-5y")
def api_trade_exim_5y(geo: str = "Global", db: Session = Depends(get_db)):
    snapshot = get_latest_snapshot(db, "trade_exim_5y", geo)
    if snapshot:
        return snapshot.payload
    return {"ok": False, "error": f"snapshot not ready for geo={geo}", "series": []}


@router.get("/api/wealth/proxy")
def api_wealth_proxy():
    return widget_data.wealth_proxy_mvp()


@router.get("/api/finance/big-transactions")
def api_finance_big_transactions():
    return widget_data.finance_big_transactions_mvp()


@router.get("/api/wealth/indicators-5y")
def api_wealth_indicators_5y(geo: str = "Global", db: Session = Depends(get_db)):
    snapshot = get_latest_snapshot(db, "wealth_indicators_5y", geo)
    if snapshot:
        return snapshot.payload
    return {"ok": False, "error": f"snapshot not ready for geo={geo}", "series": []}


@router.get("/api/wealth/disposable-latest")
def api_wealth_disposable_latest(db: Session = Depends(get_db)):
    snapshot = get_latest_snapshot(db, "wealth_disposable_latest", "global")
    if snapshot:
        return snapshot.payload
    return {"ok": False, "error": "snapshot not ready", "rows": {}}


@router.get("/api/wealth/age-structure-latest")
def api_wealth_age_structure_latest(geo: str = "Global", db: Session = Depends(get_db)):
    snapshot = get_latest_snapshot(db, "wealth_age_structure_latest", geo)
    if snapshot:
        return snapshot.payload
    return {"ok": False, "error": f"snapshot not ready for geo={geo}", "rows": []}


@router.get("/api/finance/ma/industry")
def api_finance_ma_industry(db: Session = Depends(get_db)):
    snapshot = get_latest_snapshot(db, "finance_ma_industry", "global")
    if snapshot:
        return snapshot.payload
    return {"ok": False, "error": "snapshot not ready", "rows": []}


@router.get("/api/finance/ma/country")
def api_finance_ma_country(db: Session = Depends(get_db)):
    snapshot = get_latest_snapshot(db, "finance_ma_country", "global")
    if snapshot:
        return snapshot.payload
    return {"ok": False, "error": "snapshot not ready", "rows": []}


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, msg: str = "", db: Session = Depends(get_db)):
    jobs = []
    for row in list_job_definitions(db):
        next_run = get_next_run_time(row.job_id)
        jobs.append(
            {
                "job_id": row.job_id,
                "name": row.name,
                "description": row.description,
                "cron_expr": row.cron_expr,
                "timezone": row.timezone,
                "enabled": row.enabled,
                "default_params_json": json.dumps(row.default_params or {}, ensure_ascii=False),
                "last_success_at": _fmt_utc(row.last_success_at),
                "next_run_at": _fmt_utc(next_run),
            }
        )

    runs: list[JobRun] = list_recent_job_runs(db, limit=120)

    return templates.TemplateResponse(
        "jobs.html",
        {
            "request": request,
            "base_path": settings.BASE_PATH.rstrip("/"),
            "msg": msg,
            "jobs_enabled": settings.JOBS_ENABLED,
            "jobs": jobs,
            "runs": runs,
            "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        },
    )


@router.post("/jobs/run")
def jobs_run(
    request: Request,
    job_id: str = Form(...),
    params_json: str = Form(default=""),
):
    params = parse_params_json(params_json, fallback={})
    result = run_job_now(job_id=job_id, params_override=params, triggered_by="manual")
    msg = f"{job_id}: {result.get('status')} ({result.get('message') or result.get('error') or ''})"
    return RedirectResponse(url=_jobs_redirect_url(request, msg), status_code=303)


@router.post("/jobs/update")
def jobs_update(
    request: Request,
    db: Session = Depends(get_db),
    job_id: str = Form(...),
    cron_expr: str = Form(...),
    timezone_name: str = Form(default=""),
    enabled: str | None = Form(default=None),
    default_params_json: str = Form(default="{}"),
):
    default_params = parse_params_json(default_params_json, fallback={})
    ok, detail = update_job_definition(
        db,
        job_id=job_id,
        cron_expr=cron_expr,
        timezone_name=timezone_name,
        enabled=(enabled == "on"),
        default_params=default_params,
    )
    status = "updated" if ok else "failed"
    msg = f"{job_id}: {status} ({detail})"
    return RedirectResponse(url=_jobs_redirect_url(request, msg), status_code=303)


def _register_base_path_aliases() -> None:
    base = settings.BASE_PATH.rstrip("/")
    if not base or base == "/":
        return

    alias_specs = [
        {"path": base, "endpoint": homepage, "methods": ["GET"], "response_class": HTMLResponse, "name": "prefixed_homepage_root"},
        {"path": f"{base}/", "endpoint": homepage, "methods": ["GET"], "response_class": HTMLResponse, "name": "prefixed_homepage_slash"},
        {"path": f"{base}/health", "endpoint": health, "methods": ["GET"], "response_class": HTMLResponse, "name": "prefixed_health"},
        {"path": f"{base}/v2", "endpoint": homepage_v2, "methods": ["GET"], "response_class": HTMLResponse, "name": "prefixed_homepage_v2"},
        {"path": f"{base}/api/trade/corridors", "endpoint": api_trade_corridors, "methods": ["GET"], "name": "prefixed_api_trade_corridors"},
        {"path": f"{base}/api/trade/refresh", "endpoint": api_trade_refresh, "methods": ["POST"], "name": "prefixed_api_trade_refresh"},
        {"path": f"{base}/api/trade/exim-5y", "endpoint": api_trade_exim_5y, "methods": ["GET"], "name": "prefixed_api_trade_exim_5y"},
        {"path": f"{base}/api/wealth/proxy", "endpoint": api_wealth_proxy, "methods": ["GET"], "name": "prefixed_api_wealth_proxy"},
        {"path": f"{base}/api/finance/big-transactions", "endpoint": api_finance_big_transactions, "methods": ["GET"], "name": "prefixed_api_finance_big_transactions"},
        {"path": f"{base}/api/wealth/indicators-5y", "endpoint": api_wealth_indicators_5y, "methods": ["GET"], "name": "prefixed_api_wealth_indicators_5y"},
        {"path": f"{base}/api/wealth/disposable-latest", "endpoint": api_wealth_disposable_latest, "methods": ["GET"], "name": "prefixed_api_wealth_disposable_latest"},
        {"path": f"{base}/api/finance/ma/industry", "endpoint": api_finance_ma_industry, "methods": ["GET"], "name": "prefixed_api_finance_ma_industry"},
        {"path": f"{base}/api/finance/ma/country", "endpoint": api_finance_ma_country, "methods": ["GET"], "name": "prefixed_api_finance_ma_country"},
        {"path": f"{base}/jobs", "endpoint": jobs_page, "methods": ["GET"], "response_class": HTMLResponse, "name": "prefixed_jobs_page"},
        {"path": f"{base}/jobs/run", "endpoint": jobs_run, "methods": ["POST"], "name": "prefixed_jobs_run"},
        {"path": f"{base}/jobs/update", "endpoint": jobs_update, "methods": ["POST"], "name": "prefixed_jobs_update"},
    ]

    for spec in alias_specs:
        router.add_api_route(
            spec["path"],
            endpoint=spec["endpoint"],
            methods=spec["methods"],
            response_class=spec.get("response_class"),
            include_in_schema=False,
            name=spec["name"],
        )


_register_base_path_aliases()
