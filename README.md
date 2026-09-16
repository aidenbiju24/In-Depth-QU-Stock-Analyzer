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
produced by documented, deterministic formulas — all of them listed in the
**Equations** section below and implemented directly in the code.

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

---

## Equations

Every formula below is implemented verbatim in the code — the source module is
cited next to each block. Returns are simple returns; `NaN` is returned rather
than fabricating a value when a metric is undefined.

### 1. Returns and growth

| Formula | Where |
|---|---|
| Simple return: `R = (P_t − P_0) / P_0` | `quant/metrics.py` |
| Daily returns: `R_t = P_t / P_{t−1} − 1` | `quant/metrics.py` |
| Total return over a window: `TR = P_T / P_0 − 1` | `backtest/engine.py` |
| Annualized return (geometric): `R_ann = (1 + TR)^{1/T} − 1`, `T` = years | `quant/metrics.py` |
| Annualized return from daily returns: `R_ann = (∏(1 + r_t))^{252/n} − 1` | `quant/metrics.py` |
| Revenue/EPS CAGR: `CAGR = (X_T / X_0)^{1/T} − 1` (NaN if either term ≤ 0) | `quant/metrics.py` |
| Year-over-year growth: `g = X_now / X_1y − 1` | `quant/model.py` |
| Margin expansion: `ΔOM = EBIT_now/Rev_now − EBIT_1y/Rev_1y` | `quant/model.py` |

### 2. Risk metrics

| Formula | Where |
|---|---|
| Annualized volatility: `σ = std(r, ddof=1) × √252` | `quant/metrics.py` |
| Sharpe ratio: `S = (R_p − R_f) / σ` (all annualized) | `quant/metrics.py` |
| Downside deviation: `DD = √(mean(min(r − MAR, 0)²)) × √252` | `quant/metrics.py` |
| Sortino ratio: `So = (R_p − R_f) / DD` | `quant/metrics.py` |
| Beta: `β = Cov(r_i, r_m) / Var(r_m)` (daily, date-aligned) | `quant/metrics.py` |
| Jensen's alpha: `α = R_p − [R_f + β(R_m − R_f)]` (annualized) | `quant/metrics.py` |
| Drawdown series: `DD_t = V_t / Peak_t − 1` (≤ 0), `Peak_t = max_{s≤t} V_s` | `quant/metrics.py` |
| Max drawdown (magnitude): `MDD = |min_t DD_t|` | `quant/metrics.py` |
| Historical VaR (95%): `VaR = max(0, −quantile(r, 0.05))` | `quant/metrics.py` |
| Expected shortfall: `ES = max(0, −mean(r : r ≤ q_0.05))` | `quant/metrics.py` |
| Win rate: `WR = (1/n) Σ 1[r_t > 0]` | `quant/metrics.py` |
| Information ratio: `IR = (R_p,ann − R_b,ann) / (σ(r_p − r_b) × √252)` | `backtest/engine.py` |

### 3. Factor model — Quant Score (0–100)

Five factors, each scored 0–100, then combined with fixed weights:

```text
QS = 0.20·Value + 0.20·Growth + 0.25·Quality + 0.20·Momentum + 0.15·Risk
```

Source: `quant/factors.py`.

**Metric → factor score.** Each metric is mapped to 0–100 with a
piecewise-linear map between documented anchors `[worst, best]`, direction-
aware and clamped (absolute mode):

```text
higher-is-better:  score = clamp((v − worst) / (best − worst), 0, 1) × 100
lower-is-better:   score = clamp((best − v) / (best − worst), 0, 1) × 100
```

In universe (percentile) mode, metrics are winsorized at the 2.5/97.5
percentiles, then converted to cross-sectional percentile ranks (reversed for
lower-is-better metrics) and scaled by 100.

**Factor score.** Weighted mean of its metrics' scores; missing metrics are
skipped and their weight redistributed:

```text
Factor_f = Σ (w_i · s_i) / Σ w_i        over metrics with data
Coverage_f = Σ w_i (available) / Σ w_i (total)
```

A factor with coverage < 50% is reported missing, never scored. The composite
renormalizes factor weights over available factors the same way.

**Interpretation bands:** ≥ 90 Exceptional · 80–90 Strong · 70–80 Favorable ·
60–70 Neutral/Favorable · 50–60 Neutral · 40–50 Weak · 30–40 Very Weak ·
< 30 Poor.

<details>
<summary>Metric definitions, directions, anchors and weights (click to expand)</summary>

| Metric | Factor | Better | Anchors [worst → best] | Weight in factor |
|---|---|---|---|---|
| P/E (TTM) | Value | lower | 30.0 → 8.0 | 0.20 |
| Forward P/E | Value | lower | 35.0 → 10.0 | 0.15 |
| Price/Book | Value | lower | 8.0 → 1.0 | 0.10 |
| Price/Sales | Value | lower | 10.0 → 1.0 | 0.10 |
| EV/EBITDA | Value | lower | 20.0 → 6.0 | 0.15 |
| FCF yield | Value | higher | 0% → 8% | 0.15 |
| Earnings yield | Value | higher | 0% → 10% | 0.15 |
| Revenue growth (1y) | Growth | higher | −5% → 25% | 0.20 |
| Revenue CAGR (3y) | Growth | higher | −2% → 20% | 0.20 |
| EPS growth (1y) | Growth | higher | −10% → 25% | 0.20 |
| FCF growth (1y) | Growth | higher | −10% → 25% | 0.15 |
| Op. income growth (1y) | Growth | higher | −10% → 25% | 0.15 |
| Margin expansion (1y) | Growth | higher | −2% → 3% | 0.10 |
| ROE | Quality | higher | 0% → 25% | 0.15 |
| ROIC | Quality | higher | 0% → 20% | 0.20 |
| Gross margin | Quality | higher | 10% → 60% | 0.10 |
| Operating margin | Quality | higher | 2% → 30% | 0.15 |
| Net margin | Quality | higher | 1% → 25% | 0.10 |
| FCF margin | Quality | higher | 0% → 15% | 0.10 |
| Debt/Equity | Quality | lower | 2.0 → 0.25 | 0.10 |
| Interest coverage | Quality | higher | 3× → 20× | 0.05 |
| Positive-earnings years (5y) | Quality | higher | 0.5 → 1.0 | 0.05 |
| 1M / 3M / 6M / 12M price return | Momentum | higher | ±10% / −15–20% / −20–30% / −25–35% | 0.10 / 0.15 / 0.20 / 0.20 |
| Positive months (12m) | Momentum | higher | 40% → 75% | 0.15 |
| 12M return vs benchmark | Momentum | higher | −15% → 20% | 0.20 |
| Annualized volatility | Risk | lower | 60% → 15% | 0.30 |
| \|Beta − 1\| | Risk | lower | 0.80 → 0.00 | 0.15 |
| Max drawdown (magnitude) | Risk | lower | 55% → 10% | 0.25 |
| Sharpe ratio (1y) | Risk | higher | −0.5 → 1.5 | 0.20 |
| Downside deviation | Risk | lower | 45% → 10% | 0.10 |

</details>

**Metric construction** (point-in-time; `quant/model.py`):

- `FCF = OperatingCashFlow − |CapEx|`; `FCF yield = FCF / MarketCap`
- `Earnings yield = EPS_diluted / (MarketCap / Shares_diluted)` (fallback `1 / P/E`)
- `ROE = NetIncome / TotalEquity`; `D/E = (LTD + STD) / TotalEquity`
- `ROIC = NOPAT / (Debt + Equity)`, `NOPAT = EBIT × (1 − tax_rate)`,
  `tax_rate = TaxExpense / PretaxIncome`
- `Interest coverage = EBIT / InterestExpense`
- `Earnings consistency = (# of last 5 fiscal years with NetIncome > 0) / 5`
- `Momentum_d = P_now / P_{now − d} − 1` for d ≈ 30/91/182/365 calendar days,
  `Rel. strength = Momentum_12m(stock) − Momentum_12m(benchmark)`
- `Momentum consistency = fraction of positive monthly returns over trailing 12m`

### 4. DCF valuation (unlevered FCFF, Gordon terminal value)

Source: `valuation/dcf.py`. All flows are % of revenue unless stated.

```text
Revenue_t  = Revenue_{t−1} × (1 + g_t)
EBIT_t     = Revenue_t × EBIT margin_t
NOPAT_t    = EBIT_t × (1 − tax rate)
FCFF_t     = NOPAT_t + D&A_t − CapEx_t − ΔWC_t
PV(FCFF)   = Σ_{t=1..n} FCFF_t / (1 + WACC)^t
TV         = FCFF_{n+1} / (WACC − g_term),   FCFF_{n+1} = FCFF_n × (1 + g_term)
PV(TV)     = TV / (1 + WACC)^n
EV         = PV(FCFF) + PV(TV)
Equity     = EV − Net Debt
Fair value = Equity / Diluted shares
Upside     = (Fair value − Price) / Price
```

Constraints: `g_term < WACC` is enforced (cells where `g ≥ WACC` are rejected
in the sensitivity table, not computed); a non-positive final explicit-year
FCFF is flagged as invalid rather than silently scored. The sensitivity table
recomputes fair value across a WACC × terminal-growth grid.

### 5. Portfolio construction

Source: `portfolio/optimizer.py`, `portfolio/analytics.py`.

```text
Expected returns (annualized):  μ_i = mean(r_i) × 252
Covariance (annualized):        Σ_ij = Cov(r_i, r_j) × 252
Portfolio return:               R_p = Σ w_i·μ_i          (vector: w'μ)
Portfolio volatility:           σ_p = √(w' Σ w)
Portfolio Sharpe:               S_p = (w'μ − R_f) / √(w' Σ w)
Correlation:                    ρ_ij = Σ_ij / (σ_i σ_j)
```

Optimization (SciPy SLSQP, multi-start) over long-only weights with
`Σw = 1`, `0 ≤ w_i ≤ max_position`:

| Objective | Minimized |
|---|---|
| Max Sharpe | `−(w'μ − R_f) / √(w'Σw)` |
| Min volatility | `√(w'Σw)` |
| Target return | `√(w'Σw)` subject to `w'μ ≥ R_target` |

The sample covariance is checked for positive semi-definiteness (eigenvalues)
and ridge-corrected if needed; every solution is re-validated against all
constraints before being returned. `highly correlated` pairs are flagged at
|ρ| ≥ 0.85.

### 6. Monte Carlo simulation (Geometric Brownian Motion)

Source: `simulation/monte_carlo.py`. μ/σ are estimated from the last ~2 years
of daily returns ending **before** today (no look-ahead):

```text
σ_ann = std(r, ddof=1) × √252
μ_ann = mean(ln(1 + r)) × 252
S_t   = S_0 × exp( (μ − σ²/2)·t + σ·W_t ),   W_t ~ N(0, t)
```

10,000 seeded paths (default) over a ≤ 5-year horizon; outputs mean, median,
5th/25th/50th/75th/95th percentile paths and terminal values,
`P(gain) = P(S_T > S_0)`. Same seed + same inputs ⇒ identical output.
Documented limitation: GBM is lognormal-iid — fat tails are not captured; the
output is a scenario statistic, never a forecast.

### 7. Backtesting (event-driven, T+1 execution)

Source: `backtest/engine.py`. Timeline discipline:

```text
information at T → signal at T → execute at close of T+1 (lag configurable)
```

The signal context receives price slices strictly ≤ T and factor scores
recomputed from statements whose **filing date** ≤ T, so a strategy can never
see the close it trades at. Accounting holds units and cash; each rebalance
transacts at the execution-date close, paying `(commission_bps + slippage_bps)/10,000`
of transacted value; names without a price that day are skipped to cash and
logged. Rebalance schedules: daily / weekly (Mondays) / monthly (first trading
day) / quarterly (first trading day of Jan/Apr/Jul/Oct). Corporate actions are
handled by using total-return adjusted closes. Factor backtests rank the
universe by the point-in-time factor score and hold the top-N equally weighted.

### 8. Earnings and event studies

Source: `simulation/earnings.py`.

```text
EPS surprise %    = (Actual − Expected) / |Expected|
Revenue surprise % = (Actual − Expected) / |Expected|
Market reaction   = Close(report date) / Close(last close before report date) − 1
Abnormal return   = AR_t = R_stock,t − R_bench,t
CAR               = Σ_{t ∈ window} AR_t
```

The reaction window is anchored on the provider's report date — never the
fiscal period end, which would leak future information.

### 9. Recommendation engine (deterministic rules)

Source: `simulation/recommendation.py`. No ML, no opaque confidence — every
recommendation records the rules that fired.

```text
Points = base(Quant Score) + DCF modifier + momentum ± earnings quality

Base:   QS ≥ 80 → +40 · ≥ 70 → +30 · ≥ 60 → +20 · ≥ 50 → +10 ·
        ≥ 40 → 0  · ≥ 30 → −10 · < 30 → −20
DCF:    upside ≥ +30% → +15 · ≥ +15% → +8 · ≤ −15% → −8 · ≤ −30% → −15
Momo:   12M ≥ +5% → +5 · ≤ −10% → −5
Beats:  beat rate ≥ 70% → +5 · ≤ 40% → −5
Vetoes: volatility ≥ 60% or |MDD| ≥ 55% caps the action at Hold

Action: ≥ +32 Strong Buy · ≥ +18 Buy · ≥ −12 Hold · ≥ −26 Sell · else Strong Sell
```

### 10. Market regime (context only)

Source: `simulation/regime.py` — reported as context, never overrides the
factor model or recommendations.

```text
Trend:        bull if P_last > SMA-200 else bear
Vol regime:   ratio = σ_20d,ann / σ_60d,ann
              high if ratio ≥ 1.15 · low if ratio ≤ 0.85 · normal otherwise
Risk on/off:  risk_on if 3M return(SPY) > 3M return(TLT) else risk_off
```

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

- The **frontend never calls external APIs**. In production it talks to
  FastAPI same-origin through the Next.js rewrite (`/api/*` →
  `QUANT_API_URL`, default `http://127.0.0.1:8000`); in dev it calls
  FastAPI directly on :8000 (Next's dev proxy drops slow/empty POSTs).
- Providers are swappable: each implements the `DataProvider` interface in
  `backend/app/providers/base.py` and returns normalized schemas.
- Credentials live only in the Python process, loaded from `.env.local`
  (repo root or `backend/`).
- SEC fetches are cached (24h companyfacts TTL) and throttled to SEC's
  fair-access limit; Alpha Vantage calls respect a daily budget.

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

# Terminal 2 — research terminal (dev)
npm run dev
```

Open <http://localhost:3000>.

### Production mode

```bash
npm run build
npm run start          # serves the built app + proxies /api to FastAPI
```

Deployment variables (all optional):

- `QUANT_API_URL` — where the Next.js rewrite forwards `/api/*` (default
  `http://127.0.0.1:8000`).
- `NEXT_PUBLIC_QUANT_API_URL` — override the frontend's API base entirely
  (e.g. when FastAPI is exposed on its own domain).
- `CORS_ORIGINS` — comma-separated extra origins allowed by FastAPI when the
  frontend is served cross-origin (default covers localhost/127.0.0.1:3000).
- `QUANT_DB_PATH`, `RISK_FREE_RATE`, `AV_DAILY_BUDGET` — see `.env.example`.

Run uvicorn behind a process manager (or at least `--workers 2`) for
unattended use; SQLite suits a single team's research workload.

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

The pytest suite includes hand-computed financial cases: Sharpe, Sortino,
beta, VaR/ES, CAGR, DCF fair values, optimizer constraints, backtester
look-ahead checks, cache-expiry regression, and an end-to-end pipeline test.

---

## Look-ahead bias discipline

This is the platform's central integrity rule:

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
(survivorship bias). Point-in-time constituent data is not available on free
tiers.

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
