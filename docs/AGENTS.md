# Agents

The full specifications are in SPEC §5–6. This index tracks the implementation.

| ID | Agent | Engine | Code | Phase | Status |
|---|---|---|---|---|---|
| A0 | Orchestrator + Data Integrity Gate | code | `app/orchestrator/` | 1, 7, 9 | scaffold only |
| A1 | News & Fundamentals | code + LLM | `app/agents/news_fundamentals/` | 5 | — |
| A2 | Macro, Intermarket & Regime | code + LLM | `app/agents/macro_regime/` | 6 | — |
| A3 | Positioning & Sentiment | code + LLM | `app/agents/positioning_sentiment/` | 6 | — |
| A4 | Event-Risk Sentinel | code + LLM (light) | `app/agents/event_risk/` | 6 | — |
| A5 | Style & Strategy Selector + Researcher | code + LLM | `app/agents/style_strategy/` | 4, 7 | — |
| A6 | Multi-Timeframe Technical Analyst | code + LLM | `app/features/` + `app/agents/technical/` | 2, 7 | — |
| A7 | Risk & Capital Manager | code only (hard veto) | `app/risk/` | 3, 7 | — |
| A8 | Red Team | LLM | `app/agents/red_team/` | 7 | — |
| A9 | Chief Strategist | code gates + LLM | `app/agents/chief/` | 7 | — |
| A10 | Position & Thesis Monitor | code + LLM (light) | `app/agents/monitor/` | 3, 9 | — |
| A11 | Performance Auditor | code + LLM (weekly) | `app/agents/auditor/` | 10 | — |
| A12 | Fast Signal Engine | code only | `app/fast/` | 8 | process scaffold (halted) |

Each LLM agent lives in `agents/<name>/{agent.py, schema.py, prompt.md, tests/}`, with `prompt_version` in the prompt's front-matter. Prompts build on the shared skeleton in SPEC §17.1.
