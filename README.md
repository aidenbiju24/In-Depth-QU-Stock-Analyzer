# In-Depth Quant Stock Analyzer

A quantitative investment research platform built for the Wharton Global High
School Investment Competition. It combines fundamental data ingestion, a
five-factor scoring model, DCF valuation, risk analytics, portfolio
optimization, point-in-time backtesting, Monte Carlo simulation, and a fully
auditable research journal.

**The core investment system:**

```text
Data → Metrics → Factors → Valuation → Risk → Portfolio Construction → Backtest → Decision
```

This is not an AI stock picker. Every score, valuation, and recommendation is
produced by documented, deterministic formulas that you can inspect.

---

## What it does

| Capability | Where |
|---|---|
| Factor model (Value 20% / Growth 20% / Quality 25% / Momentum 20% / Risk 15% → 0–100 Quant Score) | `backend/app/quant/` |
| FCFF DCF with WACC × terminal-growth sensitivity | `backend/app/valuation/dcf.py` |
| Volatility, beta, Sharpe, Sortino, VaR, ES, drawdown | `backend/app/quant/metrics.py` |
| Portfolio analytics, correlation, constrained optimizer (max Sharpe / min vol / target return) | `backend/app/portfolio/` |
| Event-based backtester with T+1 execution; factor backtests over point-in-time scores | `backend/app/backtest/engine.py` |
| Seeded Monte Carlo (10,000 paths default) | `backend/app/simulation/monte_carlo.py` |
| Market regime classification (context only — never overrides the model) | `backend/app/simulation/regime.py` |
| Earnings surprises + market reaction | `backend/app/simulation/earnings.py` |
| Rule-based recommendation (Strong Buy → Strong Sell) | `backend/app/simulation/recommendation.py` |
| Research decision journal + model-run audit trail | `backend/app/research/journal.py` |
| Research terminal UI | `app/` (Next.js) |

Authoritative specs: [`PROJECT_SPEC.md`](PROJECT_SPEC.md) and
[`METHODOLOGY.md`](METHODOLOGY.md). The code implements those documents; when
in doubt, the documents win.

---

## Architecture

```text
Alpha Vantage ─┐
               │
SEC EDGAR ─────┼──> providers/ ──> ingestion (normalize, validate) ──> SQLite
               │                                                        │
FMP ───────────┘                                              quantitative engine
                                                                       │
                                        ┌──────────────┬───────────────┤
                                     Factors       Valuation         Risk
                                        └──────────────┴───────────────┘
                                                                       │
                                              portfolio / backtest / journal
                                                                       │
                                              FastAPI (backend/app/api.py)
                                                                       │
                                          Next.js UI (never touches providers)
```

- The **frontend never calls external APIs**. It talks to FastAPI through a
  Next.js rewrite (`/api/*` → `http://127.0.0.1:8000`).
- Providers are swappable: each implements the `DataProvider` interface in
  `backend/app/providers/base.py` and returns normalized schemas.
- Credentials live only in the Python process, loaded from `.env.local`.

---

## Install

Requirements: **Python 3.12+** and **Node 20+**.

```bash
# 1. Python backend
py -3 -m venv .venv                       # Windows (or: python3 -m venv .venv)
./.venv/Scripts/python.exe -m pip install -r backend/requirements.txt   # Windows
# .venv/bin/pip install -r backend/requirements.txt                     # macOS/Linux

# 2. Frontend
npm install
```

## Configure credentials

```bash
cp .env.example .env.local
```

Then edit `.env.local`:

```text
ALPHA_VANTAGE_API_KEY=<your free key>     # https://www.alphavantage.co/support/#api-key
FMP_API_KEY=<your free key>               # https://site.financialmodelingprep.com
SEC_USER_AGENT=Full Name email@example.com
```

Notes:

- `.env.local` is git-ignored and **never** commit it.
- `SEC_USER_AGENT` is **not** an API key. SEC public endpoints require a
  User-Agent header identifying you: `"Sample CompanyName AdminContact@sample.com"`.
  See [SEC fair-access policy](https://www.sec.gov/os/accessing-edgar-data).
- All three providers work on free tiers; the platform targets **$0 operating cost**.

## Run

```bash
# Terminal 1 — quant engine
./.venv/Scripts/python.exe -m uvicorn app.api:app --app-dir backend --port 8000

# Terminal 2 — research terminal
npm run dev
```

Open <http://localhost:3000>.

First workflow: on the **Dashboard**, enter tickers (e.g. `AAPL,MSFT,NVDA`) and
press **Ingest + Analyze**. Data is fetched from providers, normalized,
validated, stored in SQLite, and scored. Then open **Stock Research** for the
full transparency view of any name.

## Run tests

```bash
./.venv/Scripts/python.exe -m pytest backend/tests -q
./.venv/Scripts/python.exe -m ruff check backend
npm run lint        # frontend
npm run build       # typecheck + production build
```

The pytest suite (73 tests) includes hand-computed financial cases: Sharpe,
Sortino, beta, VaR/ES, CAGR, DCF fair values, optimizer constraints,
backtester look-ahead checks, and an end-to-end pipeline test.

---

## Look-ahead bias discipline

This is the platform's central integrity rule (PROJECT_SPEC §51-53):

- Prices used on date T are **strictly ≤ T**.
- Fundamentals used on date T come only from statements whose **filing date**
  (or retrieval date when unknown) is ≤ T. FY2023 results filed 2024-02-15 are
  invisible to a 2024-01-10 decision.
- The backtester executes at the **next bar** after a signal; a strategy can
  never trade on the close it just saw.
- Factor backtests recompute the factor model **as of each rebalance date** —
  today's scores are never retroactively projected onto history.
- Missing data is **never zero-filled or fabricated**. Metrics that cannot be
  computed are marked missing with a reason.

Known limitation: historical factor backtests use today's listed universe
(survivorship bias, PROJECT_SPEC §52). Point-in-time constituent data is not
available on free tiers.

## Database

SQLite at `backend/data/quant.db` (git-ignored). Tables: companies, prices,
financial_statements, fundamentals, earnings, technical_indicators,
factor_scores, valuations, risk_metrics, backtests, portfolios,
portfolio_positions, research_decisions, model_runs. Delete the file to reset.

## Model versions

Factor Model v1.0 · DCF Model v1.0 · Risk Model v1.0 · Portfolio Optimizer
v1.0 · Backtest Engine v1.0 · Monte Carlo v1.0 · Recommendation v1.0.
Versions increment when methodology materially changes; every run records the
version that produced it.
