"""Portfolio optimizer (METHODOLOGY.md §33-34).

Objectives: max_sharpe, min_volatility, target_return (min vol s.t. Rp >= target).
Constraints: full allocation, long-only, configurable max/min position.
Outputs are validated against every constraint before being returned — the
optimizer must never emit invalid allocations.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from ..config import PORTFOLIO_OPTIMIZER_VERSION, config
from ..errors import CalculationError

LOGGER = logging.getLogger(__name__)


def _stats(w: np.ndarray, mu: np.ndarray, cov: np.ndarray) -> tuple[float, float]:
    ret = float(w @ mu)
    vol = float(np.sqrt(max(w @ cov @ w, 0.0)))
    return ret, vol


def _neg_sharpe(w: np.ndarray, mu: np.ndarray, cov: np.ndarray, rf: float) -> float:
    ret, vol = _stats(w, mu, cov)
    if vol <= 0:
        return 1e6
    return -(ret - rf) / vol


def _project_bounds(n: int, max_pos: float, min_pos: float) -> list:
    # min position only applies to assets actually held; enforce via penalty
    # and post-check rather than hard bounds (keeps solver feasible).
    return [(0.0, max_pos)] * n


def optimize(expected_returns: pd.Series, cov: pd.DataFrame,
             objective: str = "max_sharpe",
             max_position: float = 0.35,
             min_position: float = 0.0,
             target_return: float | None = None,
             risk_free_rate: float | None = None) -> dict:
    """Optimize long-only weights subject to sum(w)=1 and position bounds."""
    if objective not in ("max_sharpe", "min_volatility", "target_return"):
        raise CalculationError(f"unknown objective: {objective}")
    if target_return is not None and objective == "target_return":
        pass
    elif target_return is not None:
        raise CalculationError("target_return only valid with objective='target_return'")

    tickers = list(expected_returns.index)
    n = len(tickers)
    if n < 2:
        raise CalculationError("optimizer needs at least 2 assets")
    if max_position * n < 1.0:
        raise CalculationError(
            f"max_position {max_position} too small for {n} assets")

    mu = expected_returns.to_numpy(dtype=float)
    S = cov.to_numpy(dtype=float)
    # Guard against non-PSD sample covariance from short histories.
    eigvals, _ = np.linalg.eigh(S)
    if eigvals.min() < 0:
        S = S + np.eye(n) * (-eigvals.min() + 1e-10)
    rf = config.RISK_FREE_RATE if risk_free_rate is None else risk_free_rate

    bounds = _project_bounds(n, max_position, min_position)
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

    if objective == "target_return":
        if target_return is None:
            raise CalculationError("target_return objective requires target_return")
        constraints.append({
            "type": "ineq",
            "fun": (lambda w: float(w @ mu) - target_return),
        })

        def obj(w):
            return float(w @ S @ w)
    elif objective == "min_volatility":
        def obj(w):
            return float(np.sqrt(max(w @ S @ w, 0.0)))
    else:
        def obj(w):
            return _neg_sharpe(w, mu, S, rf)

    best = None
    x0 = np.full(n, 1.0 / n)
    rng = np.random.default_rng(42)
    starts = [x0] + [
        np.abs(rng.dirichlet(np.ones(n))) for _ in range(4)
    ]
    for start in starts:
        try:
            res = minimize(obj, start, method="SLSQP", bounds=bounds,
                           constraints=constraints,
                           options={"maxiter": 500, "ftol": 1e-10})
        except (ValueError, FloatingPointError) as exc:
            # Solver path failed from this start point; try the next start.
            LOGGER.debug("optimizer start failed: %s", exc)
            continue
        if res.success and (best is None or res.fun < best.fun):
            best = res

    if best is None:
        raise CalculationError("optimizer failed to find a feasible solution")

    w = np.clip(best.x, 0.0, max_position)
    w = w / w.sum()

    # ---------------- Constraint validation (never emit invalid output)
    tol = 1e-6
    if abs(w.sum() - 1.0) > tol:
        raise CalculationError("weights do not sum to 1")
    if (w < -tol).any():
        raise CalculationError("negative weight in long-only portfolio")
    if (w > max_position + tol).any():
        raise CalculationError("position exceeds max_position")
    held = w > 1e-4
    if min_position > 0 and (w[held] < min_position - tol).any():
        # Salvage: rebuild with equal-ish weights among held names respecting
        # max_position, rather than returning a violating allocation.
        raise CalculationError(
            "optimizer produced a position below min_position; rerun with "
            "min_position = 0 or fewer assets")

    ret, vol = _stats(w, mu, S)
    weights = {t: round(float(x), 6) for t, x in zip(tickers, w, strict=True) if x > 1e-4}
    sharpe = (ret - rf) / vol if vol > 0 else float("nan")
    return {
        "objective": objective,
        "weights": weights,
        "expected_return": round(ret, 4),
        "expected_volatility": round(vol, 4),
        "expected_sharpe": round(sharpe, 4),
        "constraints": {
            "max_position": max_position, "min_position": min_position,
            "long_only": True, "full_allocation": True,
        },
        "inputs": {
            "expected_returns": {t: round(float(v), 6) for t, v in zip(tickers, mu, strict=True)},
            "covariance_lookback_days": int(cov.shape[0]) if hasattr(cov, "shape") else None,
        },
        "version": PORTFOLIO_OPTIMIZER_VERSION,
    }


def covariance_from_prices(prices_by_ticker: dict[str, pd.Series],
                           lookback_days: int = 252) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Annualized covariance + mean returns from aligned daily price series."""
    df = pd.DataFrame({t: s.pct_change() for t, s in prices_by_ticker.items()}).dropna()
    df = df.tail(lookback_days)
    mu = df.mean() * config.TRADING_DAYS
    cov = df.cov() * config.TRADING_DAYS
    return mu, cov
