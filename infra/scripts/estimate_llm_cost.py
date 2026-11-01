"""First-pass LLM cost model for docs/COSTS.md (SPEC §22 "Cost test", Phase 0 estimate).

Code does the math (SPEC §3.1): every assumption is a named constant below, so the estimate
can be re-run when real token counts arrive from the cost ledger in Phase 5.

    python infra/scripts/estimate_llm_cost.py          # prints the markdown tables

Prices: Anthropic first-party list prices per million tokens, checked 2026-11-01
(docs/PROVIDERS.md). Thinking tokens bill as output tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal

D = Decimal
M = D(1_000_000)

# --- price list (USD per MTok) -------------------------------------------------------------
PRICES = {
    "haiku": {"in": D("0.10"), "out": D("0.50"), "cache_read": D("0.01")},
    "sonnet": {"in": D("2.00"), "out": D("10.00"), "cache_read": D("0.20")},
    "opus": {"in": D("4.00"), "out": D("20.00"), "cache_read": D("0.20")},
}
CACHE_WRITE_MULT = D("1.25")  # 5-minute cache writes
BATCH_DISCOUNT = D("0.5")  # Message Batches API
WEB_SEARCH_PER_1K = D("10")

TRADING_DAYS_PER_MONTH = 22
WEEKS_PER_MONTH = D("4.33")
ASSETS = 7


@dataclass(frozen=True)
class Call:
    """One kind of LLM call. Tokens are per call; thinking counts as output."""

    name: str
    tier: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int = 0
    cached_share: D = D("0.25")  # share of input served from prompt cache (static system prompt etc.)
    batch: bool = False

    def cost(self) -> D:
        p = PRICES[self.tier]
        cached = D(self.input_tokens) * self.cached_share
        fresh = D(self.input_tokens) - cached
        # amortise: assume each cached prefix is written once per ~10 reads
        write = cached / 10 * p["in"] * CACHE_WRITE_MULT
        c = (fresh * p["in"] + cached * p["cache_read"] + write + D(self.output_tokens + self.thinking_tokens) * p["out"]) / M
        return c * (BATCH_DISCOUNT if self.batch else 1)


@dataclass(frozen=True)
class Scenario:
    name: str
    news_cycles_per_day: int
    triage_clusters_per_cycle: int
    deep_clusters_per_cycle: int
    brief_change_rate: D  # share of (cycle × asset) where something material changed → brief regenerated
    pipeline_runs_per_day: int  # scheduled session runs (weekly_open amortised in)
    event_reruns_per_day: int  # breaking news / regime-change mini-runs
    short_circuit_rate: D  # share of pipeline asset-runs that skip stages 2–6 (unchanged hashes)
    synthesis_tier: str = "opus"
    thesis_checks_per_day: int = 20
    web_searches_per_day: int = 20
    notes: str = ""
    overrides: dict[str, Call] = field(default_factory=dict)


CALLS = {
    "a1_triage": Call("A1 triage (per cluster)", "haiku", 700, 150, cached_share=D("0.6")),
    "a1_deep": Call("A1 deep analysis (per top-K cluster)", "sonnet", 6_000, 1_200, 1_000),
    "a1_brief": Call("A1 FundamentalBrief (per asset)", "sonnet", 8_000, 1_500, 1_500),
    "a2": Call("A2 macro & regime narrative (per asset)", "sonnet", 6_000, 1_200, 1_000),
    "a4": Call("A4 event-risk note (per asset)", "haiku", 3_000, 500),
    "a5": Call("A5 style selection (per asset)", "sonnet", 8_000, 1_500, 2_000),
    "a6": Call("A6 technical judgment (per asset)", "sonnet", 15_000, 2_500, 3_000),
    "a8": Call("A8 red team (per asset)", "sonnet", 18_000, 2_000, 3_000),
    "a9": Call("A9 chief strategist (per asset)", "opus", 25_000, 4_000, 6_000),
    "a10": Call("A10 thesis check (per check)", "haiku", 3_000, 400),
    "a3_weekly": Call("A3 positioning (per asset, weekly)", "sonnet", 6_000, 1_200, 1_000, batch=True),
    "a11_weekly": Call("A11 weekly review", "sonnet", 100_000, 8_000, 8_000, batch=True),
    "a5_research": Call("A5 research spec (per idea, weekly ×10)", "sonnet", 10_000, 2_000, 2_000, batch=True),
}


def monthly(s: Scenario) -> dict[str, D]:
    c = {**CALLS, **s.overrides}
    a9 = replace(c["a9"], tier=s.synthesis_tier)
    td = TRADING_DAYS_PER_MONTH
    runs = D(s.pipeline_runs_per_day + s.event_reruns_per_day) * ASSETS * (1 - s.short_circuit_rate)
    out = {
        "A1 news (triage + deep + briefs)": td
        * s.news_cycles_per_day
        * (
            s.triage_clusters_per_cycle * c["a1_triage"].cost()
            + s.deep_clusters_per_cycle * c["a1_deep"].cost()
            + ASSETS * s.brief_change_rate * c["a1_brief"].cost()
        ),
        "A2 + A4 (per session run)": td * D(s.pipeline_runs_per_day) * ASSETS * (c["a2"].cost() + c["a4"].cost()),
        "A5 + A6 + A8 decision chain": td * runs * (c["a5"].cost() + c["a6"].cost() + c["a8"].cost()),
        f"A9 synthesis ({s.synthesis_tier})": td * runs * a9.cost(),
        "A10 thesis checks": td * s.thesis_checks_per_day * c["a10"].cost(),
        "Weekly batch (A3, A5 research, A11)": WEEKS_PER_MONTH
        * (ASSETS * c["a3_weekly"].cost() + 10 * c["a5_research"].cost() + c["a11_weekly"].cost()),
        "Web search (A1 follow-up)": td * D(s.web_searches_per_day) * WEB_SEARCH_PER_1K / 1000,
    }
    out["Total"] = sum(out.values(), D(0))
    return out


SCENARIOS = [
    Scenario(
        "Lean",
        news_cycles_per_day=6,
        triage_clusters_per_cycle=80,
        deep_clusters_per_cycle=5,
        brief_change_rate=D("0.4"),
        pipeline_runs_per_day=2,
        event_reruns_per_day=1,
        short_circuit_rate=D("0.5"),
        synthesis_tier="sonnet",
        web_searches_per_day=10,
        notes="news every 4h, 2 session runs (London + NY), Sonnet for A9",
    ),
    Scenario(
        "Spec default",
        news_cycles_per_day=12,
        triage_clusters_per_cycle=120,
        deep_clusters_per_cycle=8,
        brief_change_rate=D("0.5"),
        pipeline_runs_per_day=4,
        event_reruns_per_day=3,
        short_circuit_rate=D("0.4"),
        notes="news every 2h, 4 runs/day + ~3 event reruns, Opus for A9",
    ),
    Scenario(
        "Heavy",
        news_cycles_per_day=18,
        triage_clusters_per_cycle=200,
        deep_clusters_per_cycle=12,
        brief_change_rate=D("0.7"),
        pipeline_runs_per_day=4,
        event_reruns_per_day=8,
        short_circuit_rate=D("0.2"),
        web_searches_per_day=60,
        notes="denser news around sessions, many event reruns, Opus for A9",
    ),
]


def _usd(x: D) -> str:
    if x < 1:
        return "<$1"
    return f"${x.quantize(D('1'), rounding=ROUND_HALF_UP):,}"


def main() -> None:
    results = {s.name: monthly(s) for s in SCENARIOS}
    lines = ["| Line item | " + " | ".join(results) + " |", "|---|" + "---:|" * len(results)]
    for item in next(iter(results.values())):
        label = item if not item.startswith("A9") else "A9 synthesis"
        row = [_usd(r[k]) for r in results.values() for k in r if k == item or (k.startswith("A9") and item.startswith("A9"))]
        bold = "**" if item == "Total" else ""
        lines.append(f"| {bold}{label}{bold} | " + " | ".join(f"{bold}{v}{bold}" for v in row) + " |")
    print("\n".join(lines))
    print()
    for s in SCENARIOS:
        print(f"- **{s.name}:** {s.notes}.")
    print()
    print("| Call | Model | In | Out | Thinking | Cost/call |")
    print("|---|---|---:|---:|---:|---:|")
    for c in CALLS.values():
        print(f"| {c.name} | {c.tier} | {c.input_tokens:,} | {c.output_tokens:,} | {c.thinking_tokens:,} | ${c.cost():.4f} |")


if __name__ == "__main__":
    main()
