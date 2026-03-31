---
name: Run heavy commands in external terminal
description: VS Code extension terminal hangs on long-running commands — run optimizers/backtests in separate PowerShell
type: feedback
---

VS Code integrated terminal hangs on long-running Python commands (optimizer, heavy backtests).

**Why:** VS Code extension wraps terminal internally, causing freezes on Windows. CLI version (npm) works fine in external terminal.

**How to apply:** For commands that take >30 seconds (optimizer, full backtests), ask user to run in external PowerShell/CMD. Provide the exact command to paste. Short backtests (~30s) may work in VS Code but default to external for safety.
