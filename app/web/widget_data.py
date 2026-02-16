from __future__ import annotations

from datetime import datetime, timezone

from app.web.external_sources import fetch_drewry_wci


def refresh_trade_flow_sources() -> dict:
    # Force-refresh upstream-derived data (best-effort).
    wci = fetch_drewry_wci(force=True)
    return {"wci": wci}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def trade_corridors_mvp(force_wci: bool = False) -> dict:
    # MVP stub. TODO: integrate UN Comtrade (monthly) + WITS/WB where possible + IMF PortWatch.
    geos = ["Global", "China", "United States", "Japan", "Germany",
            "United Kingdom", "India", "Mexico", "Singapore", "Hong Kong"]

    by_geo = {
        "Global": {
            "period": "2025 (example)",
            "value_usd_top": [
                {"rank": 1, "origin": "CN", "dest": "US", "value_usd": 575_000_000_000},
                {"rank": 2, "origin": "DE", "dest": "US", "value_usd": 160_000_000_000},
                {"rank": 3, "origin": "MX", "dest": "US", "value_usd": 155_000_000_000},
                {"rank": 4, "origin": "JP", "dest": "US", "value_usd": 135_000_000_000},
                {"rank": 5, "origin": "CN", "dest": "JP", "value_usd": 130_000_000_000},
                {"rank": 6, "origin": "IN", "dest": "US", "value_usd": 85_000_000_000},
                {"rank": 7, "origin": "CN", "dest": "DE", "value_usd": 78_000_000_000},
                {"rank": 8, "origin": "GB", "dest": "US", "value_usd": 65_000_000_000},
                {"rank": 9, "origin": "HK", "dest": "CN", "value_usd": 42_000_000_000},
                {"rank": 10, "origin": "SG", "dest": "CN", "value_usd": 35_000_000_000},
            ],
            "volume_top": [
                {"rank": 1, "origin": "CN", "dest": "US", "volume_kg": 92_000_000_000},
                {"rank": 2, "origin": "CN", "dest": "VN", "volume_kg": 45_000_000_000},
                {"rank": 3, "origin": "US", "dest": "CA", "volume_kg": 40_000_000_000},
                {"rank": 4, "origin": "CN", "dest": "JP", "volume_kg": 38_000_000_000},
                {"rank": 5, "origin": "DE", "dest": "US", "volume_kg": 22_000_000_000},
            ],
            "export_usd": 25_600_000_000_000,
            "import_usd": 26_200_000_000_000,
        },
        "China": {
            "period": "2025 (example)",
            "value_usd_top": [
                {"rank": 1, "origin": "CN", "dest": "US", "value_usd": 575_000_000_000},
                {"rank": 2, "origin": "CN", "dest": "JP", "value_usd": 130_000_000_000},
                {"rank": 3, "origin": "CN", "dest": "DE", "value_usd": 78_000_000_000},
            ],
            "volume_top": [
                {"rank": 1, "origin": "CN", "dest": "US", "volume_kg": 92_000_000_000},
                {"rank": 2, "origin": "CN", "dest": "VN", "volume_kg": 45_000_000_000},
                {"rank": 3, "origin": "CN", "dest": "JP", "volume_kg": 38_000_000_000},
            ],
            "export_usd": 3_600_000_000_000,
            "import_usd": 2_700_000_000_000,
        },
        "United States": {
            "period": "2025 (example)",
            "value_usd_top": [
                {"rank": 1, "origin": "US", "dest": "CA", "value_usd": 320_000_000_000},
                {"rank": 2, "origin": "US", "dest": "MX", "value_usd": 265_000_000_000},
                {"rank": 3, "origin": "US", "dest": "CN", "value_usd": 150_000_000_000},
            ],
            "volume_top": [
                {"rank": 1, "origin": "US", "dest": "CA", "volume_kg": 40_000_000_000},
                {"rank": 2, "origin": "US", "dest": "MX", "volume_kg": 28_000_000_000},
            ],
            "export_usd": 2_100_000_000_000,
            "import_usd": 3_300_000_000_000,
        },
        "Japan": {
            "period": "2025 (example)",
            "value_usd_top": [
                {"rank": 1, "origin": "JP", "dest": "US", "value_usd": 135_000_000_000},
                {"rank": 2, "origin": "JP", "dest": "CN", "value_usd": 120_000_000_000},
                {"rank": 3, "origin": "JP", "dest": "KR", "value_usd": 52_000_000_000},
            ],
            "volume_top": [
                {"rank": 1, "origin": "JP", "dest": "CN", "volume_kg": 18_000_000_000},
                {"rank": 2, "origin": "JP", "dest": "US", "volume_kg": 15_000_000_000},
            ],
            "export_usd": 920_000_000_000,
            "import_usd": 950_000_000_000,
        },
        "Germany": {
            "period": "2025 (example)",
            "value_usd_top": [
                {"rank": 1, "origin": "DE", "dest": "US", "value_usd": 160_000_000_000},
                {"rank": 2, "origin": "DE", "dest": "FR", "value_usd": 120_000_000_000},
                {"rank": 3, "origin": "DE", "dest": "CN", "value_usd": 105_000_000_000},
            ],
            "volume_top": [
                {"rank": 1, "origin": "DE", "dest": "US", "volume_kg": 22_000_000_000},
                {"rank": 2, "origin": "DE", "dest": "FR", "volume_kg": 18_000_000_000},
            ],
            "export_usd": 1_800_000_000_000,
            "import_usd": 1_500_000_000_000,
        },
        "United Kingdom": {
            "period": "2025 (example)",
            "value_usd_top": [
                {"rank": 1, "origin": "GB", "dest": "US", "value_usd": 65_000_000_000},
                {"rank": 2, "origin": "GB", "dest": "DE", "value_usd": 45_000_000_000},
                {"rank": 3, "origin": "GB", "dest": "NL", "value_usd": 38_000_000_000},
            ],
            "volume_top": [
                {"rank": 1, "origin": "GB", "dest": "US", "volume_kg": 8_000_000_000},
                {"rank": 2, "origin": "GB", "dest": "DE", "volume_kg": 6_500_000_000},
            ],
            "export_usd": 530_000_000_000,
            "import_usd": 780_000_000_000,
        },
        "India": {
            "period": "2025 (example)",
            "value_usd_top": [{"rank": 1, "origin": "IN", "dest": "US", "value_usd": 85_000_000_000}],
            "volume_top": [{"rank": 1, "origin": "IN", "dest": "AE", "volume_kg": 9_200_000_000}],
            "export_usd": 780_000_000_000,
            "import_usd": 980_000_000_000,
        },
        "Mexico": {
            "period": "2025 (example)",
            "value_usd_top": [{"rank": 1, "origin": "MX", "dest": "US", "value_usd": 155_000_000_000}],
            "volume_top": [{"rank": 1, "origin": "MX", "dest": "US", "volume_kg": 11_500_000_000}],
            "export_usd": 670_000_000_000,
            "import_usd": 650_000_000_000,
        },
        "Singapore": {
            "period": "2025 (example)",
            "value_usd_top": [{"rank": 1, "origin": "SG", "dest": "CN", "value_usd": 35_000_000_000}],
            "volume_top": [{"rank": 1, "origin": "SG", "dest": "MY", "volume_kg": 2_100_000_000}],
            "export_usd": 520_000_000_000,
            "import_usd": 480_000_000_000,
        },
        "Hong Kong": {
            "period": "2025 (example)",
            "value_usd_top": [{"rank": 1, "origin": "HK", "dest": "CN", "value_usd": 42_000_000_000}],
            "volume_top": [{"rank": 1, "origin": "HK", "dest": "CN", "volume_kg": 1_400_000_000}],
            "export_usd": 620_000_000_000,
            "import_usd": 690_000_000_000,
        },
    }

    # Convenience: compute surplus/deficit for each geo.
    for geo, d in by_geo.items():
        d["trade_balance_usd"] = (d.get("export_usd") or 0) - (d.get("import_usd") or 0)

    return {
        "source": "MVP stub (planned: UN Comtrade / WITS / UNCTAD / PortWatch)",
        "updated_at": utc_now_iso(),
        "geos": geos,
        "by_geo": by_geo,
        "wci": fetch_drewry_wci(force=force_wci),
        "portwatch": {
            "source": "Planned: IMF PortWatch",
            "period": "2026-02 (example)",
            "commentary": "Placeholder until PortWatch integration.",
        },
        "notes": [
            "This is an MVP scaffold: numbers are placeholders until data sources are wired.",
            "We show value and volume separately; volume may be missing for some corridors in real data.",
        ],
    }


def wealth_proxy_mvp() -> dict:
    # MVP proxy stub. TODO: integrate UN WPP (age structure) + WB/OECD for income/consumption proxies.
    countries = ["India", "Mexico", "Singapore", "Hong Kong"]
    return {
        "source": "MVP proxy stub (planned: UN WPP + World Bank/OECD where available)",
        "updated_at": utc_now_iso(),
        "countries": countries,
        "age_buckets": ["18-34", "35-54", "55+"],
        "wealth_share_proxy": {
            "India": [22, 38, 40],
            "Mexico": [18, 34, 48],
            "Singapore": [15, 33, 52],
            "Hong Kong": [12, 30, 58],
        },
        "spending_share_proxy": {
            "India": [34, 44, 22],
            "Mexico": [30, 46, 24],
            "Singapore": [26, 48, 26],
            "Hong Kong": [24, 45, 31],
        },
        "shift_pace_proxy": {
            "India": +1.8,
            "Mexico": +1.2,
            "Singapore": +0.6,
            "Hong Kong": +0.4,
        },
        "notes": [
            "This widget uses proxies until a consistent, open, cross-country wealth-by-age dataset is confirmed.",
        ],
    }


def finance_big_transactions_mvp() -> dict:
    # MVP stub. TODO: integrate GDELT 2.1 feed + extraction with source links.
    return {
        "source": "MVP stub (planned: GDELT 2.1 + public filings)",
        "updated_at": utc_now_iso(),
        "transactions": [
            {
                "date": "2026-02-12",
                "type": "M&A (example)",
                "headline": "Example mega-deal headline",
                "value_usd": 48_000_000_000,
                "region": "Global",
                "link": "https://example.com",
            },
            {
                "date": "2026-02-11",
                "type": "Debt issuance (example)",
                "headline": "Example bond issuance",
                "value_usd": 12_500_000_000,
                "region": "APAC",
                "link": "https://example.com",
            },
        ],
        "notes": [
            "Near-real-time is feasible via news feeds but will contain noise; always show source links.",
        ],
    }
