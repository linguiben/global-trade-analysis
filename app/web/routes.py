from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.web import widget_data
from app.web.worldbank import fetch_trade_exim_5y
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import UserVisitLog
from app.db.session import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


def _client_ip(request: Request) -> str:
    # Prefer reverse-proxy header if present; otherwise fall back to peer.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.get("/", response_class=HTMLResponse)
def homepage(request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]

    db.add(UserVisitLog(ip=ip, user_agent=ua))
    db.commit()

    visited_count = db.query(func.count(UserVisitLog.id)).scalar() or 0

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "base_path": settings.BASE_PATH.rstrip("/"),
            "visited_count": visited_count,
            "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        },
    )


@router.get("/health", response_class=HTMLResponse)
def health():
    return "OK"


# --- Widget APIs (MVP stubs) ---


@router.get("/api/trade/corridors")
def api_trade_corridors():
    return widget_data.trade_corridors_mvp()


@router.post("/api/trade/refresh")
def api_trade_refresh():
    # This endpoint is intended for scheduled refresh (e.g., 09:00 daily).
    # It forces upstream pulls (WCI now; more sources later).
    return {
        "ok": True,
        "refreshed_at": widget_data.utc_now_iso(),
        "details": widget_data.refresh_trade_flow_sources(),
    }


@router.get("/api/trade/exim-5y")
def api_trade_exim_5y(geo: str = "Global"):
    # Annual fallback via World Bank WDI (nominal USD)
    geo_map = {
        "Global": "WLD",
        "India": "IND",
        "Mexico": "MEX",
        "Singapore": "SGP",
        "Hong Kong": "HKG",
    }
    country = geo_map.get(geo, "WLD")

    # derive end_year from UTC date (safe, close enough; WDI may lag)
    from datetime import datetime, timezone

    end_year = datetime.now(timezone.utc).year - 1
    return fetch_trade_exim_5y(country, end_year=end_year, years=5)


@router.get("/api/wealth/proxy")
def api_wealth_proxy():
    return widget_data.wealth_proxy_mvp()


@router.get("/api/finance/big-transactions")
def api_finance_big_transactions():
    return widget_data.finance_big_transactions_mvp()
