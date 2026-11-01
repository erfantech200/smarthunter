# Costs — first estimate (Phase 0, 2026-11-01)

These are estimates from a model, not measurements. Phase 5 replaces them with real numbers from the `llm_calls` cost ledger, as SPEC §22 "Cost test" requires. Re-run the model at any time:

```bash
python infra/scripts/estimate_llm_cost.py
```

Every assumption (tokens per call, calls per day, cache share, skip rates) is a named constant in that script.

## LLM (Anthropic), USD per month, 22 trading days

| Line item | Lean | Spec default | Heavy |
|---|---:|---:|---:|
| A1 news (triage + deep + briefs) | $38 | $110 | $243 |
| A2 + A4 (per session run) | $10 | $20 | $20 |
| A5 + A6 + A8 decision chain | $48 | $133 | $305 |
| A9 synthesis | $32 | $181 | $413 |
| A10 thesis checks | <$1 | <$1 | <$1 |
| Weekly batch (A3, A5 research, A11) | $2 | $2 | $2 |
| Web search (A1 follow-up) | $2 | $4 | $13 |
| **Total** | **$133** | **$451** | **$996** |

- **Lean:** news every 4h, 2 session runs (London + NY), Sonnet for A9.
- **Spec default:** news every 2h, 4 runs a day plus about 3 event reruns, Opus for A9.
- **Heavy:** denser news around sessions, many event reruns, Opus for A9.

**What drives the bill:**
1. **A9 on Opus is the largest single item** in the spec-default scenario (about 40%). A9 on Sonnet 5.5 costs half per token. The budget guard already downgrades A9 to the analysis model at 80% of budget (SPEC §17). Proposal: start A9 on **Sonnet**, run Opus as a shadow on a sample, and promote Opus only if A11 shows it adds value.
2. **Event reruns × 7 assets.** A full rerun of stages 2–6 for all 7 assets costs about $3.40 with Opus as A9, or about $2.40 with Sonnet. The short-circuit rules (unchanged hashes skip stages 2–6) and *per-asset* reruns (only the affected assets) are the main levers.
3. **Thinking tokens bill as output.** The model assumes 1–6k thinking tokens per call. `output_config.effort` is set per agent. Triage and A4 run at `low`.
4. **Prompt caching** covers static system prompts, driver maps and strategy descriptions. The model assumes only 25% of input is cached, which is conservative.

**Budget guard behaviour (SPEC §17):** at 80% of `llm.monthly_budget_usd`, synthesis drops to the analysis model and frequency drops. At 100%, only deterministic code runs: A12 keeps working on the last valid snapshots until they expire, and My Book and A10 level alerts keep working. You get an alert either way.

## Market data, USD per month

| Option | Monthly |
|---|---:|
| Recommended: OANDA practice + Twelve Data Basic + free official sources + FMP calendar | **≈ $29–69** |
| + Twelve Data Grow (wider second source) | + ≈ $79 |
| + Twelve Data Pro (full WebSocket as a backup stream) | + ≈ $191–229 |
| + Databento CME live (oil term structure, real futures volume) | + ≥ $199 |

Prices marked unverified in `docs/PROVIDERS.md` must be confirmed on the official pages before you subscribe.

## Hosting

| Item | Monthly (indicative, unverified) |
|---|---:|
| VPS, 4 vCPU / 8–16 GB / 160+ GB SSD (Vultr or DigitalOcean Sydney, Hetzner/OVH EU for feed latency) | ≈ $40–100 |
| Off-site encrypted backups (S3-compatible object storage, Backblaze B2 or similar) | ≈ $1–5 |
| Tailscale (personal plan) or Cloudflare Access (free tier) | $0 |
| **Hosting total** | **≈ $45–105** |

## All-in monthly range

| Scenario | LLM | Data | Hosting | **Total** |
|---|---:|---:|---:|---:|
| Lean | ≈ $133 | ≈ $30–70 | ≈ $45–105 | **≈ $210–310** |
| Spec default | ≈ $451 | ≈ $30–70 | ≈ $45–105 | **≈ $525–625** |
| Heavy | ≈ $996 | ≈ $110–300 | ≈ $45–105 | **≈ $1,150–1,400** |
