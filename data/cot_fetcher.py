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

# Column aliases: CFTC has used slightly different names across file formats.
# Each key is our canonical name; value is a list of known alternatives.
_COL_ALIASES: dict[str, list[str]] = {
    "Market_and_Exchange_Names":   [
        "Market_and_Exchange_Names",
        "Market and Exchange Names",
    ],
    "As_of_Date_In_Form_YYMMDD":   [
        "As_of_Date_In_Form_YYMMDD",
        "As_of_Date_in_Form_YYMMDD",
        "As of Date in Form YYMMDD",
        "Report_Date_as_YYYY-MM-DD",
        "As of Date in Form YYYY-MM-DD",
    ],
    "NonComm_Positions_Long_All":  [
        "NonComm_Positions_Long_All",
        "Noncomm_Positions_Long_All",
        "Noncommercial Positions-Long (All)",
    ],
    "NonComm_Positions_Short_All": [
        "NonComm_Positions_Short_All",
        "Noncomm_Positions_Short_All",
        "Noncommercial Positions-Short (All)",
    ],
    "Comm_Positions_Long_All":     [
        "Comm_Positions_Long_All",
        "Commercial Positions-Long (All)",
    ],
    "Comm_Positions_Short_All":    [
        "Comm_Positions_Short_All",
        "Commercial Positions-Short (All)",
    ],
}


def _resolve_columns(actual_cols: list[str]) -> dict[str, str] | None:
    """Map our canonical column names to whatever the file actually calls them.

    Returns {canonical: actual} or None if any required column is missing.
    """
    actual_set = set(actual_cols)
    mapping: dict[str, str] = {}
    for canonical, aliases in _COL_ALIASES.items():
        found = next((a for a in aliases if a in actual_set), None)
        if found is None:
            return None
        mapping[canonical] = found
    return mapping


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
        # Try "annual.txt" first; fall back to first .txt file in the archive
        txt_files = [n for n in zf.namelist() if n.lower().endswith(".txt")]
        inner_name = "annual.txt" if "annual.txt" in txt_files else (txt_files[0] if txt_files else None)
        if inner_name is None:
            log.warning("COT %d: no .txt file found inside ZIP (%s)", year, zf.namelist())
            return None
        with zf.open(inner_name) as f:
            raw = pd.read_csv(f, dtype=str, low_memory=False)
    except Exception as exc:
        log.warning("COT parse failed for %d: %s", year, exc)
        return None

    col_map = _resolve_columns(list(raw.columns))
    if col_map is None:
        log.warning(
            "COT %d: unrecognised column names in '%s'. Found: %s",
            year, inner_name, list(raw.columns)[:10],
        )
        return None

    # Rename to canonical names so the rest of the code is unchanged
    raw = raw.rename(columns={v: k for k, v in col_map.items()})

    rows = []
    for _, row in raw.iterrows():
        name = str(row["Market_and_Exchange_Names"]).strip()
        if name not in CONTRACT_MAP:
            continue
        symbol = CONTRACT_MAP[name]
        try:
            date_val = str(row["As_of_Date_In_Form_YYMMDD"]).strip()
            # Support both YYMMDD (e.g. "260101") and YYYY-MM-DD (e.g. "2026-01-01")
            if "-" in date_val:
                report_date = datetime.strptime(date_val[:10], "%Y-%m-%d").date().isoformat()
            else:
                report_date = datetime.strptime(date_val.zfill(6), "%y%m%d").date().isoformat()
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
