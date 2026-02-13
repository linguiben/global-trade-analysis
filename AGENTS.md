# Repository Guidelines

## Project Structure & Module Organization
- `app/main.py`: FastAPI app entrypoint, router registration, and static/test mounts.
- `app/web/routes.py`: homepage and internal API routes (`/api/...`).
- `app/web/templates/dashboard.html`: main UI (reads internal APIs / server-rendered snapshots; no direct external data calls).
- `app/web/worldbank.py`, `app/web/worldpopreview.py`, `app/web/external_sources.py`, `app/web/imaa.py`: upstream data adapters and parsing logic.
- `app/jobs/runtime.py`: job runners + scheduler wiring (including `generate_homepage_insights`).
- `app/db/`: SQLAlchemy session/model definitions.
- `app/web/test/`: lightweight HTML prototype pages.
- `doc/`: business/domain notes. Runtime config lives in `.env` (see `env.example`).

## Build, Test, and Development Commands
- Install deps:
  - `python -m venv .venv && source .venv/bin/activate`
  - `pip install -r requirements.txt`
- Run locally (dev reload):
  - `uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload`
- Run with Docker:
  - `docker compose up -d --build`
- Quick health check:
  - `curl http://localhost:9000/health`
- Smoke-check key APIs:
  - `curl http://localhost:9000/api/trade/corridors`
  - `curl "http://localhost:9000/api/wealth/indicators-5y?geo=Global"`

## Coding Style & Naming Conventions
- Follow existing Python style: 4-space indentation, PEP 8 naming, type hints where practical.
- Use `snake_case` for functions/variables, `PascalCase` for ORM models.
- Keep route handlers thin; place external-fetch/parsing logic in `app/web/*` helper modules.
- Keep imports grouped as standard library, third-party, then local modules.
- Match existing frontend conventions in `dashboard.html` (`id`/function names aligned to API payload fields).

## Testing Guidelines
- No formal automated test suite is currently configured; use focused smoke tests for route/API changes.
- For parser changes, validate both success and fallback paths (timeouts, empty rows, cache behavior).
- If adding automated tests, use `pytest` with files named `test_*.py` under a new `tests/` directory.

## Commit & Pull Request Guidelines
- Use short, imperative commit subjects, optionally scoped (examples from history: `Fix ...`, `Add ...`, `Use ...`).
- Keep each commit focused on one logical change.
- PRs should include:
  - what changed and why,
  - impacted endpoints/files,
  - manual verification steps (commands/cURLs),
  - UI screenshots for dashboard template changes.

## Security & Configuration Tips
- Copy `env.example` to `.env` and keep secrets out of git.
- Do not hardcode credentials or tokens.
- Preserve request timeouts/caching for external sources to avoid unstable or excessive upstream calls.
