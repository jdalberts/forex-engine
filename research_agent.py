"""
Weekly automated research agent — scans for trading strategy updates,
tool changes, news source monitoring, and SA regulation changes.

Runs every Sunday evening via Windows Task Scheduler.
Updates memory/research_unified_engine.md and sends Telegram digest.

Usage:
    python research_agent.py              # run full research scan
    python research_agent.py --dry-run    # print results without saving/sending

Requirements:
    pip install anthropic
    ANTHROPIC_API_KEY in .env (or system environment)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("research_agent")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MEMORY_FILE = Path(__file__).parent / ".claude" / "projects" / \
    "c--Users-jalbe-OneDrive---Ahrhoff-Futtergut-SA--PTY--Ltd-Desktop-forex-engine" / \
    "memory" / "research_unified_engine.md"

RESEARCH_TOPICS = [
    {
        "name": "Strategy & Market Research",
        "query": (
            "Search for the latest algorithmic trading strategy research published "
            "in the last 7 days. Focus on: new mean reversion or trend following "
            "approaches for forex and commodities, any new academic papers on "
            "systematic trading, changes in market regime or volatility structure. "
            "Also check if there are any new findings about combining strategies."
        ),
    },
    {
        "name": "Tool & API Updates",
        "query": (
            "Search for updates to these specific tools in the last 7 days: "
            "MetaTrader5 Python package, NautilusTrader, PyBroker, VectorBT, "
            "ib_async (Interactive Brokers Python), Pepperstone broker updates, "
            "and any new Python trading libraries that have gained traction. "
            "Also check for breaking changes in pandas, numpy, or fastapi."
        ),
    },
    {
        "name": "News Source Monitoring",
        "query": (
            "Search for changes to these financial data APIs in the last 7 days: "
            "Finnhub API, Alpha Vantage, yfinance, GDELT, ForexFactory. "
            "Check for: pricing changes, API deprecations, new features, "
            "new free data sources for forex or commodity OHLC data. "
            "Also check current Claude API (Anthropic) pricing for any changes."
        ),
    },
    {
        "name": "SA Regulation",
        "query": (
            "Search for any South Africa financial regulation changes in the "
            "last 7 days affecting forex trading or algorithmic trading. "
            "Check FSCA announcements, COFI Bill progress, any new restrictions "
            "on retail forex or CFD trading from South Africa."
        ),
    },
]

SYSTEM_PROMPT = """You are a research assistant for an automated forex/commodity trading engine.
Your job is to scan for the latest developments and report ONLY what is NEW and actionable.

Rules:
- Only report findings from the last 7 days
- Be specific: include dates, version numbers, prices, URLs
- Focus on what CHANGES something for the trading engine
- Skip generic advice or old information
- If nothing new is found for a topic, say "No significant changes this week"
- Keep each topic to 2-5 bullet points maximum
- Output valid JSON matching the schema below

Output JSON schema:
{
  "scan_date": "YYYY-MM-DD",
  "topics": [
    {
      "name": "Topic Name",
      "has_changes": true/false,
      "findings": ["bullet 1", "bullet 2"],
      "action_required": true/false,
      "action_description": "what to do (if action_required)"
    }
  ],
  "summary": "1-2 sentence overall summary"
}"""


def run_research() -> dict:
    """Call Claude API with web search to research all topics."""
    try:
        import anthropic
    except ImportError:
        log.error("pip install anthropic (required for research agent)")
        return {}

    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set in .env")
        return {}

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build the research prompt
    topics_text = "\n\n".join(
        f"### Topic {i+1}: {t['name']}\n{t['query']}"
        for i, t in enumerate(RESEARCH_TOPICS)
    )

    user_prompt = f"""Today is {datetime.now(timezone.utc).strftime('%Y-%m-%d')}.

Please research the following topics using web search. For each topic, report ONLY
what has changed in the last 7 days. Output valid JSON.

{topics_text}

Remember: output ONLY the JSON object, no markdown formatting, no code fences."""

    log.info("Calling Claude API for research scan...")
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20241022",
            max_tokens=2000,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        return json.loads(text)
    except json.JSONDecodeError as exc:
        log.error("Failed to parse Claude response as JSON: %s", exc)
        log.error("Raw response: %s", text[:500])
        return {}
    except Exception as exc:
        log.error("Claude API call failed: %s", exc)
        return {}


def format_telegram_digest(results: dict) -> str:
    """Format research results into a Telegram message."""
    if not results:
        return "Weekly Research: API call failed — check logs."

    lines = [f"📊 WEEKLY RESEARCH SCAN — {results.get('scan_date', 'unknown')}"]
    lines.append("")

    has_any_changes = False
    for topic in results.get("topics", []):
        name = topic.get("name", "Unknown")
        has_changes = topic.get("has_changes", False)
        findings = topic.get("findings", [])
        action = topic.get("action_required", False)

        if has_changes:
            has_any_changes = True
            icon = "🔴" if action else "🟡"
            lines.append(f"{icon} {name}:")
            for f in findings[:3]:
                lines.append(f"  • {f}")
        else:
            lines.append(f"✅ {name}: No changes")

    lines.append("")
    lines.append(results.get("summary", ""))

    if not has_any_changes:
        lines.append("\n💤 All clear — no action needed this week.")

    return "\n".join(lines)


def update_memory(results: dict) -> None:
    """Append new findings to the research memory file."""
    if not results or not MEMORY_FILE.exists():
        return

    date = results.get("scan_date", datetime.now().strftime("%Y-%m-%d"))
    changes = []
    for topic in results.get("topics", []):
        if topic.get("has_changes"):
            for finding in topic.get("findings", []):
                changes.append(f"- [{topic['name']}] {finding}")

    if not changes:
        log.info("No changes to write to memory.")
        return

    # Append to the memory file
    new_section = f"\n\n### Auto-Research Scan ({date})\n" + "\n".join(changes) + "\n"

    content = MEMORY_FILE.read_text(encoding="utf-8")
    content += new_section
    MEMORY_FILE.write_text(content, encoding="utf-8")
    log.info("Updated memory file with %d new findings.", len(changes))


def main():
    parser = argparse.ArgumentParser(description="Weekly research agent")
    parser.add_argument("--dry-run", action="store_true", help="Print results without saving/sending")
    args = parser.parse_args()

    log.info("Starting weekly research scan...")
    results = run_research()

    if not results:
        log.error("Research scan returned no results.")
        return

    # Format digest
    digest = format_telegram_digest(results)
    print("\n" + digest + "\n")

    if args.dry_run:
        log.info("Dry run — not saving or sending.")
        return

    # Update memory file
    update_memory(results)

    # Send Telegram digest
    try:
        from data.notifier import send_alert
        if send_alert(digest):
            log.info("Telegram digest sent.")
        else:
            log.warning("Telegram send failed (check config).")
    except Exception as exc:
        log.error("Telegram error: %s", exc)

    log.info("Research scan complete.")


if __name__ == "__main__":
    main()
