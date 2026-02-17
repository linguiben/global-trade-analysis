from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.web import widget_data
from app.jobs.runtime import (
    ALLOWED_GEOS,
    ALLOWED_INSIGHT_CARD_KEYS,
    ALLOWED_INSIGHT_TAB_KEYS,
    get_allowed_geos,
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
from app.db.models import GeoDictionary, JobRun, UserVisitLog, WidgetInsight, WidgetSnapshot
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
        # Attach DB-level metadata without changing job payload contract.
        payload = dict(snapshot.payload)
        payload.setdefault("_meta", {})
        if isinstance(payload.get("_meta"), dict):
            payload["_meta"].update(
                {
                    "fetched_at": snapshot.fetched_at.isoformat() if snapshot.fetched_at else None,
                    "source_updated_at": snapshot.source_updated_at.isoformat() if snapshot.source_updated_at else None,
                    "source_updated_at_note": snapshot.source_updated_at_note or "",
                }
            )
        return payload
    return fallback or {}


def _jobs_redirect_url(request: Request, msg: str) -> str:
    base = settings.BASE_PATH.rstrip("/")
    use_prefixed = bool(base) and request.url.path.startswith(f"{base}/")
    path = f"{base}/jobs" if use_prefixed else "/jobs"
    return f"{path}?msg={quote(msg)}"


def _latest_insights_map(db: Session) -> dict:
    """Return latest LLM insights keyed by (card_key, tab_key, scope)."""
    rows: list[WidgetInsight] = (
        db.query(WidgetInsight)
        .filter(WidgetInsight.generated_by == "llm")
        .order_by(WidgetInsight.card_key.asc(), WidgetInsight.tab_key.asc(), WidgetInsight.scope.asc(), WidgetInsight.id.desc())
        .all()
    )

    out: dict[str, dict[str, dict[str, dict]]] = {}
    for r in rows:
        card = r.card_key
        tab = r.tab_key
        scope = r.scope
        out.setdefault(card, {}).setdefault(tab, {})
        if scope in out[card][tab]:
            continue
        out[card][tab][scope] = {
            "content": r.content,
            "reference_list": r.reference_list or [],
            "source_updated_at": r.source_updated_at.isoformat() if r.source_updated_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
    return out


def _dashboard_payload(db: Session) -> tuple[dict, datetime | None, bool]:
    trade = get_latest_snapshot(db, "trade_corridors", "Global")
    trade_exim = get_latest_snapshots_by_key(db, "trade_exim_5y")
    wealth_ind = get_latest_snapshots_by_key(db, "wealth_indicators_5y")
    wealth_disp = get_latest_snapshot(db, "wealth_disposable_latest", "Global")
    wealth_age = get_latest_snapshots_by_key(db, "wealth_age_structure_latest")
    fin_ind = get_latest_snapshot(db, "finance_ma_industry", "Global")
    fin_cty = get_latest_snapshot(db, "finance_ma_country", "Global")

    trade_payload = _snapshot_payload(trade)
    corridor_geos = trade_payload.get("geos") if isinstance(trade_payload.get("geos"), list) else []
    if not corridor_geos:
        corridor_geos = ["Global", "India", "Mexico", "Singapore", "Hong Kong"]

    # Merge all scopes that have ANY snapshot data (not just trade_corridors geos)
    all_geos_set: set[str] = set(corridor_geos)
    all_geos_set.update(trade_exim.keys())
    all_geos_set.update(wealth_ind.keys())
    all_geos_set.update(wealth_age.keys())
    geos = sorted(all_geos_set, key=lambda g: (g != "Global", g))

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

    trade_payload["geos"] = geos

    payload = {
        "trade_corridors": trade_payload,
        "trade_exim_by_geo": trade_exim_by_geo,
        "wealth_indicators_by_geo": wealth_ind_by_geo,
        "wealth_age_structure_by_geo": wealth_age_by_geo,
        "wealth_disposable_latest": _snapshot_payload(wealth_disp, fallback={"rows": {}, "source": "N/A", "link": ""}),
        "finance_ma_industry": _snapshot_payload(fin_ind, fallback={"rows": [], "source": "N/A", "link": ""}),
        "finance_ma_country": _snapshot_payload(fin_cty, fallback={"rows": [], "source": "N/A", "link": ""}),
        "insights": _latest_insights_map(db),
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
@router.head("/v2")
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


@router.get("/v3", response_class=HTMLResponse)
@router.head("/v3")
def homepage_v3(request: Request, db: Session = Depends(get_db)):
    """v3 homepage.

    v3 keeps the v1 (dashboard.html) visual style but fixes minor JS issues and
    adds simple version navigation.
    """
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]
    db.add(UserVisitLog(ip=ip, user_agent=ua))
    db.commit()

    visited_count = db.query(func.count(UserVisitLog.id)).scalar() or 0
    dashboard_data, latest_at, is_stale = _dashboard_payload(db)

    return templates.TemplateResponse(
        "dashboard_v3.html",
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


@router.get("/v4", response_class=HTMLResponse)
@router.head("/v4")
def homepage_v4(request: Request, db: Session = Depends(get_db)):
    """v4 homepage.

    v4 redesigns the executive summary into a single concise narrative
    paragraph for management, with collapsible key metrics.
    """
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]
    db.add(UserVisitLog(ip=ip, user_agent=ua))
    db.commit()

    visited_count = db.query(func.count(UserVisitLog.id)).scalar() or 0
    dashboard_data, latest_at, is_stale = _dashboard_payload(db)

    return templates.TemplateResponse(
        "dashboard_v4.html",
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


@router.get("/v5", response_class=HTMLResponse)
@router.head("/v5")
def homepage_v5(request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]
    db.add(UserVisitLog(ip=ip, user_agent=ua))
    db.commit()

    visited_count = db.query(func.count(UserVisitLog.id)).scalar() or 0
    dashboard_data, latest_at, is_stale = _dashboard_payload(db)

    return templates.TemplateResponse(
        "dashboard_v5.html",
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


@router.get("/v5_1", response_class=HTMLResponse)
@router.head("/v5_1")
def homepage_v5_1(request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]
    db.add(UserVisitLog(ip=ip, user_agent=ua))
    db.commit()

    visited_count = db.query(func.count(UserVisitLog.id)).scalar() or 0
    dashboard_data, latest_at, is_stale = _dashboard_payload(db)

    return templates.TemplateResponse(
        "dashboard_v5_1.html",
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


@router.get("/v5_2", response_class=HTMLResponse)
@router.head("/v5_2")
def homepage_v5_2(request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]
    db.add(UserVisitLog(ip=ip, user_agent=ua))
    db.commit()

    visited_count = db.query(func.count(UserVisitLog.id)).scalar() or 0
    dashboard_data, latest_at, is_stale = _dashboard_payload(db)

    return templates.TemplateResponse(
        "dashboard_v5_2.html",
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


@router.get("/v5_3", response_class=HTMLResponse)
@router.head("/v5_3")
def homepage_v5_3(request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]
    db.add(UserVisitLog(ip=ip, user_agent=ua))
    db.commit()

    visited_count = db.query(func.count(UserVisitLog.id)).scalar() or 0
    dashboard_data, latest_at, is_stale = _dashboard_payload(db)

    return templates.TemplateResponse(
        "dashboard_v5_3.html",
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


@router.get("/v6", response_class=HTMLResponse)
@router.head("/v6")
def homepage_v6(request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]
    db.add(UserVisitLog(ip=ip, user_agent=ua))
    db.commit()

    visited_count = db.query(func.count(UserVisitLog.id)).scalar() or 0
    dashboard_data, latest_at, is_stale = _dashboard_payload(db)

    return templates.TemplateResponse(
        "dashboard_v6.html",
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


@router.get("/v7", response_class=HTMLResponse)
@router.head("/v7")
def homepage_v7(request: Request, db: Session = Depends(get_db)):
    """v7 homepage — serves the static t7.html infographic page."""
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]
    db.add(UserVisitLog(ip=ip, user_agent=ua))
    db.commit()

    return FileResponse("app/web/static/t7.html", media_type="text/html")


@router.get("/health", response_class=HTMLResponse)
def health():
    return "OK"


# --- Widget APIs (MVP stubs) ---


@router.get("/api/trade/corridors")
def api_trade_corridors(db: Session = Depends(get_db)):
    snapshot = get_latest_snapshot(db, "trade_corridors", "Global")
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
    snapshot = get_latest_snapshot(db, "wealth_disposable_latest", "Global")
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
    snapshot = get_latest_snapshot(db, "finance_ma_industry", "Global")
    if snapshot:
        return snapshot.payload
    return {"ok": False, "error": "snapshot not ready", "rows": []}


@router.get("/api/finance/ma/country")
def api_finance_ma_country(db: Session = Depends(get_db)):
    snapshot = get_latest_snapshot(db, "finance_ma_country", "Global")
    if snapshot:
        return snapshot.payload
    return {"ok": False, "error": "snapshot not ready", "rows": []}


@router.get("/map/trade-flow", response_class=HTMLResponse)
def trade_flow_map(request: Request, db: Session = Depends(get_db)):
    dashboard_data, latest_at, is_stale = _dashboard_payload(db)
    return templates.TemplateResponse(
        "trade_flow_map.html",
        {
            "request": request,
            "base_path": settings.BASE_PATH.rstrip("/"),
            "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "mode": "all",
            "mode_label": "ALL SCOPES",
            "dashboard_data": dashboard_data,
            "data_updated_at": _fmt_utc(latest_at),
            "data_is_stale": is_stale,
        },
    )


@router.get("/map/trade-flow-top5", response_class=HTMLResponse)
def trade_flow_map_top5(request: Request, db: Session = Depends(get_db)):
    dashboard_data, latest_at, is_stale = _dashboard_payload(db)
    return templates.TemplateResponse(
        "trade_flow_map.html",
        {
            "request": request,
            "base_path": settings.BASE_PATH.rstrip("/"),
            "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "mode": "top5",
            "mode_label": "TOP 5",
            "dashboard_data": dashboard_data,
            "data_updated_at": _fmt_utc(latest_at),
            "data_is_stale": is_stale,
        },
    )


@router.get("/api/trade/exim-latest-all")
def api_trade_exim_latest_all(top_n: int | None = None, db: Session = Depends(get_db)):
    """Aggregate latest export/import per geo from DB snapshots.

    This is a DB-reader API (no external fetch). Intended for map overlays.
    """

    def latest_point(payload: dict[str, Any]) -> tuple[int | None, float | None, float | None]:
        # payload from fetch_trade_exim_5y: {series:[{period,export_usd,import_usd},...]}
        series = payload.get("series") or []
        if not isinstance(series, list):
            return None, None, None
        for row in reversed(series):
            if not isinstance(row, dict):
                continue
            ex = row.get("export_usd")
            im = row.get("import_usd")
            if ex is None and im is None:
                continue
            y = row.get("period")
            try:
                y = int(y) if y is not None else None
            except Exception:
                y = None
            try:
                exv = float(ex) if ex is not None else None
            except Exception:
                exv = None
            try:
                imv = float(im) if im is not None else None
            except Exception:
                imv = None
            return y, exv, imv
        return None, None, None

    rows: list[dict[str, Any]] = []
    years = []
    all_snaps = get_latest_snapshots_by_key(db, "trade_exim_5y")
    for geo, snap in all_snaps.items():
        if not snap or not isinstance(snap.payload, dict):
            continue
        y, ex, im = latest_point(snap.payload)
        if y:
            years.append(y)
        bal = None
        if ex is not None or im is not None:
            bal = (ex or 0.0) - (im or 0.0)
        rows.append(
            {
                "geo": geo,
                "year": y,
                "export_usd": ex,
                "import_usd": im,
                "balance_usd": bal,
                "source": snap.source,
                "source_updated_at": snap.source_updated_at.isoformat() if snap.source_updated_at else None,
            }
        )

    # Optional top_n selection by trade volume = export + import.
    # For 'top 5 countries', we exclude the aggregate 'Global' row.
    if top_n and top_n > 0:
        filtered = [r for r in rows if r.get("geo") not in ("Global", "global")]

        def keyfn(r: dict[str, Any]) -> float:
            ex = float(r.get("export_usd") or 0.0)
            im = float(r.get("import_usd") or 0.0)
            return ex + im

        rows = sorted(filtered, key=keyfn, reverse=True)[: int(top_n)]

    year_mode = max(years) if years else None
    return {"ok": True, "year": year_mode, "rows": rows}


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, msg: str = "", db: Session = Depends(get_db)):
    jobs = []
    rows = list_job_definitions(db)
    rows.sort(key=lambda r: (0 if r.job_id == "generate_homepage_insights" else 1, r.job_id))

    for row in rows:
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
            "allowed_geos": get_allowed_geos(db),
            "allowed_card_keys": sorted(ALLOWED_INSIGHT_CARD_KEYS),
            "allowed_tab_keys": sorted(ALLOWED_INSIGHT_TAB_KEYS),
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


@router.head("/jobs")
def jobs_head():
    return Response(status_code=200)


# --- Geo Dictionary Management ---


def _geos_redirect_url(request: Request, msg: str) -> str:
    base = settings.BASE_PATH.rstrip("/")
    use_prefixed = bool(base) and request.url.path.startswith(f"{base}/")
    path = f"{base}/geos" if use_prefixed else "/geos"
    return f"{path}?msg={quote(msg)}"


@router.get("/geos", response_class=HTMLResponse)
def geos_page(request: Request, msg: str = "", db: Session = Depends(get_db)):
    rows = (
        db.query(GeoDictionary)
        .order_by(GeoDictionary.sort_order, GeoDictionary.geo_name)
        .all()
    )
    return templates.TemplateResponse(
        "geos.html",
        {
            "request": request,
            "base_path": settings.BASE_PATH.rstrip("/"),
            "msg": msg,
            "geos": rows,
            "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        },
    )


@router.post("/geos/add")
def geos_add(
    request: Request,
    db: Session = Depends(get_db),
    geo_name: str = Form(...),
    iso_alpha2: str = Form(default=""),
    iso_alpha3: str = Form(default=""),
    wdi_code: str = Form(default=""),
    display_name: str = Form(default=""),
    region: str = Form(default=""),
    sort_order: int = Form(default=100),
):
    geo_name = geo_name.strip()
    if not geo_name:
        return RedirectResponse(url=_geos_redirect_url(request, "geo_name is required"), status_code=303)
    existing = db.get(GeoDictionary, geo_name)
    if existing:
        return RedirectResponse(url=_geos_redirect_url(request, f"'{geo_name}' already exists"), status_code=303)
    db.add(GeoDictionary(
        geo_name=geo_name,
        iso_alpha2=iso_alpha2.strip(),
        iso_alpha3=iso_alpha3.strip(),
        wdi_code=wdi_code.strip(),
        display_name=display_name.strip() or geo_name,
        region=region.strip(),
        enabled=True,
        sort_order=sort_order,
    ))
    db.commit()
    return RedirectResponse(url=_geos_redirect_url(request, f"Added '{geo_name}'"), status_code=303)


@router.post("/geos/update")
def geos_update(
    request: Request,
    db: Session = Depends(get_db),
    geo_name: str = Form(...),
    iso_alpha2: str = Form(default=""),
    iso_alpha3: str = Form(default=""),
    wdi_code: str = Form(default=""),
    display_name: str = Form(default=""),
    region: str = Form(default=""),
    enabled: str | None = Form(default=None),
    sort_order: int = Form(default=100),
):
    row = db.get(GeoDictionary, geo_name.strip())
    if not row:
        return RedirectResponse(url=_geos_redirect_url(request, f"'{geo_name}' not found"), status_code=303)
    row.iso_alpha2 = iso_alpha2.strip()
    row.iso_alpha3 = iso_alpha3.strip()
    row.wdi_code = wdi_code.strip()
    row.display_name = display_name.strip() or geo_name
    row.region = region.strip()
    row.enabled = (enabled == "on")
    row.sort_order = sort_order
    db.commit()
    return RedirectResponse(url=_geos_redirect_url(request, f"Updated '{geo_name}'"), status_code=303)


@router.post("/geos/delete")
def geos_delete(
    request: Request,
    db: Session = Depends(get_db),
    geo_name: str = Form(...),
):
    row = db.get(GeoDictionary, geo_name.strip())
    if row:
        db.delete(row)
        db.commit()
        return RedirectResponse(url=_geos_redirect_url(request, f"Deleted '{geo_name}'"), status_code=303)
    return RedirectResponse(url=_geos_redirect_url(request, f"'{geo_name}' not found"), status_code=303)


@router.head("/geos")
def geos_head():
    return Response(status_code=200)


def _register_base_path_aliases() -> None:
    base = settings.BASE_PATH.rstrip("/")
    if not base or base == "/":
        return

    alias_specs = [
        {"path": base, "endpoint": homepage, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_homepage_root"},
        {"path": f"{base}/", "endpoint": homepage, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_homepage_slash"},
        {"path": f"{base}/health", "endpoint": health, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_health"},
        {"path": f"{base}/v2", "endpoint": homepage_v2, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_homepage_v2"},
        {"path": f"{base}/v3", "endpoint": homepage_v3, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_homepage_v3"},
        {"path": f"{base}/v4", "endpoint": homepage_v4, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_homepage_v4"},
        {"path": f"{base}/v5", "endpoint": homepage_v5, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_homepage_v5"},
        {"path": f"{base}/v5_1", "endpoint": homepage_v5_1, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_homepage_v5_1"},
        {"path": f"{base}/v5_2", "endpoint": homepage_v5_2, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_homepage_v5_2"},
        {"path": f"{base}/v5_3", "endpoint": homepage_v5_3, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_homepage_v5_3"},
        {"path": f"{base}/v6", "endpoint": homepage_v6, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_homepage_v6"},
        {"path": f"{base}/v7", "endpoint": homepage_v7, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_homepage_v7"},
        {"path": f"{base}/map/trade-flow", "endpoint": trade_flow_map, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_trade_flow_map"},
        {"path": f"{base}/map/trade-flow-top5", "endpoint": trade_flow_map_top5, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_trade_flow_map_top5"},
        {"path": f"{base}/api/trade/corridors", "endpoint": api_trade_corridors, "methods": ["GET"], "name": "prefixed_api_trade_corridors"},
        {"path": f"{base}/api/trade/exim-latest-all", "endpoint": api_trade_exim_latest_all, "methods": ["GET"], "name": "prefixed_api_trade_exim_latest_all"},
        {"path": f"{base}/api/trade/refresh", "endpoint": api_trade_refresh, "methods": ["POST"], "name": "prefixed_api_trade_refresh"},
        {"path": f"{base}/api/trade/exim-5y", "endpoint": api_trade_exim_5y, "methods": ["GET"], "name": "prefixed_api_trade_exim_5y"},
        {"path": f"{base}/api/wealth/proxy", "endpoint": api_wealth_proxy, "methods": ["GET"], "name": "prefixed_api_wealth_proxy"},
        {"path": f"{base}/api/finance/big-transactions", "endpoint": api_finance_big_transactions, "methods": ["GET"], "name": "prefixed_api_finance_big_transactions"},
        {"path": f"{base}/api/wealth/indicators-5y", "endpoint": api_wealth_indicators_5y, "methods": ["GET"], "name": "prefixed_api_wealth_indicators_5y"},
        {"path": f"{base}/api/wealth/disposable-latest", "endpoint": api_wealth_disposable_latest, "methods": ["GET"], "name": "prefixed_api_wealth_disposable_latest"},
        {"path": f"{base}/api/wealth/age-structure-latest", "endpoint": api_wealth_age_structure_latest, "methods": ["GET"], "name": "prefixed_api_wealth_age_structure_latest"},
        {"path": f"{base}/api/finance/ma/industry", "endpoint": api_finance_ma_industry, "methods": ["GET"], "name": "prefixed_api_finance_ma_industry"},
        {"path": f"{base}/api/finance/ma/country", "endpoint": api_finance_ma_country, "methods": ["GET"], "name": "prefixed_api_finance_ma_country"},
        {"path": f"{base}/jobs", "endpoint": jobs_page, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_jobs_page"},
        {"path": f"{base}/jobs", "endpoint": jobs_head, "methods": ["HEAD"], "response_class": HTMLResponse, "name": "prefixed_jobs_head"},
        {"path": f"{base}/jobs/run", "endpoint": jobs_run, "methods": ["POST"], "name": "prefixed_jobs_run"},
        {"path": f"{base}/jobs/update", "endpoint": jobs_update, "methods": ["POST"], "name": "prefixed_jobs_update"},
        {"path": f"{base}/geos", "endpoint": geos_page, "methods": ["GET", "HEAD"], "response_class": HTMLResponse, "name": "prefixed_geos_page"},
        {"path": f"{base}/geos", "endpoint": geos_head, "methods": ["HEAD"], "response_class": HTMLResponse, "name": "prefixed_geos_head"},
        {"path": f"{base}/geos/add", "endpoint": geos_add, "methods": ["POST"], "name": "prefixed_geos_add"},
        {"path": f"{base}/geos/update", "endpoint": geos_update, "methods": ["POST"], "name": "prefixed_geos_update"},
        {"path": f"{base}/geos/delete", "endpoint": geos_delete, "methods": ["POST"], "name": "prefixed_geos_delete"},
    ]

    for spec in alias_specs:
        kwargs = {
            "endpoint": spec["endpoint"],
            "methods": spec["methods"],
            "include_in_schema": False,
            "name": spec["name"],
        }
        # Only pass response_class when explicitly provided; passing None breaks FastAPI.
        if "response_class" in spec and spec["response_class"] is not None:
            kwargs["response_class"] = spec["response_class"]

        router.add_api_route(spec["path"], **kwargs)


_register_base_path_aliases()
