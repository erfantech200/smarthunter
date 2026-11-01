# Trading styles

Source of truth for values: `config/desk.yaml` → `styles`. This document explains how styles are used. SPEC §7 has the full rules.

## Profiles (defaults)

| | Scalp | Intraday | Swing | Position |
|---|---|---|---|---|
| Mode | **shadow** (System Book only) | live_alerts | live_alerts | live_alerts |
| Timeframes H / M / L | M15 / M5 / M1 | H1 / M15 / M5 | D1 / H4 / H1 | W1 / D1 / H4 |
| Risk multiplier | 0.25 | 0.5 | 1.0 | 1.0 |
| Max cost / TP1 | 15% | 10% | swap-adjusted | swap-adjusted |
| Min weighted R:R | 1.2 | 1.5 | 2.0 | 2.5 |
| Signal validity | 3 min | 30 min | plan `valid_until` | plan `valid_until` |
| Max hold | 60 min | 12 h | 15 days | 12 weeks |
| Engine | A12 (fast, code only) | A6 setup → A12 trigger | slow loop | slow loop |
| Session limits | tokyo_open, london_open, london_ny_overlap; ≤5 trades and ≤2 consecutive losses per session | quiet hours mute entry alerts | — | — |

The effective risk for an A-grade setup is `0.5% × style multiplier`: scalp 0.125%, intraday 0.25%, swing and position 0.5%. Grade B halves it. Vol state high ×0.7, extreme ×0.5 or reject.

## Eligibility (SPEC §7.2, computed in code, explained by A5)
A style is eligible for an asset *now* only if all of these hold:
1. **Regime** on its timeframes suits at least one of its strategies with a proven edge.
2. **Volatility and liquidity:** scalps need `liquidity_state = deep` and movement that isn't extreme.
3. **Live cost-to-target** is within `max_cost_to_tp1`.
4. **Session clock:** inside an allowed window. Quiet hours mute scalp and intraday entry alerts.
5. **No event blackout** for that style, and A1 `news_intensity ≠ storm` for scalps.
6. **Proven edge:** OOS and System Book stats for style × asset × regime × session pass the promotion gates (SPEC §11.4).
7. **No circuit breaker** active, global or per style.

A shadow style can be eligible, but its output goes only to the System Book.

## Bias hierarchy (SPEC §7.4)
Position → swing → intraday → scalp. A lower style trades in the direction of the nearest *active* higher-style bias. The exceptions are a neutral higher bias, a range regime, or an explicitly approved counter-trend strategy with its own edge. Exceptions are flagged in alerts. Exposure from several active styles on one asset adds up in A7.

## Session clock (DST-aware; stored in UTC, shown in Melbourne time)
Three DST regimes interact: Melbourne (first Sunday of April → first Sunday of October is standard time, UTC+10; otherwise UTC+11), London (last Sunday of March → last Sunday of October, UTC+1) and New York (second Sunday of March → first Sunday of November, UTC−4). Computed with `zoneinfo`:

| Period (2026 dates) | Tokyo open 09:00 JST | London open 08:00 | NY open 08:00 ET | US data 08:30 ET | London close 16:00 |
|---|---|---|---|---|---|
| Jan (AEDT / GMT / EST) | 11:00 | 19:00 | **00:00** | **00:30** | **03:00** |
| mid-Mar (AEDT / GMT / EDT) | 11:00 | 19:00 | 23:00 | 23:30 | **03:00** |
| Apr–Sep (AEST / BST / EDT) | 10:00 | 17:00 | 22:00 | 22:30 | **01:00** |
| mid-Oct (AEDT / BST / EDT) | 11:00 | 18:00 | 23:00 | 23:30 | **02:00** |
| Nov–Dec (AEDT / GMT / EST) | 11:00 | 19:00 | **00:00** | **00:30** | **03:00** |

All times are Melbourne local. **Bold** times fall at or after midnight Melbourne.

**Conflict with `quiet_hours: 01:00-07:00`.** The London/NY overlap (NY open → London close) runs 00:00–03:00 Melbourne from November to March. Two of its three hours fall inside quiet hours, where scalp and intraday entry alerts are muted. From April to September the overlap is 22:00–01:00 and isn't affected. This is listed as an open question in PLAN.md. Scalping is in shadow mode for now anyway, so nothing is lost yet.

**Week boundaries.** FX opens Sunday 17:00 New York, which is Monday 07:00–09:00 Melbourne depending on DST, and closes Friday 17:00 New York, which is Saturday morning in Melbourne. Metals and oil CFDs have daily breaks and oil rolls. Phase 1 takes their hours from the provider instead of assuming them.
