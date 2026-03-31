"""
AI sentiment layer — fetches headlines and scores with Claude Haiku.

Uses Finnhub free tier (60 req/min) for headlines, Claude Haiku for analysis.
Returns a sentiment score per currency pair: bullish / bearish / neutral.

Used as a FILTER (not signal generator) — blocks trades against strong sentiment.

Usage:
    from data.sentiment import SentimentFilter
    sf = SentimentFilter()
    bias = sf.get_bias("GBPUSD", direction="long")  # True = allow, False = block

Cost: ~$0.60/month with Claude Haiku batch at 50 headlines/session.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from core import config

log = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# How often to refresh sentiment (seconds)
SENTIMENT_REFRESH_SEC = 900  # 15 minutes

# Sentiment thresholds — block trades when confidence exceeds this
BLOCK_THRESHOLD = 0.5  # sentiment score magnitude must exceed this to block

# Currency mapping: which Finnhub categories affect which pairs
CURRENCY_KEYWORDS = {
    "GBPUSD": ["gbp", "pound", "sterling", "bank of england", "boe", "uk economy",
                "usd", "dollar", "fed", "fomc", "us economy", "nonfarm"],
    "USDCHF": ["chf", "franc", "swiss", "snb",
                "usd", "dollar", "fed", "fomc", "us economy", "nonfarm"],
    "GBPJPY": ["gbp", "pound", "sterling", "boe", "uk economy",
                "jpy", "yen", "boj", "japan"],
    "XAUUSD": ["gold", "xau", "precious metal", "safe haven", "inflation",
               "usd", "dollar", "fed", "rates"],
    "SPOTCRUDE": ["oil", "crude", "opec", "petroleum", "energy",
                  "wti", "brent", "barrel"],
}

# ── Sentiment cache ──────────────────────────────────────────────────────────
_sentiment_cache: dict[str, dict] = {}
_last_refresh: float = 0.0


def _fetch_headlines(category: str = "general", count: int = 20) -> list[dict]:
    """Fetch latest market news from Finnhub."""
    if not FINNHUB_API_KEY:
        log.debug("Finnhub API key not set — skipping sentiment")
        return []

    url = "https://finnhub.io/api/v1/news"
    params = {"category": category, "token": FINNHUB_API_KEY}

    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            articles = resp.json()[:count]
            log.info("Fetched %d headlines from Finnhub", len(articles))
            return articles
        log.warning("Finnhub returned %d: %s", resp.status_code, resp.text[:200])
        return []
    except Exception as exc:
        log.warning("Finnhub fetch failed: %s", exc)
        return []


def _filter_relevant(headlines: list[dict], symbol: str) -> list[str]:
    """Filter headlines relevant to a specific pair."""
    keywords = CURRENCY_KEYWORDS.get(symbol, [])
    if not keywords:
        return []

    relevant = []
    for article in headlines:
        title = (article.get("headline", "") or "").lower()
        summary = (article.get("summary", "") or "").lower()
        text = title + " " + summary
        if any(kw in text for kw in keywords):
            relevant.append(article.get("headline", ""))

    return relevant[:10]  # max 10 per pair


def _analyze_with_claude(headlines: list[str], symbol: str) -> dict:
    """Send headlines to Claude Haiku for sentiment analysis."""
    if not ANTHROPIC_API_KEY or not headlines:
        return {"sentiment": 0.0, "confidence": 0.0, "direction": "neutral"}

    try:
        import anthropic
    except ImportError:
        log.warning("anthropic package not installed — skipping AI sentiment")
        return {"sentiment": 0.0, "confidence": 0.0, "direction": "neutral"}

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Analyze these headlines for {symbol} trading sentiment.
Output ONLY valid JSON — no markdown, no explanation.

Headlines:
{chr(10).join(f'- {h}' for h in headlines)}

JSON schema:
{{"sentiment": <float -1.0 bearish to +1.0 bullish>, "confidence": <float 0.0 to 1.0>, "direction": "<bullish|bearish|neutral>", "reasoning": "<one sentence>"}}"""

    try:
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=200,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        result = json.loads(text)
        log.info("[sentiment] %s: %s (%.2f confidence) — %s",
                 symbol, result.get("direction", "?"),
                 result.get("confidence", 0), result.get("reasoning", ""))
        return result
    except json.JSONDecodeError as exc:
        log.warning("Claude sentiment parse failed: %s", exc)
        return {"sentiment": 0.0, "confidence": 0.0, "direction": "neutral"}
    except Exception as exc:
        log.warning("Claude sentiment call failed: %s", exc)
        return {"sentiment": 0.0, "confidence": 0.0, "direction": "neutral"}


def refresh_sentiment() -> None:
    """Refresh sentiment for all configured pairs."""
    global _sentiment_cache, _last_refresh

    now = time.monotonic()
    if now - _last_refresh < SENTIMENT_REFRESH_SEC:
        return  # too soon

    headlines = _fetch_headlines(category="general", count=50)
    if not headlines:
        _last_refresh = now
        return

    for symbol in config.PAIRS:
        relevant = _filter_relevant(headlines, symbol)
        if relevant:
            _sentiment_cache[symbol] = _analyze_with_claude(relevant, symbol)
        else:
            _sentiment_cache[symbol] = {"sentiment": 0.0, "confidence": 0.0, "direction": "neutral"}

    _last_refresh = now
    log.info("[sentiment] Refreshed for %d pairs", len(config.PAIRS))


class SentimentFilter:
    """Gate that blocks trades against strong AI sentiment."""

    def __init__(self, threshold: float = BLOCK_THRESHOLD):
        self.threshold = threshold

    def allow_trade(self, symbol: str, direction: str) -> bool:
        """
        Return True if trade is allowed, False if sentiment blocks it.

        Only blocks when:
        - Sentiment confidence > threshold
        - Sentiment direction opposes the trade direction
        """
        data = _sentiment_cache.get(symbol)
        if not data:
            return True  # no data = allow (fail-open)

        confidence = data.get("confidence", 0.0)
        sentiment_dir = data.get("direction", "neutral")

        if confidence < self.threshold:
            return True  # low confidence = don't block

        if sentiment_dir == "neutral":
            return True

        # Block if sentiment opposes trade direction
        if direction == "long" and sentiment_dir == "bearish":
            log.info("[sentiment] BLOCKED %s long — sentiment is bearish (conf=%.2f)",
                     symbol, confidence)
            return False
        if direction == "short" and sentiment_dir == "bullish":
            log.info("[sentiment] BLOCKED %s short — sentiment is bullish (conf=%.2f)",
                     symbol, confidence)
            return False

        return True

    def get_summary(self, symbol: str) -> str:
        """Return human-readable sentiment for dashboard."""
        data = _sentiment_cache.get(symbol)
        if not data:
            return "No data"
        direction = data.get("direction", "neutral")
        confidence = data.get("confidence", 0.0)
        return f"{direction.capitalize()} ({confidence:.0%})"
