"""
[NEW — Step 10] CFTC COT report downloader and parser.

Downloads Legacy Futures-Only COT data from the CFTC website (free, no API key).
Parses EUR, GBP, CHF, JPY currency futures and stores net spec/commercial positions.

Usage:
    seed_cot(db_path)      — called once on startup (downloads current + previous year)
    refresh_cot(db_path)   — called every COT_REFRESH_INTERVAL_SEC (re-fetches current year)
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime

import pandas as pd
import requests

from core import db

log = logging.getLogger(__name__)

# Map CFTC contract names → our FX symbols
CONTRACT_MAP: dict[str, str] = {
    "EURO FX - CHICAGO MERCANTILE EXCHANGE":                "EURUSD",
    "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE": "GBPUSD",
    "SWISS FRANC - CHICAGO MERCANTILE EXCHANGE":            "USDCHF",
    "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE":           "GBPJPY",
}

_CFTC_URL = "https://www.cftc.gov/files/dea/history/deacot{year}.zip"

_REQUIRED_COLS = [
    "Market_and_Exchange_Names",
    "As_of_Date_In_Form_YYMMDD",
    "NonComm_Positions_Long_All",
    "NonComm_Positions_Short_All",
    "Comm_Positions_Long_All",
    "Comm_Positions_Short_All",
]


def _download_year(year: int) -> pd.DataFrame | None:
    """Download and parse the CFTC annual COT ZIP for `year`.

    Returns a DataFrame with columns: report_date, symbol, net_spec, net_comm.
    Returns None on failure (network error, bad year, missing file, etc.).
    """
    url = _CFTC_URL.format(year=year)
    try:
        resp = requests.get(url, timeout=30)
    except requests.RequestException as exc:
        log.warning("COT download failed for %d: %s", year, exc)
        return None

    if not resp.ok:
        log.warning("COT download %d -> HTTP %s", year, resp.status_code)
        return None

    try:
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        # The file inside is always named "annual.txt"
        with zf.open("annual.txt") as f:
            raw = pd.read_csv(f, usecols=_REQUIRED_COLS, dtype=str, low_memory=False)
    except Exception as exc:
        log.warning("COT parse failed for %d: %s", year, exc)
        return None

    rows = []
    for _, row in raw.iterrows():
        name = str(row["Market_and_Exchange_Names"]).strip()
        if name not in CONTRACT_MAP:
            continue
        symbol = CONTRACT_MAP[name]
        try:
            date_str = str(row["As_of_Date_In_Form_YYMMDD"]).strip().zfill(6)
            report_date = datetime.strptime(date_str, "%y%m%d").date().isoformat()
            net_spec = float(row["NonComm_Positions_Long_All"]) - float(row["NonComm_Positions_Short_All"])
            net_comm = float(row["Comm_Positions_Long_All"])    - float(row["Comm_Positions_Short_All"])
        except (ValueError, TypeError) as exc:
            log.debug("Skipping malformed COT row for %s: %s", symbol, exc)
            continue

        rows.append({
            "report_date": report_date,
            "symbol":      symbol,
            "net_spec":    net_spec,
            "net_comm":    net_comm,
        })

    if not rows:
        log.warning("COT %d: no matching contracts found in file", year)
        return None

    df = pd.DataFrame(rows)
    log.info("COT %d: parsed %d rows for %s", year, len(df),
             ", ".join(df["symbol"].unique().tolist()))
    return df


def seed_cot(db_path: str) -> int:
    """Download current year + previous year COT data on startup.

    Skips any report dates already in the DB (INSERT OR IGNORE).
    Safe to call on every startup — returns total rows inserted.
    """
    current_year  = datetime.now().year
    total_inserted = 0

    for year in (current_year - 1, current_year):
        df = _download_year(year)
        if df is None:
            continue
        inserted = db.save_cot(db_path, df.to_dict("records"))
        total_inserted += inserted
        log.info("COT seed %d: %d rows saved", year, inserted)

    return total_inserted


def refresh_cot(db_path: str) -> int:
    """Re-download current year only (CFTC updates weekly).

    New report dates are added; existing ones are silently skipped.
    Returns number of rows saved.
    """
    current_year = datetime.now().year
    df = _download_year(current_year)
    if df is None:
        return 0
    inserted = db.save_cot(db_path, df.to_dict("records"))
    log.info("COT refresh %d: %d rows saved", current_year, inserted)
    return inserted
