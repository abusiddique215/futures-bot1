# Pre-Plan 1 Verification — Supply Chain + Topstep Facts

**Date:** 2026-05-22
**Source:** Three parallel research agents dispatched between Plan 1 self-review and Plan 1 execution.
**Status:** Findings captured here; spec patches deferred to the point where each becomes load-bearing (noted per item).

This document exists so the verification findings don't get lost between Plan 1 review and Plan 3 implementation. Spec files are **not** edited in place yet — they remain as the user/Codex reviewed them. Patches listed here are applied when their target plan is being written.

---

## 1. `project-x-py` (TopstepX SDK)

**Verdict:** Use, with pin bump.

| Field | Spec assumed | Verified 2026-05-22 |
|---|---|---|
| PyPI canonical name | `project-x-py` | ✅ `project-x-py` |
| Latest version | `>=3.5.8` | **3.5.9** (datetime parsing fix) |
| TopstepX support | yes | ✅ `api.topstepx.com` in README |
| Python requirement | 3.12+ | 3.12+ (matches) |
| Last code push | n/a | 2025-09-23 (~8 months stale — not abandoned, but quiet) |

**Risks:**
- Repo is quiet but not archived. Track upstream for emergency fixes.
- v3 introduced breaking changes that may affect spec 02 §3.3:
  - `create_initialized_trading_suite()` was removed
  - Single-instrument string args deprecated in favor of lists
  - Direct `suite.data` access deprecated in multi-instrument mode
  - Spec uses `client.create_suite("MNQ")` — this should still work; **re-verify before Plan 8.**

**Patch deferred to Plan 8 (TopstepX Live Execution):**
- Bump `pyproject.toml` pin: `"project-x-py>=3.5.9,<4.0"`
- In Task that wires the SDK, add an explicit version-pin check + a 5-minute smoke test against the SDK's current API surface (call `list_accounts()` against the SDK's mock if available).

---

## 2. `nautilus-trader` (Runtime)

**Verdict:** Use, with pin bump. Clean.

| Field | Spec assumed | Verified 2026-05-22 |
|---|---|---|
| Latest version | `>=1.200` | **1.227.0** (2026-05-18) |
| macOS arm64 + Py3.12 wheel | implied yes | ✅ pre-built `cp312-cp312-macosx_*_arm64.whl` |
| Rust toolchain | flagged as risk | ✅ **NOT needed** for wheel installs |
| Strategy API stable | assumed | ✅ Zero breaking changes 1.200 → 1.227 |
| RiskEngine API stable | assumed | ✅ Zero breaking changes |
| ExecutionClient API stable | assumed | ✅ Only additive change (`calculate_commission` added in 1.227) |

**Patch deferred to Plan 2 (Data Pipeline) — first plan that imports Nautilus:**
- Bump `pyproject.toml` pin: `"nautilus-trader>=1.227,<1.228"`
- The 1.227 `cancel_order`/`modify_order` Rust v2 signature changes do NOT affect Cython/Python subclasses; no spec rewrite needed.

---

## 3. Topstep facts (Jan-May 2026)

### 3.1 TopstepX API URLs — UNCHANGED

| Spec assumed | Verified |
|---|---|
| `https://api.topstepx.com` (REST) | ✅ |
| `https://rtc.topstepx.com/hubs/user` (SignalR user hub) | ✅ |
| `https://rtc.topstepx.com/hubs/market` (SignalR market hub) | ✅ |
| JWT auth, ~24h token TTL | ✅ |

Source: `https://gateway.docs.projectx.com/docs/getting-started/connection-urls/`

**No spec patches needed.**

### 3.2 $50K Combine pricing — DUAL PATH NOW

Spec 00 §3 ("Reality check") referenced "$49 + $149 activation = $198 each" as the Combine attempt cost. As of Feb 2026, Topstep added a second pricing tier:

| Path | Monthly fee | Activation fee | Total per attempt |
|---|---|---|---|
| **Standard Path** (spec's assumption) | $49 | $149 | $198 first attempt; $49 reset |
| **No Activation Fee Path** (new Feb 2026) | $95 | $0 | $95 first attempt; $95 reset |

Source: `https://help.topstep.com/en/articles/9208217-topstep-pricing`

Old URL `https://www.topstep.com/pricing/` now 404s; canonical pricing lives in the help-center article above.

**Patch deferred to Plan 9 (Mac Deploy) — or anywhere we surface "Combine attempt budget":**
- Update spec 00 §3 to acknowledge both paths.
- If the bot needs to surface cost-per-attempt to the operator (e.g., in a startup banner), the choice should be config-driven, not hardcoded.

**Decision needed from operator before Combine 1:** which path to subscribe to?
- Standard ($49/mo) makes sense if you're confident in ≤1 reset.
- No-Activation ($95/mo) makes sense if you expect 2+ attempts in the same month, since reset cost is then $95 not $49+$149.

### 3.3 VPS/VPN ban — CITATION FIX

Spec multi-cites `https://help.topstep.com/en/articles/10305426-prohibited-trading-strategies-at-topstep` for the VPS/VPN ban. The binding language actually lives in:

**`https://help.topstep.com/en/articles/8680268-can-i-use-a-vpn`**

Exact text:
> "No, you cannot use a VPN while trading with Topstep."
> Prohibits "VPNs, Proxy Services, TOR, geo-location obfuscation, and other potential identity masking services."

And from TopstepX API rules: **"activity must come from your own device, without using VPS, VPNs, or remote access tools."** A VPS connection triggers HTTP 403.

Applies to **both** Combine and Funded.

**Patches deferred to Plan 9 (Mac Deploy):**
Update the following citations in specs:
- `00-architecture-overview.md §7 item 5` — swap URL
- `00-architecture-overview.md §5 table` (row "Remote VPS / cloud") — swap URL
- `04-risk-engine.md §2` (table row "VPS/cloud prohibited") — swap URL
- `07-config-and-deploy.md §3.9` ("Cloud usage policy" table) — swap URL
- `07-config-and-deploy.md §3.6 step 3` hostname-guard comment — swap URL

### 3.4 EFA $50K Scaling Plan — VERIFIED, NUMBERS LOCKED

Spec 04 §3.3 + §4.4 `EFAStandardEoDDrawdown.max_position` already has the right thresholds. Upgrading from "Medium confidence" to **VERIFIED 2026-05-22.**

| EoD profit (= equity − start_balance) | Max contracts (mini-equivalents) |
|---|---|
| `< +$1,500` | **2** |
| `+$1,500 ≤ profit < +$2,000` | **3** |
| `≥ +$2,000` | **5** |

Source: `https://h2tfunding.com/topstep-scaling-plan/` (Topstep's own help article 8284223 only shows a graph, no text).

**Topstep platform quirk:** On TopstepX, **10 micros = 1 mini** for scaling purposes. On third-party platforms (Tradovate, NinjaTrader), **1 micro = 1 full contract**. Our spec runs on TopstepX for live, so the 10:1 rule applies. v1 already maps MNQ → mini_cap × 10 (50 micros on $50K Combine, scaling 20/30/50 on EFA). Consistent.

**Tier upgrade timing:** Effective the **next session** after the Trade Report posts (not intraday). The bot must not assume a milestone hit during the day immediately unlocks a higher cap.

**Patches deferred to Plan 3 (Risk Engine):**
- Remove the "Medium confidence" warning + 90-day re-verification check (spec 04 §3.3 + §6 question 5).
- Add a session-boundary gate on scaling-tier increases: the bot reads `policy.max_position()` only from the snapshot active at session open (17:00 CT), not mid-session.
- Add a comment in `EFAStandardEoDDrawdown.max_position` linking to the verified source.

### 3.5 Combine MLL semantics — WORDING FIX

Spec 04 §3.3 table says:

| Policy | Phantom MLL semantics |
|---|---|
| `CombineIntradayDrawdown` | Real-time on `state.equity` (incl. unrealized); locks at `start_balance` once `equity ≥ start_balance + MLL_AMOUNT` |
| `EFAStandardEoDDrawdown` | **Trails on end-of-day equity only**; intraday wicks ignored. Locks at $0. |

The phrase "intraday wicks ignored" is ambiguous and could be read as "intraday equity isn't checked against the floor" — which would be wrong and dangerous.

**Reality (Topstep article 8284204):**
> "The MLL updates at the end of each trading day, but it is monitored in real time. Both your realized and unrealized P&L count toward it."

For **both** Combine and EFA:
- Equity (incl. unrealized P&L) is checked against the phantom-MLL floor in real time.
- The **floor itself** updates differently:
  - Combine: high-water ratchets every tick, floor moves intraday until it locks at `start_balance`.
  - EFA: high-water ratchets EoD only; the floor is constant intraday.

The spec's code is already correct (`TopstepRiskGate.on_tick` checks `equity ≤ phantom_mll` on every tick regardless of policy; the policies differ only in `update_on_tick` and `update_on_eod` semantics). Only the **prose** is misleading.

**Patches deferred to Plan 3 (Risk Engine):**
- In `04-risk-engine.md §3.3` table: change EFA row's phantom-MLL semantics column to: "Floor itself ratchets EoD only (intraday wicks don't move the floor). Locks at $0. **Equity is still checked against the floor in real time** — `state.equity ≤ phantom_mll` triggers liquidation on any tick, same as Combine."
- In `04-risk-engine.md §3.4` paragraph after the worked example: drop the "(no intraday wick concern)" phrase from the EFA Standard description. Replace with: "For EFA Standard accounts, `phantom_mll` is constant within a session — only `update_on_eod` ratchets the floor. The equity-touch check in `TopstepRiskGate.on_tick` still runs every tick using `state.equity` (incl. unrealized)."

---

## Summary of patches by target plan

| Patch | Apply when writing… |
|---|---|
| Bump `nautilus-trader` pin to `>=1.227,<1.228` | Plan 2 |
| Spec 04 §3.3 + §3.4 EFA prose tightening | Plan 3 |
| Spec 04 §3.3 + §6: EFA scaling tiers verified, drop 90-day stale warning | Plan 3 |
| Spec 04 §3.3 EFA: add session-boundary gate on tier increase | Plan 3 |
| Bump `project-x-py` pin to `>=3.5.9,<4.0` | Plan 8 |
| Re-verify `project-x-py` v3 API surface against spec 02 §3.3 | Plan 8 |
| Spec 00 / 04 / 07: swap VPS/VPN citation URL to article 8680268 | Plan 9 |
| Spec 00 §3 / spec 07: add No-Activation-Fee path ($95/mo, $0 activation) | Plan 9 |
| Add config option / operator question: which Combine pricing path | Plan 9 |

**Plan 1 is unaffected** by every patch above — it ships types, constants, Protocol shells, and config schema. None of the corrections touch Plan 1's content.
