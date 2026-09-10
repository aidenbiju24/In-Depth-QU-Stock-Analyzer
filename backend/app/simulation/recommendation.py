"""Recommendation engine (METHODOLOGY.md §53-56).

Deterministic, rule-based. NO machine learning, NO LLM, NO opaque confidence
scores. Every recommendation is fully traceable: the output records which
rules fired and which inputs produced them.

Framework:
  1. Start from the composite Quant Score (0-100) with documented bands.
  2. Apply documented modifiers: DCF upside band, momentum confirmation,
     earnings quality, risk veto for extreme drawdown/volatility.
  3. Map the final points to the 5-level scale:
     Strong Buy / Buy / Hold / Sell / Strong Sell.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

REC_MODEL_VERSION = "1.0"


@dataclass
class RecommendationInput:
    quant_score: float | None          # 0-100 composite
    dcf_upside: float | None           # (fair - price)/price
    momentum_12m: float | None         # trailing 12M return
    earnings_beat_rate: float | None   # 0-1 fraction
    annual_volatility: float | None    # annualized
    max_drawdown: float | None         # positive magnitude fraction
    regime: str | None = None          # informational only


@dataclass
class Recommendation:
    ticker: str
    action: str                        # Strong Buy .. Strong Sell
    score: float                       # internal points (documented)
    rules_fired: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    version: str = REC_MODEL_VERSION
    disclaimer: str = ("Rule-based output from documented quantitative inputs; "
                       "not investment advice.")

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker, "action": self.action,
            "score": round(self.score, 1), "rules_fired": self.rules_fired,
            "reasoning": self.reasoning, "version": self.version,
            "disclaimer": self.disclaimer,
        }


# Documented bands (METHODOLOGY §53).
QS_BASE = [
    (80, 40), (70, 30), (60, 20), (50, 10), (40, 0), (30, -10), (0, -20),
]
UPSIDE_STRONG = 0.30
UPSIDE_BUY = 0.15
DOWNSIDE_SELL = -0.15
DOWNSIDE_STRONG = -0.30
MOMENTUM_CONFIRM = 0.05
MOMENTUM_NEGATIVE = -0.10
BEAT_RATE_GOOD = 0.70
BEAT_RATE_BAD = 0.40
VOL_VETO = 0.60          # annualized vol above this => cap at Hold
DD_VETO = 0.55           # max drawdown magnitude above this => cap at Hold

SCALE = ["Strong Sell", "Sell", "Hold", "Buy", "Strong Buy"]


def _action_from_points(points: float) -> str:
    if points >= 32:
        return "Strong Buy"
    if points >= 18:
        return "Buy"
    if points >= -12:
        return "Hold"
    if points >= -26:
        return "Sell"
    return "Strong Sell"


def recommend(ticker: str, inputs: RecommendationInput) -> Recommendation:
    rules: list[str] = []
    reasoning: list[str] = []
    points = 0.0

    # 1) Quant score base points.
    qs = inputs.quant_score
    if qs is None or not math.isfinite(qs):
        return Recommendation(
            ticker=ticker, action="Hold", score=0.0,
            rules_fired=["insufficient_data"],
            reasoning=["Quant score unavailable — recommendation suppressed to HOLD."],
        )
    for lo, pts in QS_BASE:
        if qs >= lo:
            points += pts
            rules.append(f"quant_score>={lo}")
            reasoning.append(f"Quant score {qs:.0f} -> base {pts:+d} points")
            break

    # 2) DCF upside modifier.
    up = inputs.dcf_upside
    if up is not None and math.isfinite(up):
        if up >= UPSIDE_STRONG:
            points += 15
            rules.append("dcf_upside>=30%")
            reasoning.append(f"DCF upside {up:+.0%} -> +15 points")
        elif up >= UPSIDE_BUY:
            points += 8
            rules.append("dcf_upside>=15%")
            reasoning.append(f"DCF upside {up:+.0%} -> +8 points")
        elif up <= DOWNSIDE_STRONG:
            points -= 15
            rules.append("dcf_upside<=-30%")
            reasoning.append(f"DCF downside {up:+.0%} -> -15 points")
        elif up <= DOWNSIDE_SELL:
            points -= 8
            rules.append("dcf_upside<=-15%")
            reasoning.append(f"DCF downside {up:+.0%} -> -8 points")

    # 3) Momentum confirmation.
    mom = inputs.momentum_12m
    if mom is not None and math.isfinite(mom):
        if mom >= MOMENTUM_CONFIRM:
            points += 5
            rules.append("momentum_12m>=+5%")
            reasoning.append(f"12M momentum {mom:+.0%} -> +5 points")
        elif mom <= MOMENTUM_NEGATIVE:
            points -= 5
            rules.append("momentum_12m<=-10%")
            reasoning.append(f"12M momentum {mom:+.0%} -> -5 points")

    # 4) Earnings beat rate.
    br = inputs.earnings_beat_rate
    if br is not None and math.isfinite(br):
        if br >= BEAT_RATE_GOOD:
            points += 5
            rules.append("beat_rate>=0.70")
            reasoning.append(f"Earnings beat rate {br:.0%} -> +5 points")
        elif br <= BEAT_RATE_BAD:
            points -= 5
            rules.append("beat_rate<=0.40")
            reasoning.append(f"Earnings beat rate {br:.0%} -> -5 points")

    # 5) Risk vetoes: extreme volatility or drawdown caps the action.
    vol = inputs.annual_volatility
    dd = inputs.max_drawdown
    cap = None
    if vol is not None and math.isfinite(vol) and vol >= VOL_VETO:
        cap = "Hold"
        rules.append("risk_veto_volatility")
        reasoning.append(
            f"Annualized volatility {vol:.0%} >= {VOL_VETO:.0%} — action capped at Hold")
    if dd is not None and math.isfinite(dd) and dd >= DD_VETO:
        cap = "Hold"
        rules.append("risk_veto_drawdown")
        reasoning.append(
            f"Max drawdown {dd:.0%} >= {DD_VETO:.0%} — action capped at Hold")

    action = _action_from_points(points)
    if cap == "Hold":
        order = {a: i for i, a in enumerate(SCALE)}
        if order[action] > order["Hold"]:
            action = "Hold"

    if inputs.regime:
        reasoning.append(f"Market regime: {inputs.regime} (context only, no modifier)")

    return Recommendation(ticker=ticker, action=action, score=points,
                          rules_fired=rules, reasoning=reasoning)
