"""
[NEW — Step 13] Telegram alert notifier.

Sends plain-text messages to a configured Telegram bot.
If TELEGRAM_TOKEN or TELEGRAM_CHAT_ID are not set in .env, all calls silently
no-op so the engine never fails because of a missing notification config.

Usage:
    from data.notifier import send_alert
    send_alert("🟢 TRADE OPEN\\nEURUSD LONG  entry=1.08420")

Setup (one-time):
    1. Message @BotFather on Telegram → /newbot → copy the token
    2. Message your bot, then visit:
       https://api.telegram.org/bot<TOKEN>/getUpdates
       to find your chat_id
    3. Add to .env:
       TELEGRAM_TOKEN=<token>
       TELEGRAM_CHAT_ID=<chat_id>
"""

from __future__ import annotations

import logging

import requests

from core import config

log = logging.getLogger(__name__)

_TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_alert(msg: str) -> bool:
    """
    Send a plain-text message to the configured Telegram chat.

    Returns True on success, False on any failure (including not configured).
    Never raises — safe to call from anywhere in the engine loop.
    """
    token   = config.TELEGRAM_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        log.debug("Telegram not configured — alert suppressed: %s", msg[:80])
        return False

    url = _TELEGRAM_URL.format(token=token)
    try:
        resp = requests.post(
            url,
            json    = {"chat_id": chat_id, "text": msg},
            timeout = 10,
        )
        if resp.status_code == 200:
            log.info("Telegram alert sent (%d chars)", len(msg))
            return True
        log.warning(
            "Telegram alert failed  HTTP %d: %s",
            resp.status_code, resp.text[:200],
        )
        return False
    except Exception as exc:          # network error, timeout, etc.
        log.warning("Telegram alert error: %s", exc)
        return False
