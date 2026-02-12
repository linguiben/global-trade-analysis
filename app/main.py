from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db.models import Base
from app.db.session import engine
from app.web.routes import router as web_router

favicon_path = Path("app/web/static/favicon.ico")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create minimal tables automatically.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Global Trade Analysis", lifespan=lifespan)

# Static files; when running behind nginx under /gta/, nginx will strip the prefix.
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
app.include_router(web_router)


@app.get("/favicon.ico")
def favicon():
    if favicon_path.exists():
        return FileResponse(favicon_path)
    return FileResponse("/dev/null")
