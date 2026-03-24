"""Clean IG Markets REST client for CFD demo/live accounts."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from core import config

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
                timeout=config.IG_REQUEST_TIMEOUT_SEC,
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
            resp = self._session.request(method, url, headers=headers, timeout=config.IG_REQUEST_TIMEOUT_SEC, **kwargs)
        except requests.RequestException as exc:
            log.error("IG %s %s failed: %s", method, path, exc)
            # [NEW — Step 9] Exponential backoff — retry up to IG_RETRY_MAX times
            resp = None
            for attempt in range(1, config.IG_RETRY_MAX + 1):
                wait = min(config.IG_RETRY_BASE_SEC ** attempt, 30)
                log.warning("Retrying %s %s in %ds (attempt %d/%d)…",
                            method, path, wait, attempt, config.IG_RETRY_MAX)
                time.sleep(wait)
                try:
                    resp = self._session.request(
                        method, url, headers=headers,
                        timeout=config.IG_REQUEST_TIMEOUT_SEC, **kwargs,
                    )
                    break
                except requests.RequestException as exc2:
                    log.error("Retry %d failed: %s", attempt, exc2)
            if resp is None:
                return None

        if resp.status_code == 401:
            log.warning("IG session expired — re-authenticating")
            if not self.authenticate():
                return None
            try:
                resp = self._session.request(method, url, headers={"Version": version}, timeout=config.IG_REQUEST_TIMEOUT_SEC, **kwargs)
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
          EUR/USD CFD returns raw ×10000 (11510 → 1.1510); other pairs
          return human-readable prices so price_scale=1.
          Do NOT use the API's scalingFactor — it is inconsistent across
          instruments (some pairs already return human-readable prices but
          still carry a non-1 scalingFactor, causing double-division).
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

        # Log dealing rules once so we can see minimum stop distance
        rules = data.get("dealingRules", {})
        min_stop = rules.get("minNormalStopOrLimitDistance", {})
        if min_stop:
            log.info(
                "%s min stop distance: %s %s",
                epic, min_stop.get("value"), min_stop.get("unit"),
            )

        return {
            "bid":    float(bid)   / price_scale,
            "ask":    float(offer) / price_scale if offer is not None else float(bid) / price_scale,
            "status": snapshot.get("marketStatus"),
            "time":   datetime.now(timezone.utc).replace(tzinfo=None),
            "min_stop_pips": float(min_stop.get("value", 0)) if min_stop else 0,
        }

    def get_history(
        self,
        epic: str,
        resolution: str = "HOUR",
        max_bars: int = 500,
        price_scale: int = 1,          # kept for compat; overridden by scalingFactor if snapshot called first
        from_time: Optional[datetime] = None,   # [NEW — Step 8] if set, fetch only bars since this time
    ) -> list[dict]:
        """Historical OHLC bars from GET /prices/{epic} (v3, date-range).

        price_scale: same as get_snapshot — divide raw IG price by this.
        from_time:   if provided, use as the start of the date range instead of
                     calculating from max_bars.  Used by refresh_bars() for
                     incremental fetches.
        """
        date_to   = datetime.now(timezone.utc).replace(tzinfo=None)
        if from_time is not None:                                        # [NEW — Step 8]
            date_from = from_time
        else:
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
        entry: float,
        pip_size: float,
        currency: str = "USD",
    ) -> Optional[dict]:
        """Place a MARKET CFD order with stop and limit.

        Uses stopDistance/limitDistance (pips from fill price) rather than
        absolute stopLevel/limitLevel, so IG calculates levels from the
        actual fill — avoids ATTACHED_ORDER_LEVEL_ERROR caused by the market
        moving between our quote and the order being processed.
        """
        stop_distance  = round(abs(entry - stop_level)  / pip_size, 1)
        limit_distance = round(abs(limit_level - entry) / pip_size, 1)
        log.info(
            "Order distances — stop: %.1f pips  limit: %.1f pips",
            stop_distance, limit_distance,
        )
        payload = {
            "epic":          epic,
            "direction":     direction.upper(),
            "size":          size,
            "orderType":     "MARKET",
            "currencyCode":  currency,
            "forceOpen":     True,
            "guaranteedStop": False,
            "stopDistance":  stop_distance,
            "limitDistance": limit_distance,
            "expiry":        "-",
        }
        resp = self._request("POST", "/positions/otc", version="2", json=payload)
        if resp is None:
            return None
        result = resp.json()
        log.info("Order placed — dealReference: %s", result.get("dealReference"))
        return result

    def confirm_order(self, deal_reference: str) -> Optional[dict]:
        """Check deal confirmation — POST response only means received, not accepted."""
        import time as _time
        _time.sleep(1)   # give IG a moment to process
        resp = self._request("GET", f"/confirms/{deal_reference}")
        if resp is None:
            return None
        data = resp.json()
        status = data.get("dealStatus", "UNKNOWN")
        reason = data.get("reason", "UNKNOWN")
        if status == "ACCEPTED":
            log.info("Deal ACCEPTED  ref=%s  fill=%.5f", deal_reference, data.get("level", 0))
        else:
            log.error("Deal REJECTED  ref=%s  reason=%s", deal_reference, reason)
        return data

    def get_account_balance(self) -> Optional[float]:
        """
        Fetch the real account balance from IG GET /accounts.
        Returns the 'balance' field for the configured account_id, or None on failure.
        Used by the engine to keep EquityGuard and DailyLossGuard in sync with
        the actual account rather than a hardcoded starting value.
        """
        resp = self._request("GET", "/accounts", version="1")
        if resp is None:
            return None
        accounts = resp.json().get("accounts", [])
        for acct in accounts:
            if acct.get("accountId") == self.account_id:
                balance = acct.get("balance", {}).get("balance")
                if balance is not None:
                    return float(balance)
        # Fallback: return balance of first account if account_id not matched
        if accounts:
            balance = accounts[0].get("balance", {}).get("balance")
            if balance is not None:
                log.warning("account_id %s not found — using first account balance", self.account_id)
                return float(balance)
        log.warning("Could not parse account balance from IG response")
        return None

    def get_open_positions(self) -> list[dict]:
        """All open CFD positions."""
        resp = self._request("GET", "/positions", version="2")
        if resp is None:
            return []
        return resp.json().get("positions", [])

    def amend_stop(self, epic: str, new_stop: float, price_scale: int = 1) -> bool:
        """
        [NEW — Step 5] Move the stop level on an open position.

        Finds the live position by epic (GET /positions), then amends it via
        PUT /positions/otc/{dealId}.  Returns True on success.

        price_scale: same as get_snapshot — raw IG price = human-readable × price_scale.
          EUR/USD CFD: price_scale=10000 → send 11450 not 1.1450.
          All other pairs: price_scale=1 → send as-is.
          [B6 FIX — Step 11] Incorrect scale caused amendment to send 1.1450 to IG
          for EURUSD when IG expects 11450, which would immediately trigger the stop.

        Note: uses absolute stopLevel (not pip distance) — correct format for
        position *amendments*. Distance-based (Fix 2) only applies to new orders.
        """
        positions = self.get_open_positions()
        match = next(
            (p for p in positions if p.get("market", {}).get("epic") == epic),
            None,
        )
        if match is None:
            log.warning("amend_stop: no open position found for %s", epic)
            return False

        deal_id  = match["position"]["dealId"]
        # [B6 FIX — Step 11] Scale to IG raw format.
        # EURUSD (price_scale=10000): 1.1450 → 11450.0 → round to 1 dp (integer-ish)
        # Other pairs (price_scale=1):  1.2750 → 1.2750  → keep 5 dp
        decimals = 1 if price_scale > 1 else 5
        raw_stop = round(new_stop * price_scale, decimals)
        payload = {
            "trailingStop": False,
            "stopLevel":    raw_stop,
        }
        resp = self._request("PUT", f"/positions/otc/{deal_id}", version="2", json=payload)
        if resp is None:
            return False
        log.info("Stop amended  epic=%s  deal=%s  human=%.5f  raw=%.1f",
                 epic, deal_id, new_stop, raw_stop)
        return True

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
