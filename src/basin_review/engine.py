"""计算引擎：把措施、基准线、监测记录与规则版本编成不可变的计算版本。

要点：
- 措施按 ``depends_on`` 拓扑排序后依次计算，循环依赖直接报错；
- 监测缺期不阻断计算，结果标记为 ``estimated`` 并列出缺期月份，
  完全无观测的标记为 ``no_data``；
- 每个结果携带 provenance（规则版本、基准版本、数据快照序号、
  排放因子、分河段明细），支撑差异归因与原口径复算。
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Iterable, Optional

from .models import (
    INDICATOR_GHG,
    INDICATOR_POLLUTION,
    STATUS_ESTIMATED,
    STATUS_NO_DATA,
    STATUS_OK,
    CalculationRun,
    IndicatorResult,
    Measure,
    MonthSpan,
    RuleSet,
    StatisticalBoundary,
)
from .store import Ledger


class MissingBaselineError(ValueError):
    """某河段+污染物在数据快照时点没有可用基准线。"""


class UnknownActivityKindError(ValueError):
    """规则版本中缺少某能源活动类型的排放因子。"""


class DependencyError(ValueError):
    """措施依赖缺失或存在循环。"""


def topo_sort(measures: dict[str, Measure]) -> list[Measure]:
    """按依赖关系拓扑排序；依赖缺失或成环时抛出 :class:`DependencyError`。"""
    for m in measures.values():
        missing = [d for d in m.depends_on if d not in measures]
        if missing:
            raise DependencyError(
                f"措施 {m.id} 依赖未登记的措施: {', '.join(sorted(missing))}"
            )

    indegree = {mid: 0 for mid in measures}
    dependents: dict[str, list[str]] = defaultdict(list)
    for m in measures.values():
        for dep in m.depends_on:
            indegree[m.id] += 1
            dependents[dep].append(m.id)

    ready = sorted(mid for mid, deg in indegree.items() if deg == 0)
    ordered: list[Measure] = []
    while ready:
        mid = ready.pop(0)
        ordered.append(measures[mid])
        for nxt in sorted(dependents[mid]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
        ready.sort()

    if len(ordered) != len(measures):
        cycle = sorted(mid for mid, deg in indegree.items() if deg > 0)
        raise DependencyError(f"措施依赖存在循环: {', '.join(cycle)}")
    return ordered


def _pollution_result(
    run_id: str,
    measure: Measure,
    pollutant: str,
    reaches: Iterable[str],
    window: MonthSpan,
    ledger: Ledger,
    ruleset: RuleSet,
    data_seq: int,
) -> IndicatorResult:
    months = window.months()
    breakdown: dict[str, dict] = {}
    expected_total = Decimal("0")
    actual_total = Decimal("0")
    gap_months: list[str] = []
    observed_any = False

    for reach_id in reaches:
        baseline = ledger.baseline_as_of(reach_id, pollutant, data_seq)
        if baseline is None:
            raise MissingBaselineError(
                f"河段 {reach_id} 污染物 {pollutant} 在快照 {data_seq} 时点无基准线"
            )
        records = ledger.monitoring_as_of(reach_id, pollutant, window, data_seq)
        monthly: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for r in records:
            monthly[r.month] += r.load
        gaps = [m for m in months if m not in monthly]
        observed = len(months) - len(gaps)
        observed_any = observed_any or observed > 0

        expected = baseline.monthly_load * observed
        actual = sum(monthly.values(), Decimal("0"))
        expected_total += expected
        actual_total += actual
        gap_months.extend(gaps)
        breakdown[reach_id] = {
            "baseline_version": baseline.version,
            "baseline_permit": baseline.permit_ref,
            "baseline_monthly_load": str(baseline.monthly_load),
            "observed_months": observed,
            "expected_load": str(expected),
            "actual_load": str(actual),
        }

    if not observed_any:
        status, value = STATUS_NO_DATA, None
    else:
        status = STATUS_ESTIMATED if gap_months else STATUS_OK
        value = expected_total - actual_total

    return IndicatorResult(
        run_id=run_id,
        measure_id=measure.id,
        indicator=INDICATOR_POLLUTION,
        subject=pollutant,
        span=window,
        value=value,
        unit="t",
        status=status,
        gap_months=tuple(sorted(gap_months)),
        evidence_ids=tuple(measure.evidence_ids),
        provenance={
            "rule_version": ruleset.version,
            "data_seq": data_seq,
            "reach_breakdown": breakdown,
        },
    )


def _ghg_result(
    run_id: str,
    measure: Measure,
    activity,
    window: MonthSpan,
    ruleset: RuleSet,
    data_seq: int,
) -> IndicatorResult:
    factor = ruleset.emission_factors.get(activity.kind)
    if factor is None:
        raise UnknownActivityKindError(
            f"规则版本 {ruleset.version} 缺少能源活动类型 {activity.kind!r} 的排放因子"
        )
    evidence_ids = (activity.evidence_id,) if activity.evidence_id else ()
    return IndicatorResult(
        run_id=run_id,
        measure_id=measure.id,
        indicator=INDICATOR_GHG,
        subject=activity.kind,
        span=activity.span,
        value=activity.amount * factor,
        unit="tCO2e",
        status=STATUS_OK,
        evidence_ids=evidence_ids,
        provenance={
            "rule_version": ruleset.version,
            "data_seq": data_seq,
            "factor": str(factor),
            "activity_amount": str(activity.amount),
            "activity_unit": activity.unit,
        },
    )


def compute_run(
    ledger: Ledger,
    ruleset: RuleSet,
    measures: dict[str, Measure],
    boundary: StatisticalBoundary,
    window: MonthSpan,
    run_id: str,
    data_seq: Optional[int] = None,
    recompute_of: str = "",
) -> CalculationRun:
    """生成一个不可变的计算版本。

    ``data_seq`` 缺省取台账当前序号；传入历史序号即按当时口径复算。
    """
    if data_seq is None:
        data_seq = ledger.current_seq

    ordered = topo_sort(measures)
    results: list[IndicatorResult] = []
    warnings: list[str] = []
    included: list[str] = []

    for measure in ordered:
        reaches = [r for r in measure.reach_ids if r in boundary.reach_ids]
        if not reaches:
            continue
        included.append(measure.id)
        for dep in measure.depends_on:
            if dep not in included and dep in measures:
                warnings.append(
                    f"措施 {measure.id} 依赖的 {dep} 不在边界 {boundary.id} 的计算范围内"
                )
        for pollutant in measure.pollutants:
            results.append(
                _pollution_result(
                    run_id, measure, pollutant, reaches, window, ledger, ruleset, data_seq
                )
            )
        for activity in measure.energy_activities:
            results.append(
                _ghg_result(run_id, measure, activity, window, ruleset, data_seq)
            )

    return CalculationRun(
        id=run_id,
        rule_version=ruleset.version,
        boundary_id=boundary.id,
        window=window,
        data_seq=data_seq,
        measure_ids=tuple(included),
        results=tuple(results),
        warnings=tuple(warnings),
        recompute_of=recompute_of,
    )
