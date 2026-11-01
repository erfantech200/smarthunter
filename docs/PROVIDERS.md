# Providers — verification log and recommendations

SPEC §10 and §24.4: verify every external API against its current official docs before integrating, and record the date.

## How this was checked (2026-11-01), and what is still open

- **Method.** The Phase 0 build sandbox could reach a web search engine but **could not fetch provider websites directly** (its network policy blocked `twelvedata.com`, `massive.com`, `developer.oanda.com` and similar hosts). Most figures below therefore come from search-result excerpts of official pages, plus third-party listings where nothing official surfaced. Each row is labelled:
  - **Verified (official):** the snippet came from the provider's own page or docs.
  - **Unverified:** a third-party source, or sources that disagree. Confirm it on the official page before you pay.
- **Before each integration phase**, the adapter's PR re-checks that provider's official docs, pricing, rate limits, terms and Australian availability, and updates this file with the date. That's the rule from §24.4. A row here isn't approval to integrate.
- **Anthropic** figures come from Anthropic's model and pricing reference, cached 2026-10-06 and current as of 2026-11-01.

## 1. Recommended stack (pending your approval)

| Need | Recommendation | Monthly cost | Status |
|---|---|---|---|
| Real-time bid/ask stream, all 7 instruments | **OANDA v20, practice (demo) account**: HTTP streaming pricing | **$0** | Recommended. See §2.1 |
| Higher-TF history (years of H1–W1) + M1/S5 bid/ask candles | OANDA v20 candles (`price=BA`) | $0 | Recommended |
| Tick history with real spreads (scalp/intraday backtests) | **Dukascopy** historical ticks (personal research use) | $0 | Terms need confirming. See §2.3 |
| Second price source (cross-check, outlier confirmation) | **Twelve Data** Basic (free) REST quotes on 1–2 instruments | $0 (Grow ≈ $79 if more is needed) | Unverified prices |
| Economic calendar **with consensus + actual** | **FMP** (Starter ≈ $29 / Premium ≈ $69 per month); fallback Trading Economics | ≈ $29–69 | **Tier that includes the calendar is unconfirmed** |
| News + central banks | Official RSS/pages (Fed, ECB, BoE, BoJ, MoF, US Treasury, EIA, OPEC) + GDELT + one news API free tier (Finnhub or Marketaux) | $0 | Recommended |
| Targeted follow-up research | Claude API web search ($10 / 1,000 searches) + web fetch | ≈ $2–15 | Verified (Anthropic) |
| Macro series | FRED, ECB Data Portal, BoE database | $0 | Official, free (key for FRED) |
| Positioning | CFTC COT via the Public Reporting Environment (Socrata API); ICE COT for Brent; ETF issuer holdings; World Gold Council | $0 | Official |
| Energy fundamentals | EIA Open Data API v2; Baker Hughes rig count; OPEC MOMR | $0 | Official |
| Oil futures term structure (optional) | **Skip for now.** Databento CME live is ≥ $199/month after its 2026-06-22 price change | $0 now | Revisit in Phase 6 |
| **Total recommended data spend** | | **≈ $30–70 / month** | |

## 2. Price feeds

### 2.1 OANDA v20 (recommended primary feed)
- **Coverage:** all 7 instruments as OANDA CFD/FX symbols: `XAU_USD`, `XAG_USD`, `EUR_USD`, `GBP_USD`, `USD_JPY`, `WTICO_USD` (WTI) and `BCO_USD` (Brent). *Confirm that the account's instrument list includes the oil CFDs. Availability varies by OANDA division.*
- **Endpoints (verified, official):** practice REST `https://api-fxpractice.oanda.com`, practice streaming `https://stream-fxpractice.oanda.com`, live `https://api-fxtrade.oanda.com`. Streaming is chunked HTTP, not WebSocket.
- **Australia (verified, official):** OANDA's AU site advertises the REST API and a free demo ("practice") environment that mirrors production endpoints. Account activation is "subject to meeting our criteria".
- **Stream rate (unverified, third-party):** at most about 4 price updates per second per instrument (250 ms), and *not every price*. Reported limits: 100 req/s per token and 20 concurrent streams per account.
- **Implications we design for:**
  1. Bars we build from the stream will differ slightly from OANDA's own candles in high/low, because the stream is throttled. The Phase 1 DoD "live bars match the provider's bars" needs a stated tolerance. Proposed: OHLC within 1 typical spread, and close exact on M5+.
  2. OANDA provides **no tick history**. Scalp and intraday tick-replay backtests use Dukascopy ticks (§2.3). S5/M1 bid/ask candles are the fallback, labelled lower fidelity.
  3. **No order endpoints are ever called** (SPEC §3.10). The adapter talks to the pricing and instrument-candles endpoints only, and `tests/test_architecture.py` fails the build if order or trade endpoints appear in the code.
  4. Practice accounts can be closed after long inactivity, so the stream watchdog alerts on auth failures.
- **Terms:** confirm that OANDA's API terms allow personal analysis use of practice-account prices. Prices are not redistributed: single user, private.
- **Later:** once you choose a broker, its feed (cTrader Open API / MT5 bridge) can replace OANDA behind the same adapter interface, and the basis offset should go to about 0 (SPEC §8.4).

### 2.2 Alternatives evaluated
| Provider | Real-time streaming | Coverage of our 7 | Price | Notes |
|---|---|---|---|---|
| **Twelve Data** | WebSocket. Full access needs **Pro** or higher (official support article). Basic and Grow get trial symbols only | FX yes. Commodities from Grow | Grow ≈ $79/month; Pro ≈ $191–229/month (third-party, **unverified**) | Good second source. Free Basic tier is enough for a REST cross-check |
| **Massive (ex-Polygon) Currencies** | WebSocket `wss://socket.massive.com/forex` on **Currencies Starter** and up, not Basic (official docs) | FX majors + XAU/XAG as FX pairs. **No oil** | Unverified (third-party figures conflict) | Would still need an oil source |
| **Dukascopy** | Live JForex feed requires an account | All 7 incl. Brent/WTI CFDs | Free historical | Best free tick history (§2.3) |
| **Databento (CME/ICE)** | Yes, real exchange data | Futures only (GC, SI, CL, BZ), not spot FX | CME live ≥ $199/month (official blog, 2026-06-22 pricing) | Optional term-structure reference, not a primary feed |

### 2.3 Dukascopy historical ticks
- Free bid/ask tick data, the most common free source for FX/CFD tick backtests. Multi-year tick ranges are gigabytes per instrument.
- **Terms: not confirmed.** Third-party tools say users are bound by Dukascopy's licence terms, which are shown when downloading through JForex. **Before Phase 4:** read the licence, download only for personal research, store locally, never redistribute.
- Dukascopy prices differ from OANDA's (a different liquidity pool). Backtests use Dukascopy spreads *scaled to the active broker profile's session spreads*, so the edge is never measured at a cheaper spread than you will actually pay.

## 3. Calendar and news

| Provider | What we'd use | Price | Status |
|---|---|---|---|
| **FMP** | `/stable/economic-calendar` (actual, consensus/estimate, previous, impact) | Starter $29 ($19/month annual), Premium $69 ($49/month annual) per official pages | Which tier includes the economic calendar is **unconfirmed** |
| **Trading Economics** | Calendar with Actual/Consensus/Forecast, official-source actuals | Not found (enterprise-style pricing) | Fallback if FMP's coverage or latency is poor |
| **Finnhub** | News; economic calendar is **premium** | Free tier 60 calls/min. Paid tiers reported at $199–399/month (**unverified**) | Calendar too expensive here. Free news tier OK |
| Official RSS/pages | Fed, ECB, BoE, BoJ, Japan MoF, US Treasury, EIA, OPEC | Free | Fetch politely. Respect robots and terms |
| GDELT | Broad news discovery + tone (low weight) | Free | — |
| Claude web search / fetch | Targeted verification with a domain allow-list | $10 / 1,000 searches + tokens | Verified |

**The calendar needs consensus values,** because §6 A1 computes the surprise as actual − consensus. Without them, A1 still works, but surprise-based logic (strategy 10, post-release drift) is disabled and shows as a data gap.

## 4. Macro, positioning, energy (free, official)
- **FRED** (St. Louis Fed): US 2y/10y, 10y TIPS real yield, breakevens, HY OAS, broad USD index, VIX close. Free API key. Respect the published rate limit.
- **ECB Data Portal**, **BoE IADB**, **BoJ / MoF statistics**: DE/UK/JP yields and policy rates. Free, no key for ECB.
- **CFTC COT**: Public Reporting Environment (Socrata API at `publicreporting.cftc.gov`). Legacy futures-only history goes back to 1986, alongside Disaggregated and TFF datasets. An optional free Socrata app token raises rate limits. The dataset IDs get pinned in Phase 6 after checking the API help pages.
- **ICE COT** (Brent): published by ICE weekly. Check its format and terms in Phase 6.
- **EIA Open Data API v2**: weekly petroleum status (Cushing), production, SPR. Free key.
- **Gold/silver ETF holdings** (issuer files) and the **World Gold Council**: check terms before automating downloads.

## 5. Anthropic API (verified 2026-11-01)

| Role (desk.yaml) | Model ID | Input $/MTok | Output $/MTok | Cache read $/MTok |
|---|---|---:|---:|---:|
| triage | `claude-haiku-5-5` | 0.10 (≤100K-token prompts; 0.50 beyond) | 0.50 (2.50 beyond) | not listed; COSTS.md assumes 0.1× input |
| analysis | `claude-sonnet-5-5` | 2.00 | 10.00 | 0.20 |
| synthesis | `claude-opus-5-5` | 4.00 | 20.00 | 0.20 |

Features we'll use, with their current parameter names:
- **Structured outputs:** `output_config: {format: {...}}` on `messages.create`, or `client.messages.parse()` with a Pydantic model. The old `output_format` is deprecated. Strict tool schemas use `strict: true` on the tool.
- **No forced tool choice** on Opus 5.5 / Sonnet 5.5: `tool_choice` `any`/`tool` returns a 400. Use structured outputs instead, which suits us anyway.
- **Thinking:** adaptive by default. It can't be disabled on Opus 5.5. Depth is set with `output_config.effort`, whose default is `medium` on Opus 5.5 and Haiku 5.5 and `high` on Sonnet 5.5. We set it explicitly per agent. Thinking tokens bill as output.
- **Sampling params** (`temperature`/`top_p`/`top_k`) are rejected (400) on current models. Determinism comes from cassettes in tests, not from temperature.
- **Prompt caching:** `cache_control: {type: "ephemeral"}`. Cache writes cost 1.25× input (5-minute TTL), and reads cost about 0.1× input.
- **Message Batches API:** 50% off, used for weekly research and review.
- **Server tools:** `web_search_20260209` / `web_fetch_20260209` with `allowed_domains`. Their errors arrive as result blocks, not exceptions.
- **Refusals:** check `stop_reason == "refusal"` before reading content. Server-side `fallbacks` are available on Opus 5.5 and Sonnet 5.5. A refusal marks that pillar `unavailable` (SPEC §3.4) and never produces a fabricated output.
- **Australian availability:** the first-party Claude API is available to Australian customers. Data handling follows Anthropic's commercial terms.

## 6. Keys you'll need, by phase

| Phase | Key | Where | Free? |
|---|---|---|---|
| 1 | `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID` | oanda.com/au-en → open a demo (practice) account → *Manage API Access* | Free |
| 1 | `TWELVE_DATA_API_KEY` | twelvedata.com → sign up (Basic) | Free |
| 1 | `FRED_API_KEY` | fredaccount.stlouisfed.org → API keys | Free |
| 3 | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | @BotFather → `/newbot`; your chat id via the bot's `getUpdates` | Free |
| 5 | `ANTHROPIC_API_KEY` | console.anthropic.com → API keys (set a spend limit there too) | Paid, usage |
| 5/6 | `FMP_API_KEY` | financialmodelingprep.com → plan that includes the economic calendar | Paid |
| 6 | `EIA_API_KEY` | eia.gov/opendata | Free |
| 6 | `CFTC_SOCRATA_APP_TOKEN` (optional) | publicreporting.cftc.gov → developer settings | Free |
