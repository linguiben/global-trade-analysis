from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
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
