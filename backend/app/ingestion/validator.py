"""Data validation (PROJECT_SPEC.md §10, §37; METHODOLOGY.md §55).

Validation NEVER repairs data silently. Findings are collected and surfaced;
metrics that cannot be trusted are dropped (kept as NULL), not zero-filled.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date

from ..errors import ValidationError

LOGGER = logging.getLogger(__name__)


@dataclass
class Finding:
    severity: str   # error | warning | info
    field: str
    message: str


@dataclass
class ValidationResult:
    ok: bool = True
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: str, field_: str, message: str) -> None:
        self.findings.append(Finding(severity, field_, message))
        if severity == "error":
            self.ok = False

    def summary(self) -> str:
        errs = sum(1 for f in self.findings if f.severity == "error")
        warns = sum(1 for f in self.findings if f.severity == "warning")
        return f"{'PASS' if self.ok else 'FAIL'} ({errs} errors, {warns} warnings)"


def check_price_series(bars: list) -> ValidationResult:
    """Validate normalized daily bars for a ticker."""
    res = ValidationResult()
    if not bars:
        res.add("error", "prices", "no price data available")
        return res
    seen: dict = {}
    for b in bars:
        if b.date.year < 1970 or b.date > date.today():
            LOGGER.warning("price bar has suspicious date: %s", b.date)
            res.add("error", "date", f"invalid date {b.date}")
        key = b.date
        if key in seen:
            res.add("warning", "duplicate", f"duplicate date {b.date}")
        seen[key] = True
        for name in ("open", "high", "low", "close", "adj_close"):
            v = getattr(b, name)
            if v is not None:
                if math.isnan(v) or math.isinf(v):
                    res.add("error", name, f"non-finite {name} on {b.date}")
                elif v < 0:
                    res.add("error", name, f"negative {name} on {b.date}")
        hi, lo = b.high, b.low
        if hi is not None and lo is not None and hi < lo:
            res.add("error", "high_low", f"high < low on {b.date}")
    return res


def check_statement(st, currency: str | None = None) -> ValidationResult:
    """Sanity-check a normalized statement. Negative equity is flagged, not
    silently scored."""
    res = ValidationResult()
    items = st.items
    if st.fiscal_date.year < 1970:
        res.add("error", "fiscal_date", f"implausible fiscal date {st.fiscal_date}")
    if currency and st.currency and currency != st.currency:
        res.add("warning", "currency",
                f"statement currency {st.currency} != profile currency {currency}")
    eq = items.get("total_equity")
    if eq is not None and eq <= 0:
        res.add("warning", "total_equity",
                f"non-positive equity on {st.fiscal_date}: flagged for factor engines")
    rev = items.get("revenue")
    if rev is not None and rev < 0:
        res.add("error", "revenue", f"negative revenue on {st.fiscal_date}")
    return res


def validate_ticker(ticker: str) -> str:
    """Normalize ticker syntax; raise ValidationError on garbage input."""
    t = (ticker or "").strip().upper()
    if not t or len(t) > 6 or not t.replace(".", "").replace("-", "").isalnum():
        raise ValidationError(f"invalid ticker format: {ticker!r}")
    return t
