"""
[NEW — Step 11] Economic calendar / news event filter.

Pauses ALL new signal entry within NEWS_PAUSE_MINUTES before AND after any
high-impact scheduled release.  This is a gate-only module — it never generates
signals, never modifies risk, and never affects open positions.

Built-in coverage (no API key required):
    - US NFP (Non-Farm Payrolls): first Friday of every month at 13:30 UTC

Optional API coverage (requires FMP_API_KEY env var):
    - Full forward-looking economic calendar via financialmodelingprep.com
    - Free tier: 250 requests/day — more than enough for hourly refreshes

User-supplied coverage (no API key required):
    - data/news_events.json — manually maintained list of one-off events
    - Format: [{"date": "2026-06-05", "time_utc": "13:30", "name": "US NFP override"}]

Usage:
    from data.news_filter import is_news_window, refresh_news_cache
    refresh_news_cache(db_path)   # call hourly alongside COT refresh
    if is_news_window(now):
        continue  # skip signal generation

To get a free FMP API key:
    1. Go to https://financialmodelingprep.com/developer/docs
    2. Click "Get my API Key" — free tier gives 250 calls/day (no credit card)
    3. Add to your .env file:  FMP_API_KEY=your_key_here
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

from core import config

log = logging.getLogger(__name__)

# In-memory cache of upcoming high-impact events fetched from FMP
# Format: list of datetime objects (UTC, naive)
_event_cache: list[datetime] = []
_cache_date: Optional[date] = None   # which calendar date the cache covers


# ── Built-in: US NFP ──────────────────────────────────────────────────────────

def _nfp_datetime(year: int, month: int) -> datetime:
    """Return the NFP release datetime for the given year/month.

    US Non-Farm Payrolls: first Friday of every month at 13:30 UTC.
    """
    d = date(year, month, 1)
    days_to_friday = (4 - d.weekday()) % 7   # 4 = Friday in Python's weekday()
    first_friday   = d + timedelta(days=days_to_friday)
    return datetime(year, month, first_friday.day, 13, 30)


def _builtin_events(now: datetime) -> list[datetime]:
    """Return built-in high-impact events for current and adjacent months."""
    events = []
    # NFP this month, last month, and next month (to catch edge-of-month windows)
    for delta_months in (-1, 0, 1):
        y, m = now.year, now.month + delta_months
        if m <= 0:
            y -= 1
            m += 12
        elif m > 12:
            y += 1
            m -= 12
        events.append(_nfp_datetime(y, m))
    return events


# ── User-supplied custom events ────────────────────────────────────────────────

def _load_custom_events(events_file: str) -> list[datetime]:
    """Load datetimes from data/news_events.json.  Returns [] if missing."""
    path = Path(events_file)
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("news_events.json parse error: %s", exc)
        return []
    result = []
    for entry in entries:
        try:
            dt = datetime.fromisoformat(f"{entry['date']}T{entry['time_utc']}")
            result.append(dt)
        except (KeyError, ValueError) as exc:
            log.debug("Skipping malformed news event entry: %s", exc)
    return result


# ── Optional: Financial Modeling Prep API ─────────────────────────────────────

def _fetch_fmp_events(api_key: str, from_date: date, to_date: date) -> list[datetime]:
    """
    Fetch high-impact economic events from FMP economic calendar API.

    Endpoint: GET https://financialmodelingprep.com/api/v3/economic_calendar
    Params: from, to, apikey
    Returns list of UTC datetimes for HIGH-impact events only.

    Free tier key: https://financialmodelingprep.com/developer/docs
    """
    if not api_key:
        return []
    url = "https://financialmodelingprep.com/api/v3/economic_calendar"
    params = {
        "from":    from_date.isoformat(),
        "to":      to_date.isoformat(),
        "apikey":  api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
    except requests.RequestException as exc:
        log.warning("FMP calendar fetch failed: %s", exc)
        return []
    if not resp.ok:
        log.warning("FMP calendar HTTP %s", resp.status_code)
        return []
    events = []
    for item in resp.json():
        try:
            if item.get("impact", "").lower() != "high":
                continue
            # FMP returns date as "2026-06-05 13:30:00"
            dt_str = item.get("date", "")
            dt     = datetime.fromisoformat(dt_str)
            events.append(dt)
        except (ValueError, AttributeError):
            continue
    log.info("FMP calendar: fetched %d high-impact events (%s to %s)",
             len(events), from_date, to_date)
    return events


# ── Cache refresh ──────────────────────────────────────────────────────────────

def refresh_news_cache(now: Optional[datetime] = None) -> None:
    """[NEW — Step 11] Refresh the in-memory event cache.

    Called hourly by the engine (alongside COT refresh).
    Fetches 7-day window from FMP if API key is set; always includes built-ins.
    """
    global _event_cache, _cache_date
    if now is None:
        now = datetime.utcnow()

    today = now.date()
    if _cache_date == today and _event_cache:
        return   # already fresh for today

    events: list[datetime] = []

    # Always include built-in NFP dates
    events.extend(_builtin_events(now))

    # Always include custom user events
    events.extend(_load_custom_events(config.NEWS_EVENTS_FILE))

    # Optionally enrich with FMP full calendar
    if config.FMP_API_KEY:
        fmp_events = _fetch_fmp_events(
            config.FMP_API_KEY,
            from_date=today,
            to_date=today + timedelta(days=7),
        )
        events.extend(fmp_events)

    _event_cache = events
    _cache_date  = today
    log.info("News cache refreshed: %d events loaded (FMP key: %s)",
             len(events), "yes" if config.FMP_API_KEY else "no — NFP only")


# ── Main gate ─────────────────────────────────────────────────────────────────

def is_news_window(
    now: datetime,
    pause_minutes: int = config.NEWS_PAUSE_MINUTES,
) -> bool:
    """Return True if `now` is within `pause_minutes` of any known high-impact event.

    Always checks built-in (NFP) and custom events.
    Also checks FMP-sourced events if the cache has been populated.
    Thread-safe for read — cache is written atomically via refresh_news_cache().
    """
    window = timedelta(minutes=pause_minutes)

    # Combine live built-ins with cached API/custom events
    all_events = list(_event_cache) + _builtin_events(now) + _load_custom_events(config.NEWS_EVENTS_FILE)

    seen: set[datetime] = set()
    for event_dt in all_events:
        if event_dt in seen:
            continue
        seen.add(event_dt)
        if abs(now - event_dt) <= window:
            log.info(
                "NEWS PAUSE: %s is within %d min of event at %s UTC",
                now.strftime("%H:%M"), pause_minutes, event_dt.strftime("%Y-%m-%d %H:%M"),
            )
            return True

    return False
