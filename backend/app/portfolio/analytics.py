"""Portfolio analytics (METHODOLOGY.md §31-37)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import RISK_MODEL_VERSION, config
from ..quant import metrics as M


def portfolio_stats(returns: pd.Series, benchmark_returns: pd.Series | None = None,
                    risk_free_rate: float | None = None) -> dict:
    """Full performance/risk summary for a return series."""
    rf = config.RISK_FREE_RATE if risk_free_rate is None else risk_free_rate
    stats = {
        "annualized_return": M.annualized_return(returns),
        "volatility": M.volatility(returns),
        "sharpe": M.sharpe_ratio(returns, rf),
        "sortino": M.sortino_ratio(returns, rf),
        "downside_deviation": M.downside_deviation(returns),
        "win_rate": M.win_rate(returns),
        "var_95_daily": M.historical_var(returns, 0.95),
        "var_99_daily": M.historical_var(returns, 0.99),
        "expected_shortfall_95_daily": M.expected_shortfall(returns, 0.95),
    }
    if benchmark_returns is not None and len(benchmark_returns.dropna()) > 0:
        b = M.beta(returns, benchmark_returns)
        stats["beta"] = b
        stats["alpha"] = M.alpha(returns, benchmark_returns, b, rf)
    return stats


def equity_curve(returns: pd.Series, initial_capital: float = 1.0) -> pd.Series:
    r = returns.dropna()
    return initial_capital * (1 + r).cumprod()


def correlation_analysis(prices_by_ticker: dict[str, pd.Series],
                         lookback_days: int = 252) -> dict:
    """Correlation matrix + concentration diagnostics (METHODOLOGY §35)."""
    df = pd.DataFrame({t: s.pct_change() for t, s in prices_by_ticker.items()})
    df = df.dropna(how="all").tail(lookback_days)
    corr = M.correlation_matrix(df)
    pairs = []
    tickers = list(corr.columns)
    for i, a in enumerate(tickers):
        for j in range(i + 1, len(tickers)):
            b = tickers[j]
            rho = corr.iloc[i, j]
            if np.isfinite(rho):
                pairs.append({"a": a, "b": b, "correlation": round(float(rho), 3)})
    pairs.sort(key=lambda p: -abs(p["correlation"]))
    highly_correlated = [p for p in pairs if p["correlation"] >= 0.85]
    return {
        "matrix": corr.round(3).to_dict(),
        "tickers": tickers,
        "pairs_sorted": pairs,
        "highly_correlated": highly_correlated,
        "mean_abs_correlation": round(float(np.nanmean(np.abs(corr.to_numpy()))), 3)
        if len(tickers) > 1 else None,
    }


def model_version() -> str:
    return RISK_MODEL_VERSION
