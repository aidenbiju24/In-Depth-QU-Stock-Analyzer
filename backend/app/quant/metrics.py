"""Core financial metrics — direct implementations of METHODOLOGY.md formulas.

Every function is pure: numpy arrays / pandas Series in, floats or Series out.
Returns are simple returns. NaN policy: functions return NaN where the input
makes the metric undefined rather than fabricating values.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252
_VOL_EPS = 1e-12   # volatility below this is floating-point noise, not data


# --------------------------------------------------------------- returns
def simple_return(p0: float, pt: float) -> float:
    """METHODOLOGY §4: R = (Pt - P0) / P0."""
    if p0 == 0:
        return float("nan")
    return (pt - p0) / p0


def price_series_returns(prices: pd.Series) -> pd.Series:
    """Daily simple returns from a price series (first value -> NaN)."""
    return prices.astype(float).pct_change()


def annualized_return(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    """Geometric annualization of daily simple returns."""
    r = returns.dropna()
    if len(r) == 0:
        return float("nan")
    growth = float(np.prod(1.0 + r.to_numpy()))
    if growth <= 0:
        return -1.0
    years = len(r) / periods_per_year
    return growth ** (1.0 / years) - 1.0


def annualized_return_from_total(total_return: float, years: float) -> float:
    """METHODOLOGY §5: (Pt/P0)^(1/T) - 1."""
    if years <= 0:
        return float("nan")
    growth = 1.0 + total_return
    if growth <= 0:
        return -1.0
    return growth ** (1.0 / years) - 1.0


def cagr(x0: float, xt: float, years: float) -> float:
    """METHODOLOGY §14. Returns NaN when economically meaningless (x0 <= 0,
    xt <= 0, or years <= 0) — never a fabricated number."""
    if x0 is None or xt is None or years is None or years <= 0:
        return float("nan")
    if x0 <= 0 or xt <= 0:
        return float("nan")
    return (xt / x0) ** (1.0 / years) - 1.0


# ------------------------------------------------------------- volatility
def volatility(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    """METHODOLOGY §6: sigma_daily * sqrt(252)."""
    r = returns.dropna()
    if len(r) < 2:
        return float("nan")
    return float(r.std(ddof=1) * np.sqrt(periods_per_year))


# ---------------------------------------------------------------- Sharpe
def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0,
                 periods_per_year: int = TRADING_DAYS) -> float:
    """METHODOLOGY §7: (Rp - Rf) / sigma_p, all annualized.

    Volatility below _VOL_EPS is treated as degenerate (no dispersion) and
    yields NaN rather than an astronomically large ratio."""
    vol = volatility(returns, periods_per_year)
    if not np.isfinite(vol) or vol <= _VOL_EPS:
        return float("nan")
    rp = annualized_return(returns, periods_per_year)
    return (rp - risk_free_rate) / vol


# --------------------------------------------------------------- Sortino
def downside_deviation(returns: pd.Series, mar: float = 0.0,
                       periods_per_year: int = TRADING_DAYS) -> float:
    """Downside deviation vs a minimum acceptable return (MAR), annualized.

    Uses the full-sample downside RMS: sqrt(mean(min(r - MAR, 0)^2)) * sqrt(N).
    """
    r = returns.dropna()
    if len(r) == 0:
        return float("nan")
    downside = np.minimum(r.to_numpy() - mar, 0.0)
    dd_daily = float(np.sqrt(np.mean(downside ** 2)))
    return dd_daily * np.sqrt(periods_per_year)


def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.0,
                  mar: float = 0.0, periods_per_year: int = TRADING_DAYS) -> float:
    """METHODOLOGY §8: (Rp - Rf) / DownsideDeviation."""
    dd = downside_deviation(returns, mar, periods_per_year)
    if not np.isfinite(dd) or dd <= _VOL_EPS:
        return float("nan")
    rp = annualized_return(returns, periods_per_year)
    return (rp - risk_free_rate) / dd


# ----------------------------------------------------------------- beta
def beta(security_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """METHODOLOGY §10: Cov(Ri, Rm) / Var(Rm), daily then aligned by date."""
    joined = pd.concat([security_returns.rename("s"),
                        benchmark_returns.rename("m")], axis=1).dropna()
    if len(joined) < 3:
        return float("nan")
    var_m = joined["m"].var(ddof=1)
    if var_m == 0:
        return float("nan")
    cov = joined["s"].cov(joined["m"])
    return float(cov / var_m)


# -------------------------------------------------------------- drawdown
def drawdown_series(values: pd.Series) -> pd.Series:
    """METHODOLOGY §9: DD_t = (V_t - Peak_t) / Peak_t (<= 0)."""
    v = values.astype(float)
    peak = v.cummax()
    return v / peak - 1.0


def max_drawdown(values: pd.Series) -> float:
    """Most negative drawdown; returned as a negative fraction."""
    dd = drawdown_series(values)
    if len(dd) == 0:
        return float("nan")
    return float(dd.min())


def max_drawdown_positive(values: pd.Series) -> float:
    """Display convention (METHODOLOGY §9): magnitude as a positive percent."""
    mdd = max_drawdown(values)
    return abs(mdd) if np.isfinite(mdd) else float("nan")


# ------------------------------------------------------- VaR / shortfall
def historical_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """METHODOLOGY §36: historical VaR as a positive loss fraction."""
    r = returns.dropna()
    if len(r) < 10:
        return float("nan")
    alpha = 1.0 - confidence
    # A loss metric cannot be negative: if the worst 5% of days still gained
    # money, VaR is 0 (no loss), not a negative number.
    return float(max(0.0, -np.quantile(r.to_numpy(), alpha)))


def expected_shortfall(returns: pd.Series, confidence: float = 0.95) -> float:
    """METHODOLOGY §37: mean loss beyond the VaR threshold (positive fraction)."""
    r = returns.dropna()
    if len(r) < 10:
        return float("nan")
    alpha = 1.0 - confidence
    q = np.quantile(r.to_numpy(), alpha)
    tail = r.to_numpy()[r.to_numpy() <= q]
    if len(tail) == 0:
        return float(max(0.0, -q))
    return float(max(0.0, -tail.mean()))


def win_rate(returns: pd.Series) -> float:
    r = returns.dropna()
    if len(r) == 0:
        return float("nan")
    return float((r > 0).mean())


# ----------------------------------------------------------- correlation
def correlation_matrix(returns_df: pd.DataFrame) -> pd.DataFrame:
    """METHODOLOGY §35: pairwise Pearson correlation of returns."""
    return returns_df.corr(min_periods=10)


# ------------------------------------------------------ portfolio helpers
def portfolio_return_series(weights: dict[str, float],
                            returns_df: pd.DataFrame) -> pd.Series:
    """METHODOLOGY §31: R_p = sum(w_i * R_i) over aligned dates."""
    cols = [c for c in weights if c in returns_df.columns]
    if not cols:
        return pd.Series(dtype=float)
    w = np.array([weights[c] for c in cols])
    sub = returns_df[cols].fillna(0.0)
    return sub.mul(w, axis=1).sum(axis=1)


def portfolio_volatility(weights: np.ndarray, cov: np.ndarray) -> float:
    """METHODOLOGY §32: sqrt(w' Sigma w)."""
    w = np.asarray(weights, dtype=float)
    return float(np.sqrt(max(w @ cov @ w, 0.0)))


def alpha(returns: pd.Series, benchmark_returns: pd.Series,
          beta_value: float, risk_free_rate: float = 0.0,
          periods_per_year: int = TRADING_DAYS) -> float:
    """Annualized Jensen-style alpha: Rp - [Rf + beta*(Rm - Rf)]."""
    joined = pd.concat([returns.rename("s"),
                        benchmark_returns.rename("m")], axis=1).dropna()
    if len(joined) < 10:
        return float("nan")
    rp = annualized_return(joined["s"], periods_per_year)
    rm = annualized_return(joined["m"], periods_per_year)
    return rp - (risk_free_rate + beta_value * (rm - risk_free_rate))
