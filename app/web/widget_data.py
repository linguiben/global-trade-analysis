from __future__ import annotations

from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def trade_corridors_mvp() -> dict:
    # MVP stub. TODO: integrate UN Comtrade (monthly) and optional IMF DOTS.
    return {
        "source": "MVP stub (planned: UN Comtrade / IMF DOTS)",
        "updated_at": utc_now_iso(),
        "value_usd_top": [
            {"rank": 1, "origin": "CN", "dest": "US", "value_usd": 575_000_000_000},
            {"rank": 2, "origin": "DE", "dest": "US", "value_usd": 160_000_000_000},
            {"rank": 3, "origin": "MX", "dest": "US", "value_usd": 155_000_000_000},
        ],
        "volume_top": [
            {"rank": 1, "origin": "CN", "dest": "US", "volume_kg": 92_000_000_000},
            {"rank": 2, "origin": "CN", "dest": "VN", "volume_kg": 45_000_000_000},
            {"rank": 3, "origin": "US", "dest": "CA", "volume_kg": 40_000_000_000},
        ],
        "notes": [
            "Value and volume are shown separately; volume may be missing for some corridors in real data.",
            "Update cadence target: monthly/quarterly depending on source availability.",
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
