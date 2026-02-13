from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.jobs import init_scheduler, shutdown_scheduler
from app.web.routes import router as web_router

favicon_path = Path("app/web/static/favicon.ico")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="Global Trade Analysis", lifespan=lifespan)

# Static files
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

# When running behind nginx under a base path (e.g. /gta), we also expose
# base-prefixed static routes so pages under /gta/* can load assets.
from app.config import settings

BASE_PATH = (settings.BASE_PATH or "").rstrip("/")
if BASE_PATH and BASE_PATH != "/":
    app.mount(f"{BASE_PATH}/static", StaticFiles(directory="app/web/static"), name="static_prefixed")

# Test pages
app.mount("/test", StaticFiles(directory="app/web/test", html=True), name="test")
if BASE_PATH and BASE_PATH != "/":
    app.mount(f"{BASE_PATH}/test", StaticFiles(directory="app/web/test", html=True), name="test_prefixed")

app.include_router(web_router)


@app.get("/favicon.ico")
def favicon():
    if favicon_path.exists():
        return FileResponse(favicon_path)
    # Avoid FileResponse on /dev/null (not a regular file in some containers)
    return ""
