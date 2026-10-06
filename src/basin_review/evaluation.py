"""评估引擎：在冻结快照 × 规则版本 × 统计边界下生成不可变报告。

引擎是纯函数式的：相同输入必然得到相同报告，因此历史报告可按原口径复算。
报告不携带时间戳，report_id 由 (快照, 规则版本, 边界) 派生。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping

from .contracts import MeasureEvidence
from .dependencies import structural_violations, topological_order
from .domain import Boundary, Measure
from .rules import RuleSet
from .snapshot import Snapshot
from .util import month_range, stable_hash

POLLUTION_PREFIX = "pollution:"
ENERGY_PREFIX = "energy:"
GHG_METRIC = "ghg:co2e"

ACTIVE_STATUSES = ("computed", "estimated")


@dataclass(frozen=True)
class Contribution:
    """一条证据对指标值的贡献（用于跨措施去重与重复计入识别）。"""

    evidence_id: str
    value: Decimal


@dataclass(frozen=True)
class IndicatorResult:
    key: str  # f"{measure_id}:{metric}"
    measure_id: str
    metric: str
    domain: str  # pollution | ghg
    value: Decimal | None  # 挂起/阻塞时为 None
    unit: str
    status: str  # computed | estimated | pending_data | blocked
    reach_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    contributions: tuple[Contribution, ...]
    baseline_revision: str
    factor_used: Decimal | None
    boundary_weight: Decimal
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Conflict:
    kind: str  # duplicate_evidence | dependency_missing | dependency_order | dependency_cycle
    detail: str
    measure_ids: tuple[str, ...]
    evidence_id: str | None = None
    amount_at_risk: Decimal | None = None


@dataclass(frozen=True)
class Report:
    report_id: str
    snapshot_id: str
    ruleset_version: str
    boundary_name: str
    indicators: tuple[IndicatorResult, ...]
    conflicts: tuple[Conflict, ...]
    totals: Mapping[str, Decimal]  # 去重后合计
    gross_totals: Mapping[str, Decimal]  # 未去重合计（展示重复计入的规模）


def compute_totals(
    indicators: Iterable[IndicatorResult], dedupe: bool
) -> dict[str, Decimal]:
    """合计有效指标；dedupe 时同一证据只计一次（按计算顺序先到先得）。"""
    indicators = list(indicators)
    totals: dict[str, Decimal] = {i.metric: Decimal(0) for i in indicators}
    seen: set[str] = set()
    for ind in indicators:
        if ind.status not in ACTIVE_STATUSES or ind.value is None:
            continue
        if not dedupe:
            totals[ind.metric] += ind.value
            continue
        add = Decimal(0)
        for c in ind.contributions:
            if c.evidence_id not in seen:
                seen.add(c.evidence_id)
                add += c.value
        totals[ind.metric] += add
    return totals


class Engine:
    def evaluate(
        self, snapshot: Snapshot, ruleset: RuleSet, boundary: Boundary
    ) -> Report:
        measures = {m.measure_id: m for m in snapshot.measures}
        all_measures = tuple(measures.values())
        order, cycles = topological_order(all_measures)
        violations = structural_violations(all_measures)

        conflicts: list[Conflict] = [
            Conflict(v.kind, v.detail, (v.measure_id, v.dependency_id))
            for v in violations
        ]
        for cycle in cycles:
            conflicts.append(
                Conflict(
                    "dependency_cycle",
                    f"措施依赖成环：{', '.join(cycle)}",
                    tuple(cycle),
                )
            )

        blocked_reasons: dict[str, list[str]] = {}
        for v in violations:
            blocked_reasons.setdefault(v.measure_id, []).append(v.detail)
        for cycle in cycles:
            for mid in cycle:
                blocked_reasons.setdefault(mid, []).append("依赖成环，无法确定计算先后")

        # 跨措施重复引用同一证据（分别报表时同一收益被重复计入的典型来源）
        evidence = sorted(
            snapshot.evidence, key=lambda e: (e.evidence_id, e.measure_id)
        )
        by_evidence: dict[str, list[MeasureEvidence]] = {}
        for ev in evidence:
            by_evidence.setdefault(ev.evidence_id, []).append(ev)
        for eid, evs in by_evidence.items():
            citing = sorted({e.measure_id for e in evs})
            if len(citing) < 2:
                continue
            unit_value = self._evidence_value(evs[0], ruleset)
            risk = unit_value * (len(citing) - 1) if unit_value is not None else None
            conflicts.append(
                Conflict(
                    "duplicate_evidence",
                    f"证据 {eid} 被措施 {', '.join(citing)} 重复引用，存在重复计入风险",
                    tuple(citing),
                    eid,
                    risk,
                )
            )

        indicators: list[IndicatorResult] = []
        sequence = list(order) + [mid for c in cycles for mid in c]
        for mid in sequence:
            m = measures[mid]
            weight = boundary.weight_for(m.reach_ids)
            if weight == 0:
                continue  # 不在统计边界内
            block_notes = tuple(blocked_reasons.get(mid, ()))
            for pollutant in sorted(m.pollutants):
                metric = POLLUTION_PREFIX + pollutant
                evs = [
                    e for e in evidence if e.measure_id == mid and e.metric == metric
                ]
                if evs:
                    indicators.append(
                        self._pollution(
                            m, metric, evs, snapshot, ruleset, boundary, weight,
                            block_notes,
                        )
                    )
            if m.energy_activities:
                evs = [
                    e
                    for e in evidence
                    if e.measure_id == mid and e.metric.startswith(ENERGY_PREFIX)
                ]
                if evs:
                    indicators.append(self._ghg(m, evs, ruleset, weight, block_notes))

        report_id = stable_hash(
            {
                "snapshot": snapshot.snapshot_id,
                "ruleset": ruleset.version,
                "boundary": boundary.name,
            }
        )
        return Report(
            report_id,
            snapshot.snapshot_id,
            ruleset.version,
            boundary.name,
            tuple(indicators),
            tuple(conflicts),
            compute_totals(indicators, ruleset.dedupe_shared_evidence),
            compute_totals(indicators, False),
        )

    # ---- 内部 ----

    def _evidence_value(
        self, ev: MeasureEvidence, ruleset: RuleSet
    ) -> Decimal | None:
        if ev.metric.startswith(POLLUTION_PREFIX):
            return ev.amount
        if ev.metric.startswith(ENERGY_PREFIX):
            kind = ev.metric.split(":", 1)[1]
            factor = ruleset.emission_factors.get(kind)
            return ev.amount * factor if factor is not None else None
        return None

    def _pollution(
        self,
        m: Measure,
        metric: str,
        evs: list[MeasureEvidence],
        snapshot: Snapshot,
        ruleset: RuleSet,
        boundary: Boundary,
        weight: Decimal,
        block_notes: tuple[str, ...],
    ) -> IndicatorResult:
        notes: list[str] = list(block_notes)
        status = "computed"
        has_baseline = any(
            b.metric == metric
            and b.revision == ruleset.baseline_revision
            and b.reach_id in m.reach_ids
            for b in snapshot.baselines
        )
        if not has_baseline:
            status = "pending_data"
            notes.append(f"缺少基准版本「{ruleset.baseline_revision}」下 {metric} 的基准值")
        gaps = self._monitoring_gaps(snapshot, m, metric, boundary)
        if gaps:
            desc = "；".join(f"{reach} 缺 {','.join(months)}" for reach, months in gaps)
            notes.append(f"监测缺期：{desc}")
            status = "estimated" if ruleset.gap_policy == "interpolate" else "pending_data"
        if block_notes:
            status = "blocked"
        contributions = tuple(
            Contribution(e.evidence_id, e.amount * weight) for e in evs
        )
        value = (
            sum((c.value for c in contributions), Decimal(0))
            if status in ACTIVE_STATUSES
            else None
        )
        return IndicatorResult(
            key=f"{m.measure_id}:{metric}",
            measure_id=m.measure_id,
            metric=metric,
            domain="pollution",
            value=value,
            unit=evs[0].unit,
            status=status,
            reach_ids=m.reach_ids,
            evidence_ids=tuple(sorted(e.evidence_id for e in evs)),
            contributions=contributions,
            baseline_revision=ruleset.baseline_revision,
            factor_used=None,
            boundary_weight=weight,
            notes=tuple(notes),
        )

    def _ghg(
        self,
        m: Measure,
        evs: list[MeasureEvidence],
        ruleset: RuleSet,
        weight: Decimal,
        block_notes: tuple[str, ...],
    ) -> IndicatorResult:
        notes: list[str] = list(block_notes)
        contributions: list[Contribution] = []
        factors: set[Decimal] = set()
        missing_factor = False
        for e in evs:
            kind = e.metric.split(":", 1)[1]
            factor = ruleset.emission_factors.get(kind)
            if factor is None:
                missing_factor = True
                notes.append(f"缺少能源活动「{kind}」的排放因子")
                continue
            factors.add(factor)
            contributions.append(Contribution(e.evidence_id, e.amount * factor * weight))
        status = "pending_data" if missing_factor else "computed"
        if block_notes:
            status = "blocked"
        value = (
            sum((c.value for c in contributions), Decimal(0))
            if status in ACTIVE_STATUSES
            else None
        )
        return IndicatorResult(
            key=f"{m.measure_id}:{GHG_METRIC}",
            measure_id=m.measure_id,
            metric=GHG_METRIC,
            domain="ghg",
            value=value,
            unit="tCO2e",
            status=status,
            reach_ids=m.reach_ids,
            evidence_ids=tuple(sorted(e.evidence_id for e in evs)),
            contributions=tuple(contributions),
            baseline_revision=ruleset.baseline_revision,
            factor_used=next(iter(factors)) if len(factors) == 1 else None,
            boundary_weight=weight,
            notes=tuple(notes),
        )

    def _monitoring_gaps(
        self, snapshot: Snapshot, measure: Measure, metric: str, boundary: Boundary
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        pollutant = metric.split(":", 1)[1]
        recorded = {(r.reach_id, r.pollutant, r.month) for r in snapshot.monitoring}
        gaps: list[tuple[str, tuple[str, ...]]] = []
        for reach_id in measure.reach_ids:
            if boundary.reach_weights.get(reach_id, Decimal(0)) == 0:
                continue
            missing = tuple(
                mo.isoformat()[:7]
                for mo in month_range(measure.window.starts_on, measure.window.ends_on)
                if (reach_id, pollutant, mo) not in recorded
            )
            if missing:
                gaps.append((reach_id, missing))
        return tuple(gaps)
