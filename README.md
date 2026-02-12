# global-trade-analysis (GTA)

A lightweight web homepage scaffold for **Global Trade Analysis**.

## Run (Docker)

```bash
docker compose up -d --build
```

- Web: http://localhost:9000
- PostgreSQL: localhost:9527

Workspace for analyzing global trade data (imports/exports, HS/SITC codes, partners, time series).

## Structure
- `notebooks/` — exploratory notebooks
- `src/` — reusable code
- `data/raw/` — raw inputs (keep large files out of git)
- `data/processed/` — derived datasets
- `reports/` — writeups / exports
- `figures/` — charts

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
