"""Factor scoring engines (METHODOLOGY.md §11-22).

Single source of truth for metric definitions:
- direction: higher-is-better or lower-is-better
- band: documented absolute scoring anchors [worst, best] for single-security
  scoring (piecewise linear, values clamped into the band)
- weight: metric weight inside its factor (sums to 1.0 per factor)

Two normalization modes, both documented in METHODOLOGY.md §12:
- "absolute": piecewise-linear mapping onto the band anchors. Used when no
  comparison universe is available.
- "percentile": cross-sectional percentile across the universe (winsorized at
  2.5/97.5). Used for rankings and factor backtesting.

Missing data policy (§55): a metric that cannot be computed is skipped, its
weight redistributed to the remaining metrics of the same factor, and the
factor's data-coverage fraction reflects it. A factor with <50% coverage is
reported missing rather than scored. Nothing is zero-filled.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Factor weights (METHODOLOGY.md §21).
FACTOR_WEIGHTS: dict[str, float] = {
    "value": 0.20,
    "growth": 0.20,
    "quality": 0.25,
    "momentum": 0.20,
    "risk": 0.15,
}


@dataclass(frozen=True)
class MetricDef:
    name: str
    factor: str          # value | growth | quality | momentum | risk
    direction: str       # higher | lower  (which direction is better)
    band: tuple[float, float]   # [worst, best] anchors for absolute mode
    weight: float
    label: str


def _m(name, factor, direction, band, weight, label) -> MetricDef:
    return MetricDef(name, factor, direction, band, weight, label)


METRIC_DEFS: list[MetricDef] = [
    # ---------------- Value (§11)
    _m("pe", "value", "lower", (8.0, 30.0), 0.20, "P/E (TTM)"),
    _m("forward_pe", "value", "lower", (10.0, 35.0), 0.15, "Forward P/E"),
    _m("pb", "value", "lower", (1.0, 8.0), 0.10, "Price/Book"),
    _m("ps", "value", "lower", (1.0, 10.0), 0.10, "Price/Sales"),
    _m("ev_ebitda", "value", "lower", (6.0, 20.0), 0.15, "EV/EBITDA"),
    _m("fcf_yield", "value", "higher", (0.0, 0.08), 0.15, "FCF yield"),
    _m("earnings_yield", "value", "higher", (0.0, 0.10), 0.15, "Earnings yield"),
    # ---------------- Growth (§13)
    _m("revenue_growth_1y", "growth", "higher", (-0.05, 0.25), 0.20, "Revenue growth (1y)"),
    _m("revenue_cagr_3y", "growth", "higher", (-0.02, 0.20), 0.20, "Revenue CAGR (3y)"),
    _m("eps_growth_1y", "growth", "higher", (-0.10, 0.25), 0.20, "EPS growth (1y)"),
    _m("fcf_growth_1y", "growth", "higher", (-0.10, 0.25), 0.15, "FCF growth (1y)"),
    _m("op_income_growth_1y", "growth", "higher", (-0.10, 0.25), 0.15, "Operating income growth (1y)"),
    _m("margin_expansion", "growth", "higher", (-0.02, 0.03), 0.10, "Operating margin change (1y)"),
    # ---------------- Quality (§15-17)
    _m("roe", "quality", "higher", (0.0, 0.25), 0.15, "ROE"),
    _m("roic", "quality", "higher", (0.0, 0.20), 0.20, "ROIC"),
    _m("gross_margin", "quality", "higher", (0.10, 0.60), 0.10, "Gross margin"),
    _m("operating_margin", "quality", "higher", (0.02, 0.30), 0.15, "Operating margin"),
    _m("net_margin", "quality", "higher", (0.01, 0.25), 0.10, "Net margin"),
    _m("fcf_margin", "quality", "higher", (0.0, 0.15), 0.10, "FCF margin"),
    _m("debt_to_equity", "quality", "lower", (0.25, 2.0), 0.10, "Debt/Equity"),
    _m("interest_coverage", "quality", "higher", (3.0, 20.0), 0.05, "Interest coverage"),
    _m("earnings_consistency", "quality", "higher", (0.5, 1.0), 0.05, "Positive-earnings years (5y)"),
    # ---------------- Momentum (§18-19)
    _m("momentum_1m", "momentum", "higher", (-0.10, 0.10), 0.10, "1M price return"),
    _m("momentum_3m", "momentum", "higher", (-0.15, 0.20), 0.15, "3M price return"),
    _m("momentum_6m", "momentum", "higher", (-0.20, 0.30), 0.20, "6M price return"),
    _m("momentum_12m", "momentum", "higher", (-0.25, 0.35), 0.20, "12M price return"),
    _m("momentum_consistency", "momentum", "higher", (0.40, 0.75), 0.15, "Positive months (12m)"),
    _m("rel_strength_12m", "momentum", "higher", (-0.15, 0.20), 0.20, "12M return vs benchmark"),
    # ---------------- Risk (§20): higher score = favorable risk
    _m("annual_volatility", "risk", "lower", (0.15, 0.60), 0.30, "Annualized volatility"),
    _m("beta_deviation", "risk", "lower", (0.0, 0.80), 0.15, "|Beta - 1|"),
    _m("max_drawdown_mag", "risk", "lower", (0.10, 0.55), 0.25, "Max drawdown (magnitude)"),
    _m("sharpe", "risk", "higher", (-0.50, 1.50), 0.20, "Sharpe ratio (1y)"),
    _m("downside_deviation", "risk", "lower", (0.10, 0.45), 0.10, "Downside deviation"),
]

METRICS_BY_NAME: dict[str, MetricDef] = {m.name: m for m in METRIC_DEFS}
FACTORS = ["value", "growth", "quality", "momentum", "risk"]


# --------------------------------------------------------------- scoring
def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def score_absolute(metric: MetricDef, value: float | None) -> float:
    """Piecewise-linear map of value onto 0-100 using band anchors.

    band[0] is the worst anchor, band[1] the best, regardless of direction.
    Values are clamped into the band (documented alternative to winsorization).
    """
    if value is None or not math.isfinite(value):
        return float("nan")
    worst, best = metric.band
    if metric.direction == "lower":
        value = _clamp(value, min(worst, best), max(worst, best))
        frac = (best - value) / (best - worst)
    else:
        value = _clamp(value, min(worst, best), max(worst, best))
        frac = (value - worst) / (best - worst)
    return float(_clamp(frac, 0.0, 1.0) * 100.0)


def score_percentile(values: pd.Series, metric: MetricDef) -> pd.Series:
    """Cross-sectional percentile score (METHODOLOGY §12) with winsorization
    at the 2.5/97.5 percentiles; direction-aware; NaN preserved as NaN."""
    v = values.astype(float).copy()
    finite = v.replace([np.inf, -np.inf], np.nan).dropna()
    if len(finite) < 5:
        return pd.Series(np.nan, index=v.index)
    lo, hi = finite.quantile(0.025), finite.quantile(0.975)
    v = v.clip(lo, hi)
    pct = v.rank(pct=True, na_option="keep")
    if metric.direction == "lower":
        pct = 1.0 - pct
    return pct * 100.0


def _factor_score(scores: dict[str, float], factor: str) -> tuple[float, float]:
    """Weighted mean of available metric scores for one factor.

    Returns (score, coverage) where coverage = available weight / total weight.
    """
    total_w = sum(m.weight for m in METRIC_DEFS if m.factor == factor)
    got_w, acc = 0.0, 0.0
    for m in METRIC_DEFS:
        if m.factor != factor:
            continue
        s = scores.get(m.name, float("nan"))
        if math.isfinite(s):
            acc += s * m.weight
            got_w += m.weight
    if total_w == 0 or got_w == 0:
        return float("nan"), 0.0
    return acc / got_w, got_w / total_w


MIN_FACTOR_COVERAGE = 0.5


@dataclass
class FactorResult:
    ticker: str
    as_of: str
    factor_scores: dict[str, float] = field(default_factory=dict)
    quant_score: float = float("nan")
    metric_scores: dict[str, float] = field(default_factory=dict)
    raw_inputs: dict[str, float | None] = field(default_factory=dict)
    coverage: dict[str, float] = field(default_factory=dict)   # per factor
    overall_coverage: float = 0.0
    missing: list[str] = field(default_factory=list)           # metrics w/ reason
    mode: str = "absolute"

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "as_of": self.as_of,
            "factor_scores": self.factor_scores,
            "quant_score": self.quant_score,
            "metric_scores": self.metric_scores,
            "raw_inputs": self.raw_inputs,
            "coverage": self.coverage,
            "overall_coverage": self.overall_coverage,
            "missing": self.missing,
            "mode": self.mode,
            "weights": FACTOR_WEIGHTS,
        }


def compute_factor_scores(raw: dict[str, float | None], ticker: str = "",
                          as_of: str = "") -> FactorResult:
    """Score one security in absolute mode from raw metric values.

    `raw` maps metric names to values (NaN/None = missing with reason).
    Missing metrics are skipped and weight-renormalized inside their factor;
    factors below 50% metric coverage are excluded from the composite.
    """
    metric_scores: dict[str, float] = {}
    raw_inputs: dict[str, float | None] = {}
    missing: list[str] = []
    for m in METRIC_DEFS:
        v = raw.get(m.name)
        raw_inputs[m.name] = v if (v is not None and math.isfinite(v)) else None
        s = score_absolute(m, v)
        if math.isfinite(s):
            metric_scores[m.name] = s
        else:
            missing.append(m.name)

    factor_scores: dict[str, float] = {}
    coverage: dict[str, float] = {}
    for f in FACTORS:
        s, cov = _factor_score(metric_scores, f)
        coverage[f] = round(cov, 3)
        if cov >= MIN_FACTOR_COVERAGE:
            factor_scores[f] = s

    # Composite QS = 0.20V + 0.20G + 0.25Q + 0.20M + 0.15R over available
    # factors with their weights renormalized (METHODOLOGY §21, §55).
    num, den = 0.0, 0.0
    for f, w in FACTOR_WEIGHTS.items():
        if f in factor_scores and math.isfinite(factor_scores[f]):
            num += w * factor_scores[f]
            den += w
    qs = num / den if den > 0 else float("nan")
    overall_cov = den  # fraction of composite weight that had data

    return FactorResult(
        ticker=ticker,
        as_of=as_of,
        factor_scores={k: round(v, 1) for k, v in factor_scores.items()},
        quant_score=round(qs, 1) if math.isfinite(qs) else float("nan"),
        metric_scores={k: round(v, 1) for k, v in metric_scores.items()},
        raw_inputs=raw_inputs,
        coverage=coverage,
        overall_coverage=round(overall_cov, 3),
        missing=missing,
        mode="absolute",
    )


def score_universe(df: pd.DataFrame) -> pd.DataFrame:
    """Percentile-normalized scoring across a comparison universe.

    `df` rows = securities (indexed by ticker), columns = metric names.
    Returns a frame with per-metric percentile scores, factor scores
    (renormalized for missing metrics), coverage, and composite quant_score.
    """
    out = pd.DataFrame(index=df.index)
    for m in METRIC_DEFS:
        if m.name in df.columns:
            out[m.name] = score_percentile(df[m.name], m)
        else:
            out[m.name] = np.nan

    for f in FACTORS:
        cols = [m.name for m in METRIC_DEFS if m.factor == f]
        present = [c for c in cols if c in out.columns]
        if not present:
            out[f"_score_{f}"] = np.nan
            out[f"_cov_{f}"] = 0.0
            continue
        w = np.array([m.weight for m in METRIC_DEFS if m.name in present])
        sub = out[present].to_numpy(dtype=float)
        mask = np.isfinite(sub)
        wsum = np.where(mask, w, 0.0).sum(axis=1)
        num = np.nansum(np.where(mask, sub * w, np.nan), axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            score = np.where(wsum > 0, num / np.where(wsum == 0, 1, wsum), np.nan)
            cov = wsum / sum(m.weight for m in METRIC_DEFS if m.factor == f)
        out[f"_score_{f}"] = np.where(wsum > 0, score, np.nan)
        out[f"_cov_{f}"] = cov

    factor_cols = [f"_score_{f}" for f in FACTORS]
    fw = np.array([FACTOR_WEIGHTS[f] for f in FACTORS])
    fsub = out[factor_cols].to_numpy(dtype=float)
    fmask = np.isfinite(fsub)
    fnum = np.nansum(np.where(fmask, fsub * fw, np.nan), axis=1)
    fden = np.where(fmask, fw, 0.0).sum(axis=1)
    out["quant_score"] = np.where(fden > 0, fnum / np.where(fden == 0, 1, fden),
                                  np.nan)
    out["overall_coverage"] = fden
    return out


def quant_score_interpretation(score: float) -> str:
    """METHODOLOGY §22 descriptive bands (not trade instructions)."""
    if score is None or not math.isfinite(score):
        return "Insufficient data"
    bands = [(90, "Exceptional"), (80, "Strong"), (70, "Favorable"),
             (60, "Neutral/Favorable"), (50, "Neutral"), (40, "Weak"),
             (30, "Very Weak"), (0, "Poor")]
    for lo, label in bands:
        if score >= lo:
            return label
    return "Poor"
