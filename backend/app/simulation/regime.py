"""Market regime classification (METHODOLOGY.md §39).

Observable inputs only: benchmark price trend and realized volatility of the
benchmark plus a representative risk-on/risk-off proxy pair. The regime is
reported as context — it NEVER overrides the factor model or the
recommendation engine (PROJECT_SPEC §30).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

REGIME_MODEL_VERSION = "1.0"

# Documented thresholds (METHODOLOGY §39): SMA-200 filter + 20d vs 60d vol.
HIGH_VOL_RATIO = 1.15      # vol20 / vol60 above this => high-vol regime
LOW_VOL_RATIO = 0.85       # below this => low-vol regime
TREND_WINDOW = 200         # SMA window for trend classification
OFFENSIVE = "SPY"          # risk-on proxy default
DEFENSIVE = "TLT"          # risk-off proxy default


def _trend(bench: pd.Series, on: pd.Timestamp) -> str:
    window = bench.loc[:on].tail(TREND_WINDOW)
    if len(window) < TREND_WINDOW // 2:
        return "unknown"
    sma = float(window.mean())
    last = float(window.iloc[-1])
    if not math.isfinite(sma) or sma == 0:
        return "unknown"
    return "bull" if last > sma else "bear"


def _vol_regime(bench: pd.Series, on: pd.Timestamp) -> str:
    window = bench.loc[:on].tail(120)
    if len(window) < 80:
        return "unknown"
    r = window.pct_change().dropna()
    vol20 = float(r.tail(20).std(ddof=1) * np.sqrt(252))
    vol60 = float(r.tail(60).std(ddof=1) * np.sqrt(252))
    if not (math.isfinite(vol20) and math.isfinite(vol60)) or vol60 == 0:
        return "unknown"
    ratio = vol20 / vol60
    if ratio >= HIGH_VOL_RATIO:
        return "high_volatility"
    if ratio <= LOW_VOL_RATIO:
        return "low_volatility"
    return "normal_volatility"


def _risk_on_off(spy: pd.Series | None, tlt: pd.Series | None,
                 on: pd.Timestamp) -> str:
    """Compare 3-month returns of the risk-on and risk-off proxies."""
    if spy is None or tlt is None:
        return "unknown"
    s = spy.loc[:on].tail(63)
    t = tlt.loc[:on].tail(63)
    if len(s) < 40 or len(t) < 40:
        return "unknown"
    r_on = float(s.iloc[-1] / s.iloc[0] - 1.0)
    r_off = float(t.iloc[-1] / t.iloc[0] - 1.0)
    if not (math.isfinite(r_on) and math.isfinite(r_off)):
        return "unknown"
    return "risk_on" if r_on > r_off else "risk_off"


def classify_regime(benchmark: pd.Series, on: pd.Timestamp,
                    spy: pd.Series | None = None,
                    tlt: pd.Series | None = None) -> dict:
    """Classify the regime using only data available on/before `on`."""
    inputs = {
        "benchmark_observations": int(benchmark.loc[:on].shape[0]),
        "as_of": str(on.date()),
    }
    trend = _trend(benchmark, on)
    vol = _vol_regime(benchmark, on)
    r = _risk_on_off(spy, tlt, on)
    # Primary label: trend dominates; vol and risk proxies recorded alongside.
    primary = trend if trend != "unknown" else (
        "high_volatility" if vol == "high_volatility" else "indeterminate")
    return {
        "version": REGIME_MODEL_VERSION,
        "as_of": str(on.date()),
        "primary_regime": primary,
        "trend": trend,
        "volatility_regime": vol,
        "risk_on_off": r,
        "inputs": inputs,
        "note": ("Regime is context only; it does not modify factor scores "
                 "or recommendations."),
    }
