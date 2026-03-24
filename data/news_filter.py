"""
[NEW — Step 11] Economic calendar / news event filter.

Pauses ALL new signal entry within NEWS_PAUSE_MINUTES before AND after any
high-impact scheduled release.  This is a gate-only module — it never generates
signals, never modifies risk, and never affects open positions.

Coverage (zero maintenance — fully automatic):
    1. US NFP: first Friday of every month at 13:30 UTC (built-in, no network)
    2. FOMC / BOE / ECB decisions: scraped weekly from official central bank
       websites and saved to data/news_events.json automatically.
       Sources:
         FOMC → https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
         BOE  → https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates
         ECB  → https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html

Optional (paid plan only):
    FMP_API_KEY in .env → full forward-looking economic calendar via
    financialmodelingprep.com/stable/economic-calendar

Usage:
    from data.news_filter import is_news_window, refresh_news_cache
    from data.news_filter import refresh_central_bank_calendar

    refresh_central_bank_calendar()  # call weekly — updates news_events.json
    refresh_news_cache(now)          # call hourly — rebuilds in-memory cache
    if is_news_window(now):
        continue
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

from core import config

log = logging.getLogger(__name__)

# In-memory cache of all upcoming events (UTC naive datetimes)
_event_cache: list[datetime] = []
_cache_date: Optional[date]  = None

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; forex-engine/1.0)"}

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
_MONTH_RE = "|".join(_MONTH_MAP)


# ── DST helpers (for correct UTC conversion) ──────────────────────────────────

def _sundays(year: int, month: int) -> list[date]:
    """All Sundays in the given year/month."""
    import calendar
    _, days_in_month = calendar.monthrange(year, month)
    return [date(year, month, d) for d in range(1, days_in_month + 1)
            if date(year, month, d).weekday() == 6]


def _us_is_dst(d: date) -> bool:
    """True if US EDT (UTC-4) is in effect — 2nd Sunday of March to 1st Sunday of November."""
    y = d.year
    return _sundays(y, 3)[1] <= d < _sundays(y, 11)[0]


def _eu_is_dst(d: date) -> bool:
    """True if CEST (UTC+2) is in effect — last Sunday of March to last Sunday of October."""
    y = d.year
    return _sundays(y, 3)[-1] <= d < _sundays(y, 10)[-1]


def _fomc_utc(d: date) -> str:
    """FOMC announces at 14:00 ET → 19:00 UTC (EST) or 18:00 UTC (EDT)."""
    return "18:00" if _us_is_dst(d) else "19:00"


def _boe_utc(d: date) -> str:
    """BOE announces at 12:00 noon UK → 12:00 UTC (GMT) or 11:00 UTC (BST)."""
    return "11:00" if _eu_is_dst(d) else "12:00"


def _ecb_utc(d: date) -> str:
    """ECB announces at 14:15 CET → 13:15 UTC (CET) or 12:15 UTC (CEST)."""
    return "12:15" if _eu_is_dst(d) else "13:15"


# ── Built-in: US NFP ──────────────────────────────────────────────────────────

def _nfp_datetime(year: int, month: int) -> datetime:
    """US NFP: first Friday of every month at 13:30 UTC."""
    d = date(year, month, 1)
    first_friday = d + timedelta(days=(4 - d.weekday()) % 7)
    return datetime(year, month, first_friday.day, 13, 30)


def _builtin_events(now: datetime) -> list[datetime]:
    """NFP for previous, current, and next month."""
    events = []
    for delta in (-1, 0, 1):
        y, m = now.year, now.month + delta
        if m <= 0:   y -= 1; m += 12
        elif m > 12: y += 1; m -= 12
        events.append(_nfp_datetime(y, m))
    return events


# ── Central bank scrapers ─────────────────────────────────────────────────────

def _scrape_fomc() -> list[dict]:
    """Scrape upcoming FOMC decision dates from federalreserve.gov.

    Page structure: year sections labelled 'YYYY FOMC Meetings', each containing
    rows with class 'fomc-meeting__month' (month name) and 'fomc-meeting__date'
    (day range e.g. '27-28'). Decision = last day of the range.
    """
    url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    try:
        resp = requests.get(url, timeout=15, headers=_HEADERS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("FOMC scrape failed: %s", exc)
        return []

    html  = resp.text
    today = date.today()
    results: list[dict] = []

    # Split into year blocks: "2026 FOMC Meetings", "2025 FOMC Meetings", etc.
    year_blocks = re.split(r'(\d{4})\s+FOMC Meetings', html)
    # year_blocks = [prefix, year1, block1, year2, block2, ...]
    i = 1
    while i < len(year_blocks) - 1:
        try:
            year = int(year_blocks[i])
        except ValueError:
            i += 2
            continue

        block = year_blocks[i + 1]

        # Extract (month, day_range) pairs from CSS class divs
        # <div class="fomc-meeting__month ..."><strong>April</strong></div>
        # <div class="fomc-meeting__date ...">28-29</div>
        months = re.findall(r'fomc-meeting__month[^>]*>\s*<strong>(\w+)</strong>', block)
        dates  = re.findall(r'fomc-meeting__date[^>]*>\s*(\d{1,2}(?:-\d{1,2})?)', block)

        for month_str, date_str in zip(months, dates):
            month_num = _MONTH_MAP.get(month_str.lower())
            if not month_num:
                continue
            # Decision = last day of range (e.g. "28-29" → 29)
            day = int(date_str.split("-")[-1])
            try:
                decision = date(year, month_num, day)
            except ValueError:
                continue
            if decision >= today:
                results.append({
                    "date":     decision.isoformat(),
                    "time_utc": _fomc_utc(decision),
                    "name":     "FOMC Rate Decision",
                    "_source":  "federalreserve.gov",
                })
        i += 2

    log.info("FOMC scraper: %d upcoming meetings found", len(results))
    return results


def _scrape_boe() -> list[dict]:
    """Scrape upcoming BOE MPC decision dates from bankofengland.co.uk.

    Uses the BOE's annual MPC dates announcement page (published each December
    for the following year at /news/YYYY/month/monetary-policy-committee-dates-for-YYYY+1).
    Falls back to the upcoming-dates page for the current year if the next-year
    page is not yet published.
    Decisions announced at 12:00 noon UK time.
    """
    from datetime import date as _date
    today = _date.today()
    _months = ["december", "november", "october", "september", "august"]
    # BOE publishes the following year's dates in Aug-Dec of the prior year
    urls = [
        f"https://www.bankofengland.co.uk/news/{today.year - 1}/{m}/monetary-policy-committee-dates-for-{today.year}"
        for m in _months
    ] + [
        "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates",
    ]
    html = ""
    for url in urls:
        try:
            resp = requests.get(url, timeout=15, headers=_HEADERS)
            if resp.ok:
                html = resp.text
                break
        except requests.RequestException:
            continue
    if not html:
        log.warning("BOE scrape failed: no page responded")
        return []
    url = url  # keep last used for log
    try:
        resp = requests.get(url, timeout=15, headers=_HEADERS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("BOE scrape failed: %s", exc)
        return []

    html  = resp.text
    today = date.today()
    results: list[dict] = []

    # Pattern: "5 February 2026" (day first, then month name, then year)
    for m in re.finditer(
        rf'\b(\d{{1,2}})\s+({_MONTH_RE})\s+(\d{{4}})\b',
        html, re.IGNORECASE
    ):
        day       = int(m.group(1))
        month_num = _MONTH_MAP[m.group(2).lower()]
        year      = int(m.group(3))
        try:
            decision = date(year, month_num, day)
        except ValueError:
            continue
        if decision >= today:
            results.append({
                "date":     decision.isoformat(),
                "time_utc": _boe_utc(decision),
                "name":     "BOE Rate Decision",
                "_source":  "bankofengland.co.uk",
            })

    # Deduplicate by date
    seen: set[str] = set()
    deduped = []
    for r in results:
        if r["date"] not in seen:
            seen.add(r["date"])
            deduped.append(r)

    log.info("BOE scraper: %d upcoming meetings found", len(deduped))
    return deduped


def _scrape_ecb() -> list[dict]:
    """Scrape upcoming ECB rate decision dates from ecb.europa.eu.

    Page uses a definition-list with <dt>dd/mm/yyyy</dt><dd>description</dd>.
    Monetary policy decisions are announced on Day 2 of each 2-day meeting.
    We look for entries labelled '(Day 2)' in a monetary policy meeting context.
    """
    url = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"
    try:
        resp = requests.get(url, timeout=15, headers=_HEADERS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("ECB scrape failed: %s", exc)
        return []

    html  = resp.text
    today = date.today()
    results: list[dict] = []

    # Extract all <dt>dd/mm/yyyy</dt><dd>description</dd> pairs
    dt_dd_pairs = re.findall(
        r'<dt>\s*(\d{2}/\d{2}/\d{4})\s*</dt>\s*<dd>(.*?)</dd>',
        html, re.DOTALL | re.IGNORECASE
    )

    for date_str, description in dt_dd_pairs:
        desc = description.lower()
        # Only want monetary policy meetings (not non-monetary, not retreats)
        if "non-monetary" in desc or "retreat" in desc:
            continue
        if "monetary policy" not in desc:
            continue
        # Take Day 2 as the decision day (when the announcement is made)
        if "day 2" not in desc:
            continue

        try:
            day, month, year = (int(x) for x in date_str.split("/"))
            decision = date(year, month, day)
        except ValueError:
            continue

        if decision >= today:
            results.append({
                "date":     decision.isoformat(),
                "time_utc": _ecb_utc(decision),
                "name":     "ECB Rate Decision",
                "_source":  "ecb.europa.eu",
            })

    log.info("ECB scraper: %d upcoming meetings found", len(results))
    return results


# ── Auto-refresh central bank calendar ────────────────────────────────────────

def _calendar_needs_refresh(events_file: str, days: int) -> bool:
    """True if news_events.json is older than `days` days or missing."""
    path = Path(events_file)
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        refreshed_at = data[-1].get("_refreshed_at") if data else None
        if not refreshed_at:
            return True
        last = date.fromisoformat(refreshed_at)
        return (date.today() - last).days >= days
    except Exception:
        return True


def refresh_central_bank_calendar(
    events_file: str = config.NEWS_EVENTS_FILE,
    refresh_days: int = config.NEWS_CALENDAR_REFRESH_DAYS,
) -> int:
    """[NEW — Step 11] Scrape FOMC, BOE, ECB dates and update news_events.json.

    Called weekly by the engine. Fetches from official central bank websites,
    merges with existing manually-added events, and saves the result.
    Returns number of events written. Safe to call at any frequency — exits
    early if the file was refreshed within `refresh_days` days.
    """
    if not _calendar_needs_refresh(events_file, refresh_days):
        return 0

    log.info("Central bank calendar refresh starting...")

    # Fetch from all three sources (failures return [])
    new_events: list[dict] = []
    new_events.extend(_scrape_fomc())
    new_events.extend(_scrape_boe())
    new_events.extend(_scrape_ecb())

    if not new_events:
        log.warning("Central bank calendar: all scrapers returned empty — keeping existing file")
        return 0

    # Load existing file and keep entries NOT from scrapers (manually added)
    path = Path(events_file)
    existing: list[dict] = []
    if path.exists():
        try:
            existing = [
                e for e in json.loads(path.read_text(encoding="utf-8"))
                if "_source" not in e and "_refreshed_at" not in e
            ]
        except Exception:
            pass

    # Merge: manual entries first, then scraped entries, then timestamp sentinel
    merged = existing + new_events
    merged.sort(key=lambda e: e["date"])
    merged.append({"_refreshed_at": date.today().isoformat()})

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    log.info("Central bank calendar: %d events written to %s", len(new_events), events_file)
    return len(new_events)


# ── User-supplied custom events ────────────────────────────────────────────────

def _load_custom_events(events_file: str) -> list[datetime]:
    """Load datetimes from news_events.json. Skips metadata sentinel rows."""
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
        if "_refreshed_at" in entry:
            continue  # metadata row
        try:
            dt = datetime.fromisoformat(f"{entry['date']}T{entry['time_utc']}")
            result.append(dt)
        except (KeyError, ValueError) as exc:
            log.debug("Skipping malformed news event entry: %s", exc)
    return result


# ── Optional: Financial Modeling Prep API (stable, paid plan) ─────────────────

_FMP_COUNTRIES = {"US", "GB", "EU", "CH", "JP"}
_HIGH_IMPACT_KEYWORDS = (
    "non farm", "nonfarm", "payroll",
    "fomc", "federal reserve", "fed rate",
    "interest rate",
    "bank of england", "boe",
    "european central bank", "ecb",
    "swiss national bank", "snb",
    "bank of japan", "boj",
    "cpi", "consumer price",
    "ppi", "producer price",
    "pce", "gdp", "unemployment",
    "retail sales", "ism manufacturing", "ism services", "jolts",
)


def _is_high_impact(event_name: str, country: str) -> bool:
    if country not in _FMP_COUNTRIES:
        return False
    name_lower = event_name.lower()
    return any(kw in name_lower for kw in _HIGH_IMPACT_KEYWORDS)


def _fetch_fmp_events(api_key: str, from_date: date, to_date: date) -> list[datetime]:
    """Fetch from FMP stable economic calendar (requires paid plan)."""
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://financialmodelingprep.com/stable/economic-calendar",
            params={"from": from_date.isoformat(), "to": to_date.isoformat(), "apikey": api_key},
            timeout=15,
        )
    except requests.RequestException as exc:
        log.warning("FMP calendar fetch failed: %s", exc)
        return []
    if not resp.ok:
        log.debug("FMP calendar HTTP %s (paid plan required for free tier)", resp.status_code)
        return []
    events = []
    for item in resp.json():
        try:
            if not _is_high_impact(item.get("event", ""), (item.get("country") or "").upper()):
                continue
            events.append(datetime.fromisoformat(item["date"]))
        except (KeyError, ValueError):
            continue
    log.info("FMP calendar: %d high-impact events fetched", len(events))
    return events


# ── In-memory cache refresh ────────────────────────────────────────────────────

def refresh_news_cache(now: Optional[datetime] = None) -> None:
    """Rebuild the in-memory event cache. Called hourly by the engine."""
    global _event_cache, _cache_date
    if now is None:
        now = datetime.utcnow()

    today = now.date()
    if _cache_date == today and _event_cache:
        return

    events: list[datetime] = []
    events.extend(_builtin_events(now))
    events.extend(_load_custom_events(config.NEWS_EVENTS_FILE))
    if config.FMP_API_KEY:
        events.extend(_fetch_fmp_events(config.FMP_API_KEY, today, today + timedelta(days=7)))

    _event_cache = events
    _cache_date  = today
    custom_count = len(_load_custom_events(config.NEWS_EVENTS_FILE))
    log.info("News cache: %d events (NFP built-in + %d from %s)",
             len(events), custom_count, config.NEWS_EVENTS_FILE)


# ── Main gate ─────────────────────────────────────────────────────────────────

def is_news_window(now: datetime, pause_minutes: int = config.NEWS_PAUSE_MINUTES) -> bool:
    """Return True if `now` is within `pause_minutes` of any known high-impact event."""
    window     = timedelta(minutes=pause_minutes)
    all_events = list(_event_cache) + _builtin_events(now) + _load_custom_events(config.NEWS_EVENTS_FILE)

    seen: set[datetime] = set()
    for event_dt in all_events:
        if event_dt in seen:
            continue
        seen.add(event_dt)
        if abs(now - event_dt) <= window:
            log.info("NEWS PAUSE: %s UTC within %d min of %s",
                     now.strftime("%H:%M"), pause_minutes, event_dt.strftime("%Y-%m-%d %H:%M"))
            return True
    return False
