"""Monte Carlo simulation (METHODOLOGY.md §38-40).

Geometric Brownian Motion on the price level:

    S_t = S_0 * exp( (mu - sigma^2/2) t + sigma W_t ),  W_t ~ N(0, t)

mu, sigma are annualized from historical returns (documented limitation: a GBM
treats the future as lognormal iid; fat tails are NOT captured — results are
scenario statistics, never forecasts). Simulations are reproducible via seed
(METHODOLOGY §40). A fixed-seed run of the same inputs gives identical output.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import MONTE_CARLO_VERSION
from ..errors import CalculationError

TRADING_DAYS = 252


@dataclass
class MonteCarloResult:
    ticker: str
    current_price: float
    days: int
    n_simulations: int
    mu_annual: float
    sigma_annual: float
    seed: int
    mean: float
    median: float
    std: float
    p05: float
    p25: float
    p75: float
    p95: float
    prob_gain: float
    prob_loss: float
    percentile_path: dict = field(default_factory=dict)   # p5/p25/p50/p75/p95 by day
    version: str = MONTE_CARLO_VERSION

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "current_price": self.current_price,
            "days": self.days,
            "n_simulations": self.n_simulations,
            "mu_annual": round(self.mu_annual, 4),
            "sigma_annual": round(self.sigma_annual, 4),
            "seed": self.seed,
            "mean": round(self.mean, 2),
            "median": round(self.median, 2),
            "std": round(self.std, 2),
            "p05": round(self.p05, 2),
            "p25": round(self.p25, 2),
            "p75": round(self.p75, 2),
            "p95": round(self.p95, 2),
            "prob_gain": round(self.prob_gain, 4),
            "prob_loss": round(self.prob_loss, 4),
            "percentile_path": self.percentile_path,
            "version": self.version,
            "disclaimer": ("Statistical scenario based on historical mu/sigma "
                           "under lognormal iid assumptions — NOT a forecast."),
        }


def run_monte_carlo(prices, ticker: str, days: int = 252,
                    n_simulations: int = 10_000, seed: int | None = 42,
                    horizon_days_history: int = 504) -> MonteCarloResult:
    """Simulate `n_simulations` price paths `days` trading days ahead.

    mu/sigma estimated from the last `horizon_days_history` calendar days of
    adjusted closes available BEFORE today (no look-ahead: estimation uses the
    same series the user can already see).
    """
    if n_simulations < 100:
        raise CalculationError("n_simulations must be >= 100")
    if days < 1 or days > 252 * 5:
        raise CalculationError("days must be in [1, 1260]")
    s = prices.dropna().astype(float)
    if len(s) < 60:
        raise CalculationError(
            f"need >= 60 price observations for Monte Carlo, got {len(s)}")
    s = s.tail(horizon_days_history)
    rets = s.pct_change().dropna()
    if len(rets) < 59:
        raise CalculationError("insufficient return observations")

    sigma_annual = float(rets.std(ddof=1) * np.sqrt(TRADING_DAYS))
    log_rets = np.log(1.0 + rets)
    mu_annual = float(log_rets.mean() * TRADING_DAYS)

    s0 = float(s.iloc[-1])
    dt = 1.0 / TRADING_DAYS
    rng = np.random.default_rng(seed if seed is not None else 42)

    # Vectorized: (n_sims, days) standard normals -> cumulative sum.
    z = rng.standard_normal((n_simulations, days))
    drift = (mu_annual - 0.5 * sigma_annual ** 2) * dt
    log_increments = drift + sigma_annual * np.sqrt(dt) * z
    log_paths = np.cumsum(log_increments, axis=1)
    paths = s0 * np.exp(log_paths)          # (n_sims, days), day 1..days

    finals = paths[:, -1]
    pct = np.percentile(paths, [5, 25, 50, 75, 95], axis=0)

    return MonteCarloResult(
        ticker=ticker,
        current_price=round(s0, 4),
        days=days,
        n_simulations=n_simulations,
        mu_annual=mu_annual,
        sigma_annual=sigma_annual,
        seed=int(seed if seed is not None else 42),
        mean=float(finals.mean()),
        median=float(np.median(finals)),
        std=float(finals.std(ddof=1)),
        p05=float(pct[0, -1]),
        p25=float(pct[1, -1]),
        p75=float(pct[3, -1]),
        p95=float(pct[4, -1]),
        prob_gain=float((finals > s0).mean()),
        prob_loss=float((finals < s0).mean()),
        percentile_path={
            "days": list(range(1, days + 1)),
            "p5": [round(float(x), 4) for x in pct[0]],
            "p25": [round(float(x), 4) for x in pct[1]],
            "p50": [round(float(x), 4) for x in pct[2]],
            "p75": [round(float(x), 4) for x in pct[3]],
            "p95": [round(float(x), 4) for x in pct[4]],
        },
    )


def scenario_analysis(base_fair_value: float,
                      shocks: list[dict] | None = None) -> list[dict]:
    """Simple scenario grid on DCF fair value (METHODOLOGY §40).

    Each scenario scales revenue growth by a documented shock factor. Returns
    the scenario table; the caller applies it via run_dcf for transparency.
    """
    scenarios = shocks or [
        {"name": "Bear", "revenue_shock": -0.30},
        {"name": "Base", "revenue_shock": 0.0},
        {"name": "Bull", "revenue_shock": +0.30},
    ]
    return [
        {
            "name": sc["name"],
            "revenue_shock": sc["revenue_shock"],
            "base_fair_value": round(base_fair_value, 2),
        }
        for sc in scenarios
    ]
