# global-trade-analysis (GTA)

A lightweight web homepage scaffold for **Global Trade Analysis**.

## Run (Docker)

```bash
docker compose up -d --build
```

- Web: http://localhost:9000
- PostgreSQL: localhost:9527

Workspace for analyzing global trade data (imports/exports, HS/SITC codes, partners, time series).

## Redeploy
喺 gta 項目目錄直接 redeploy（build + restart）：

```bash
cd /opt/repo/global-trade-analysis
docker compose up -d --build
```

可選：確認狀態/睇 logs

```bash
docker compose ps
docker compose logs -f --tail=100 web
```

## App Structure
- `app/main.py` — FastAPI entry and lifecycle.
- `app/web/routes.py` — page routes and API routes.
- `app/web/templates/dashboard.html` — homepage (display-only; no browser-side data fetch).
- `app/jobs/runtime.py` — APScheduler jobs, parameter normalization, DB persistence.
- `app/db/models.py` — ORM models.
- `init_db.sql` — schema baseline (must include all tables).
- `init.py` — idempotent SQL initializer at container startup.

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload
```

## Job Scheduling
- Jobs are persisted in DB and managed at `/gta/jobs`.
- By default, **all jobs run every 10 minutes** (`*/10 * * * *`).
- You can override cron/params per job from `/gta/jobs`.

### Global Job Switch
Add this to `.env` (from `env.example`):
```bash
JOBS_ENABLED=true
```
- `true`: scheduler starts and jobs can run.
- `false`: scheduler does not start; manual/job API execution is also blocked.

## Job Inventory
All jobs live in `app/jobs/runtime.py` (`JOB_SPECS`).

> Note: Current product requirement enforces a global cadence of **every 10 minutes**.


1. `trade_corridors`
   - Refreshes trade corridors summary; includes Drewry WCI extraction.
   - Default params: `{"force_wci": false}`
2. `trade_exim_5y`
   - Refreshes WDI export/import 5Y series for configured geos.
   - Default params: `{"geo_list": [...], "years": 5, "end_year": null, "force": false}`
3. `wealth_indicators_5y`
   - Refreshes WDI GDP-per-capita and consumption 5Y series.
   - Default params: `{"geo_list": [...], "years": 5, "end_year": null, "force": false}`
4. `wealth_disposable_latest`
   - Refreshes disposable-income-like latest snapshot (WPR + WB fallback).
   - Default params: `{"force": false}`
5. `finance_ma_industry`
   - Refreshes IMAA industry ranking snapshot.
   - Default params: `{"force": false}`
6. `finance_ma_country`
   - Refreshes IMAA country snapshot.
   - Default params: `{"force": false}`
7. `cleanup_snapshots`
   - Removes snapshots and run logs older than retention window.
   - Default params: `{"keep_days": 30}`
8. `generate_homepage_insights`
   - Generates “Insight” text for homepage cards/tabs and stores it in DB.
   - Output table: `widget_insights`

## External Data Sources
Below are the external data sources currently used by the application jobs.

### Active Sources (in use)
1. **World Bank API (WDI)**
   - URL base: `https://api.worldbank.org/v2`
   - Usage: trade and wealth time series, plus fallback proxy for disposable-income-like metric.
   - Key indicators:
     - `NE.EXP.GNFS.CD` (exports, current US$)
     - `NE.IMP.GNFS.CD` (imports, current US$)
     - `NY.GDP.PCAP.CD` (GDP per capita, current US$)
     - `NE.CON.PRVT.CD` (household final consumption, current US$)
     - `NE.CON.PRVT.PC.KD` (fallback proxy, per-capita constant 2015 US$)
   - Notes: API JSON pull with in-process cache.

2. **World Population Review (WPR)**
   - URL: `https://worldpopulationreview.com/country-rankings/disposable-income-by-country`
   - Usage: best-effort scrape for latest disposable-income-style values.
   - Notes: if parsing misses geos, system auto-falls back to World Bank proxy.

3. **Drewry World Container Index (WCI)**
   - URL: `https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry`
   - Usage: shipping/freight signal for trade widget.
   - Notes: HTML parsing of headline value/change and selected lane commentary.

4. **IMAA Institute**
   - URLs:
     - Industry stats: `https://imaa-institute.org/mergers-and-acquisitions-statistics/ma-statistics-by-industries/`
     - Country stats: `https://imaa-institute.org/mergers-and-acquisitions-statistics/ma-statistics-by-countries/`
   - Usage: M&A flow breakdown by industry and country.
   - Notes: parsed from public HTML tables/narratives (best-effort).

### Planned / Placeholder Sources (not yet wired)
- IMF PortWatch
- UN Comtrade / WITS / UNCTAD
- GDELT 2.1 (news/event feed)
