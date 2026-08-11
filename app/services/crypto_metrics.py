"""Metric shaping for the crypto performance chart.

The endpoint builds one dollar-value series; this module turns it into the
series each metric tab actually promises:

- ``value-over-time``: the dollar series unchanged.
- ``return-rate``: percent change vs the first point of the window.
- ``risk-exposure``: the crypto sleeve as a percent of total portfolio value
  at the same snapshot (denominators supplied by the caller).
"""
from decimal import Decimal
from typing import Dict, List, Optional, Sequence


def metric_series(
    points: List[Dict],
    metric: str,
    exposure_denoms: Optional[Sequence[Decimal]] = None,
) -> List[Dict]:
    if metric == "return-rate":
        first = points[0]["value"] if points else 0.0
        out = []
        for point in points:
            if first:
                pct = (point["value"] / first - 1.0) * 100.0
            else:
                pct = 0.0
            out.append({**point, "value": round(pct, 4)})
        return out

    if metric == "risk-exposure" and exposure_denoms is not None:
        out = []
        for point, denom in zip(points, exposure_denoms):
            denom_f = float(denom)
            pct = (point["value"] / denom_f * 100.0) if denom_f else 0.0
            out.append({**point, "value": round(pct, 4)})
        return out

    # value-over-time and anything unrecognized: the dollar series.
    return points
