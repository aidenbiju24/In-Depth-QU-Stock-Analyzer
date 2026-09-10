"""Earnings analysis (METHODOLOGY.md §47-50) and event studies (§51-52).

Surprises: Actual vs Expected EPS/revenue. Market reaction measured from the
close BEFORE the report date to the close AFTER (single-day window), using the
report date the data provider supplies — never the fiscal period end, which
would leak future information.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

EARNINGS_MODEL_VERSION = "1.0"


def surprise(record: dict) -> dict:
    """Actual, Expected, Surprise and Surprise % for one earnings record."""
    actual = record.get("eps_actual")
    est = record.get("eps_estimated")
    out: dict = {
        "fiscal_date": record.get("fiscal_date"),
        "report_date": record.get("report_date"),
        "eps_actual": actual,
        "eps_estimated": est,
        "eps_surprise": None,
        "eps_surprise_pct": None,
        "revenue_actual": record.get("revenue_actual"),
        "revenue_estimated": record.get("revenue_estimated"),
        "revenue_surprise": None,
        "revenue_surprise_pct": None,
        "market_reaction": None,
    }
    if actual is not None and est is not None and est != 0:
        out["eps_surprise"] = actual - est
        out["eps_surprise_pct"] = (actual - est) / abs(est)
    ra, re_ = record.get("revenue_actual"), record.get("revenue_estimated")
    if ra is not None and re_ not in (None, 0):
        out["revenue_surprise"] = ra - re_
        out["revenue_surprise_pct"] = (ra - re_) / abs(re_)
    return out


def analyze_earnings(records: list[dict], prices: pd.Series) -> dict:
    """Earnings surprise history + post-earnings reactions.

    Reaction convention: close(report_date) / close(last close strictly before
    report_date) - 1. Records without a public report date are excluded from
    reaction measurement (no look-ahead), but still shown as surprises.
    """
    px = prices.dropna().astype(float)
    px.index = pd.to_datetime(px.index)
    rows: list[dict] = []
    for rec in records:
        row = surprise(rec)
        rd = rec.get("report_date")
        if rd is not None:
            rd_ts = pd.Timestamp(rd)
            prior = px.loc[px.index < rd_ts]
            post = px.loc[px.index >= rd_ts]
            if len(prior) > 0 and len(post) > 0:
                prev_close = float(prior.iloc[-1])
                # reaction window = next close on/after report date
                after_close = float(post.iloc[0])
                if prev_close > 0:
                    row["market_reaction"] = after_close / prev_close - 1.0
        for k in ("eps_surprise_pct", "revenue_surprise_pct", "market_reaction"):
            if row[k] is not None and math.isfinite(row[k]):
                row[k] = round(row[k], 4)
        rows.append(row)

    surprises = [r["eps_surprise_pct"] for r in rows
                 if r["eps_surprise_pct"] is not None]
    return {
        "version": EARNINGS_MODEL_VERSION,
        "records": rows,
        "summary": {
            "n_reports": len(rows),
            "n_with_estimates": len(surprises),
            "beat_rate": round(sum(1 for s in surprises if s > 0) / len(surprises), 3)
            if surprises else None,
            "mean_surprise_pct": round(float(np.mean(surprises)), 4)
            if surprises else None,
            "median_surprise_pct": round(float(np.median(surprises)), 4)
            if surprises else None,
        },
    }


def abnormal_returns(prices: pd.Series, benchmark: pd.Series,
                     event_date: str, window: int = 5) -> dict:
    """Abnormal return (stock - benchmark) around an event date (§51).

    AR_t = R_stock,t - R_bench,t ; CAR = cumulative sum over the window.
    Uses data strictly from the event window; no future data beyond the window.
    """
    px = prices.dropna().astype(float)
    bx = benchmark.dropna().astype(float)
    px.index = pd.to_datetime(px.index)
    bx.index = pd.to_datetime(bx.index)
    t0 = pd.Timestamp(event_date)
    # Base price: last close strictly before the event date.
    prior = px.loc[px.index < t0]
    if len(prior) == 0:
        raise ValueError("no price data before event date")
    base_px = float(prior.iloc[-1])
    base_bx_series = bx.loc[bx.index < t0]
    if len(base_bx_series) == 0:
        raise ValueError("no benchmark data before event date")
    base_bx = float(base_bx_series.iloc[-1])

    fwd_px = px.loc[px.index >= t0].head(window)
    fwd_bx = bx.loc[bx.index >= t0].head(window)
    rows: list[dict] = []
    car = 0.0
    for (d_p, p), (_d_b, b) in zip(fwd_px.items(), fwd_bx.items(), strict=False):
        r_s = p / base_px - 1.0 if base_px > 0 else float("nan")
        r_b = b / base_bx - 1.0 if base_bx > 0 else float("nan")
        ar = r_s - r_b
        car += ar if math.isfinite(ar) else 0.0
        rows.append({"date": str(d_p.date()), "stock_return": round(r_s, 4),
                     "benchmark_return": round(r_b, 4), "abnormal_return": round(ar, 4),
                     "cumulative_abnormal_return": round(car, 4)})
    return {
        "event_date": event_date,
        "window_days": window,
        "series": rows,
        "car": round(car, 4),
    }
