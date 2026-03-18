"""Clean IG Markets REST client for CFD demo/live accounts."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

log = logging.getLogger(__name__)


class IGClient:
    BASE_URL_DEMO = "https://demo-api.ig.com/gateway/deal"
    BASE_URL_LIVE = "https://api.ig.com/gateway/deal"

    def __init__(
        self,
        api_key: str,
        identifier: str,
        password: str,
        account_id: str,
        demo: bool = True,
    ) -> None:
        self.api_key    = api_key
        self.identifier = identifier
        self.password   = password
        self.account_id = account_id
        self.base_url   = self.BASE_URL_DEMO if demo else self.BASE_URL_LIVE
        self._session   = requests.Session()
        self._cst:        Optional[str] = None
        self._x_security: Optional[str] = None
        self._auth_time:  float = 0.0

    # ── Authentication ────────────────────────────────────────────────────────

    @property
    def authenticated(self) -> bool:
        return bool(self._cst and self._x_security)

    def authenticate(self) -> bool:
        """Open a new IG session and store the auth tokens."""
        headers = {
            "X-IG-API-KEY":   self.api_key,
            "Content-Type":   "application/json",
            "Accept":         "application/json",
            "Version":        "2",
        }
        payload = {
            "identifier":        self.identifier,
            "password":          self.password,
            "encryptedPassword": False,
        }
        try:
            resp = self._session.post(
                f"{self.base_url}/session",
                json=payload,
                headers=headers,
                timeout=15,
            )
        except requests.RequestException as exc:
            log.error("IG auth request failed: %s", exc)
            return False

        if not resp.ok:
            log.error("IG auth failed %s: %s", resp.status_code, resp.text[:300])
            return False

        self._cst        = resp.headers.get("CST")
        self._x_security = resp.headers.get("X-SECURITY-TOKEN")
        self._auth_time  = time.monotonic()

        self._session.headers.update({
            "X-IG-API-KEY":    self.api_key,
            "CST":             self._cst or "",
            "X-SECURITY-TOKEN": self._x_security or "",
            "Content-Type":    "application/json",
            "Accept":          "application/json",
        })
        log.info("IG authenticated (account %s, %s)",
                 self.account_id, "DEMO" if self.base_url == self.BASE_URL_DEMO else "LIVE")
        return True

    # ── Internal request helper ───────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        version: str = "1",
        **kwargs,
    ) -> Optional[requests.Response]:
        if not self.authenticated:
            if not self.authenticate():
                return None

        url     = f"{self.base_url}{path}"
        headers = {"Version": version}

        try:
            resp = self._session.request(method, url, headers=headers, timeout=15, **kwargs)
        except requests.RequestException as exc:
            log.error("IG %s %s failed: %s", method, path, exc)
            return None

        if resp.status_code == 401:
            log.warning("IG session expired — re-authenticating")
            if not self.authenticate():
                return None
            try:
                resp = self._session.request(method, url, headers={"Version": version}, timeout=15, **kwargs)
            except requests.RequestException as exc:
                log.error("IG retry failed: %s", exc)
                return None

        if not resp.ok:
            log.error("IG %s %s → %s: %s", method, path, resp.status_code, resp.text[:300])
            return None

        return resp

    # ── Market data ───────────────────────────────────────────────────────────

    def get_snapshot(self, epic: str, price_scale: int = 1) -> Optional[dict]:
        """Current bid/offer from GET /markets/{epic}.

        price_scale: divide raw IG price by this to get actual FX rate.
                     EUR/USD CFD is quoted as ×10000 by IG (11510 → 1.1510).
        """
        resp = self._request("GET", f"/markets/{epic}")
        if resp is None:
            return None

        data     = resp.json()
        snapshot = data.get("snapshot", {})
        bid      = snapshot.get("bid")
        offer    = snapshot.get("offer")

        if bid is None:
            log.warning(
                "No bid for %s — status: %s",
                epic, snapshot.get("marketStatus", "UNKNOWN"),
            )
            return None

        return {
            "bid":    float(bid)   / price_scale,
            "ask":    float(offer) / price_scale if offer is not None else float(bid) / price_scale,
            "status": snapshot.get("marketStatus"),
            "time":   datetime.now(timezone.utc).replace(tzinfo=None),
        }

    def get_history(
        self,
        epic: str,
        resolution: str = "HOUR",
        max_bars: int = 500,
        price_scale: int = 1,
    ) -> list[dict]:
        """Historical OHLC bars from GET /prices/{epic} (v3, date-range).

        price_scale: same as get_snapshot — divide raw IG price by this.
        """
        date_to   = datetime.now(timezone.utc).replace(tzinfo=None)
        # Rough lookback: 1h bars × max_bars, cap at ~90 days for weekly
        hours_back = max_bars * {"MINUTE": 1/60, "MINUTE_5": 5/60, "MINUTE_15": 15/60,
                                  "MINUTE_30": 0.5, "HOUR": 1, "HOUR_2": 2, "HOUR_3": 3,
                                  "HOUR_4": 4, "DAY": 24, "WEEK": 168}.get(resolution, 1)
        date_from = date_to - timedelta(hours=hours_back * 1.1)   # 10 % buffer

        resp = self._request(
            "GET",
            f"/prices/{epic}",
            version="3",
            params={
                "resolution": resolution,
                "from":       date_from.strftime("%Y-%m-%dT%H:%M:%S"),
                "to":         date_to.strftime("%Y-%m-%dT%H:%M:%S"),
                "pageSize":   min(max_bars, 1000),
                "pageNumber": 1,
            },
        )
        if resp is None:
            return []

        data      = resp.json()
        allowance = data.get("allowance", {})
        remaining = allowance.get("remainingAllowance")
        if remaining is not None:
            log.info("IG data allowance remaining: %s / %s",
                     remaining, allowance.get("totalAllowance"))

        def mid(obj: dict) -> Optional[float]:
            b = obj.get("bid")
            a = obj.get("ask")
            if b is None:
                return None
            val = (float(b) + float(a)) / 2 if a is not None else float(b)
            return val / price_scale

        bars = []
        for p in data.get("prices", []):
            try:
                ts_raw = p.get("snapshotTimeUTC") or p.get("snapshotTime", "")
                ts_raw = ts_raw.replace("Z", "").strip()
                if "/" in ts_raw:
                    ts_raw = ts_raw.replace("/", "-")
                    ts_raw = ts_raw[:16]
                ts = datetime.fromisoformat(ts_raw)

                o = mid(p.get("openPrice",  {}))
                h = mid(p.get("highPrice",  {}))
                l = mid(p.get("lowPrice",   {}))
                c = mid(p.get("closePrice", {}))

                if None in (o, h, l, c):
                    continue

                bars.append({
                    "time":   ts,
                    "open":   o,
                    "high":   h,
                    "low":    l,
                    "close":  c,
                    "volume": p.get("lastTradedVolume", 0),
                })
            except Exception as exc:
                log.debug("Skipping malformed bar: %s", exc)

        log.info("Fetched %d %s bars for %s", len(bars), resolution, epic)
        return bars

    # ── Order management ──────────────────────────────────────────────────────

    def place_order(
        self,
        epic: str,
        direction: str,
        size: float,
        stop_level: float,
        limit_level: float,
        currency: str = "USD",
    ) -> Optional[dict]:
        """Place a MARKET CFD order with stop and limit."""
        payload = {
            "epic":           epic,
            "direction":      direction.upper(),
            "size":           size,
            "orderType":      "MARKET",
            "currencyCode":   currency,
            "forceOpen":      True,
            "guaranteedStop": False,
            "stopLevel":      stop_level,
            "limitLevel":     limit_level,
            "expiry":         "-",
        }
        resp = self._request("POST", "/positions/otc", version="2", json=payload)
        if resp is None:
            return None
        result = resp.json()
        log.info("Order placed — dealReference: %s", result.get("dealReference"))
        return result

    def get_open_positions(self) -> list[dict]:
        """All open CFD positions."""
        resp = self._request("GET", "/positions", version="2")
        if resp is None:
            return []
        return resp.json().get("positions", [])

    def close_position(self, deal_id: str, direction: str, size: float) -> Optional[dict]:
        """Close a position by deal ID (direction = opposite of opening direction)."""
        payload = {
            "dealId":    deal_id,
            "direction": direction.upper(),
            "size":      size,
            "orderType": "MARKET",
            "expiry":    "-",
        }
        resp = self._request("DELETE", "/positions/otc", version="1", json=payload)
        if resp is None:
            return None
        return resp.json()
