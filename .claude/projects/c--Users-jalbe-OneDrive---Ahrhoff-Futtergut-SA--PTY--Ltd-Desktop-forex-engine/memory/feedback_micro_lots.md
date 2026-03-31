---
name: MT5 micro lot sizing for small accounts
description: Position sizer needs micro lots (0.01) for accounts under ~$10k. Standard lots (1.0) block all trades on small accounts.
type: feedback
---

With $1,000 balance, the position sizer blocked ALL trades because minimum 1 standard lot risked $196 (19.6% of account) vs $10 intended (1% risk).

**Fix applied:** Position sizer now uses 0.01 lot steps for MT5 (micro lots = 1,000 units). IG still uses minimum 1 contract.

**Why:** MT5/Pepperstone supports micro lots (0.01). A $1,000 account with 1% risk and 20-pip stop needs ~0.05 lots. Standard lots are 100,000 units — way too large for accounts under $10k.

**How to apply when going live:**
- Accounts under ~$5,000: micro lots work, expect 0.01-0.10 lot sizes
- Accounts $5,000-$20,000: will size at 0.05-0.50 lots naturally
- Accounts $20,000+: will approach standard lot territory (0.50-2.0 lots)
- The `MAX_RISK_OVERRIDE_MULT = 2.0` safety check still blocks if minimum lot exceeds 2× intended risk
- If going live with IG instead of MT5, IG requires minimum 1 contract — need $10,000+ balance for that to work
