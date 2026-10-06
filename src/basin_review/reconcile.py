"""报告间差异归因：不同统计边界或不同口径的结果必须能解释差异来自何处。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .evaluation import Report


@dataclass(frozen=True)
class IndicatorDiff:
    key: str
    measure_id: str
    metric: str
    value_a: Decimal | None
    value_b: Decimal | None
    reasons: tuple[str, ...]


def diff_reports(
    a: Report,
    b: Report,
    label_a: str = "A",
    label_b: str = "B",
    absent_reason_a: str | None = None,
    absent_reason_b: str | None = None,
) -> tuple[IndicatorDiff, ...]:
    """逐项对比两份报告的指标，依据指标携带的溯源信息给出差异来源。

    absent_reason_a/b：指标只存在于一方时的解释（如"河段不在该统计边界内"）。
    """
    ia = {i.key: i for i in a.indicators}
    ib = {i.key: i for i in b.indicators}
    diffs: list[IndicatorDiff] = []
    for key in sorted(set(ia) | set(ib)):
        x, y = ia.get(key), ib.get(key)
        if x is not None and y is not None:
            same = (
                x.value == y.value
                and x.status == y.status
                and x.boundary_weight == y.boundary_weight
                and x.factor_used == y.factor_used
                and x.baseline_revision == y.baseline_revision
                and x.evidence_ids == y.evidence_ids
            )
            if same:
                continue
            reasons: list[str] = []
            if x.boundary_weight != y.boundary_weight:
                reasons.append(f"统计边界权重 {x.boundary_weight} → {y.boundary_weight}")
            if x.factor_used != y.factor_used:
                reasons.append(f"排放因子 {x.factor_used} → {y.factor_used}")
            if x.baseline_revision != y.baseline_revision:
                reasons.append(f"基准版本 {x.baseline_revision} → {y.baseline_revision}")
            if x.status != y.status:
                reasons.append(f"指标状态 {x.status} → {y.status}")
            if set(x.evidence_ids) != set(y.evidence_ids):
                reasons.append("引用证据集合变化")
            if not reasons:
                reasons.append("数值变化")
            diffs.append(
                IndicatorDiff(key, x.measure_id, x.metric, x.value, y.value, tuple(reasons))
            )
        elif x is not None:
            reason = absent_reason_b or f"仅存在于「{label_a}」口径"
            diffs.append(IndicatorDiff(key, x.measure_id, x.metric, x.value, None, (reason,)))
        else:
            assert y is not None
            reason = absent_reason_a or f"仅存在于「{label_b}」口径"
            diffs.append(IndicatorDiff(key, y.measure_id, y.metric, None, y.value, (reason,)))
    return tuple(diffs)
