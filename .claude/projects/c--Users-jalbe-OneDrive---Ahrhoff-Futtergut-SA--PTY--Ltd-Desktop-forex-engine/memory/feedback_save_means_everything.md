---
name: Save means save EVERYTHING
description: When user says "save" or asks if something is saved — commit, push to GitHub, update memory, update roadmap, and confirm all 4.
type: feedback
---

When the user says "save" or asks "is everything saved", do ALL of these:

1. **Memory** — update relevant memory files with current state
2. **Roadmap** — update CLAUDE.md with any completed/new items
3. **Git commit** — stage and commit all changes with descriptive message
4. **Git push** — push to GitHub immediately (not just commit locally!)
5. **Confirm** — tell the user what was saved to each: memory, roadmap, committed, AND pushed

**Why:** There was a gap where local commits weren't pushed to GitHub. When the VPS did `git pull`, it got old code. This caused the engine to run with wrong broker (IG instead of MT5) and wrong pairs (EURUSD still included). Always push after commit.

**How to apply:** Every time work is done or the user says "save", finish with: commit → push → confirm. Never leave unpushed commits.
