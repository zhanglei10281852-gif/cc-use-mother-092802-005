"""计算版本之间的差异归因。

比较两个 CalculationRun（可能来自不同统计边界、规则版本、
基准版本或监测快照），把总量差异分解到具体措施与指标，
并依据 provenance 指出差异来源：

- ``boundary_scope``    边界组成不同（措施/河段只在一侧）
- ``rule_change``       规则版本或排放因子变化
- ``baseline_change``   基准线版本变化（如排污许可调整）
- ``monitoring_change`` 监测数据快照变化（如补齐缺期）
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import INDICATOR_GHG, INDICATOR_POLLUTION, CalculationRun, IndicatorResult

CAUSE_LABELS = {
    "boundary_scope": "边界组成",
    "rule_change": "规则版本",
    "baseline_change": "基准线调整",
    "monitoring_change": "监测数据",
    "unknown": "未识别",
}


@dataclass(frozen=True)
class DifferenceComponent:
    measure_id: str
    indicator: str
    subject: str
    amount_a: Decimal | None
    amount_b: Decimal | None
    delta: Decimal | None  # b - a
    causes: tuple[str, ...]
    detail: str


@dataclass(frozen=True)
class DifferenceReport:
    run_a: str
    run_b: str
    components: tuple[DifferenceComponent, ...]
    totals_a: dict[str, Decimal]
    totals_b: dict[str, Decimal]
    summary: tuple[str, ...]


def _totals(results) -> dict[str, Decimal]:
    totals = {
        INDICATOR_POLLUTION: Decimal("0"),
        INDICATOR_GHG: Decimal("0"),
    }
    for r in results:
        if r.value is not None:
            totals[r.indicator] += r.value
    return totals


def _baseline_versions(result: IndicatorResult) -> dict:
    return {
        reach: info.get("baseline_version")
        for reach, info in result.provenance.get("reach_breakdown", {}).items()
    }


def _causes(a: IndicatorResult, b: IndicatorResult) -> tuple[str, ...]:
    causes: list[str] = []
    pa, pb = a.provenance, b.provenance
    # 污染削减在当前模型中不依赖规则版本的排放因子，规则修订只归因到温室气体指标
    if a.indicator == INDICATOR_GHG and (
        pa.get("rule_version") != pb.get("rule_version")
        or pa.get("factor") != pb.get("factor")
    ):
        causes.append("rule_change")
    if _baseline_versions(a) != _baseline_versions(b):
        causes.append("baseline_change")
    if set(pa.get("reach_breakdown", {})) != set(pb.get("reach_breakdown", {})):
        causes.append("boundary_scope")
    if pa.get("data_seq") != pb.get("data_seq") and a.indicator == INDICATOR_POLLUTION:
        causes.append("monitoring_change")
    return tuple(causes) or ("unknown",)


def explain_difference(run_a: CalculationRun, run_b: CalculationRun) -> DifferenceReport:
    key = lambda r: (r.measure_id, r.indicator, r.subject)  # noqa: E731
    index_a = {key(r): r for r in run_a.results}
    index_b = {key(r): r for r in run_b.results}

    components: list[DifferenceComponent] = []
    for k in sorted(set(index_a) | set(index_b)):
        a, b = index_a.get(k), index_b.get(k)
        measure_id, indicator, subject = k
        if a is None:
            components.append(
                DifferenceComponent(
                    measure_id, indicator, subject, None, b.value, b.value,
                    ("boundary_scope",),
                    f"仅出现在 {run_b.boundary_id} 边界口径（{run_b.id}）",
                )
            )
        elif b is None:
            neg = -a.value if a.value is not None else None
            components.append(
                DifferenceComponent(
                    measure_id, indicator, subject, a.value, None, neg,
                    ("boundary_scope",),
                    f"仅出现在 {run_a.boundary_id} 边界口径（{run_a.id}）",
                )
            )
        elif a.value != b.value or a.status != b.status:
            delta = (
                (b.value - a.value)
                if a.value is not None and b.value is not None
                else None
            )
            causes = _causes(a, b)
            components.append(
                DifferenceComponent(
                    measure_id, indicator, subject, a.value, b.value, delta,
                    causes,
                    "；".join(CAUSE_LABELS[c] for c in causes),
                )
            )

    totals_a, totals_b = _totals(run_a.results), _totals(run_b.results)

    by_cause: dict[str, Decimal] = {}
    for comp in components:
        if comp.delta is None:
            continue
        for cause in comp.causes:
            by_cause[cause] = by_cause.get(cause, Decimal("0")) + comp.delta
    summary = tuple(
        f"{CAUSE_LABELS.get(c, c)}差异合计 {amt}（涉及 "
        f"{sum(1 for comp in components if c in comp.causes)} 项指标）"
        for c, amt in sorted(by_cause.items())
    )

    return DifferenceReport(
        run_a=run_a.id,
        run_b=run_b.id,
        components=tuple(components),
        totals_a=totals_a,
        totals_b=totals_b,
        summary=summary,
    )
