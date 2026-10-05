"""跨措施冲突检测。

识别两类典型问题：
1. ``duplicate_evidence`` —— 独占性证据（电费单、计量读数等）被多个措施
   用于同一指标且期间重叠，典型的"能源替代收益重复计入"即属此类；
2. ``overlap_unallocated`` —— 两个措施在同一河段考核同一污染物、基准期间
   重叠，却未声明先后依赖，削减量可能重复计算。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Optional

from .models import Evidence, Measure, MonthSpan


@dataclass(frozen=True)
class Conflict:
    kind: str
    summary: str
    measure_ids: tuple[str, ...]
    evidence_id: str = ""
    subject: str = ""
    span: Optional[MonthSpan] = None
    severity: str = "high"
    suggestion: str = ""


def _depends_transitively(measures: dict[str, Measure], start: str, target: str) -> bool:
    stack, seen = [start], set()
    while stack:
        mid = stack.pop()
        if mid == target:
            return True
        if mid in seen or mid not in measures:
            continue
        seen.add(mid)
        stack.extend(measures[mid].depends_on)
    return False


def _common_span(spans: list[MonthSpan]) -> Optional[MonthSpan]:
    common = spans[0]
    for s in spans[1:]:
        common = common.intersection(s) if common else None
        if common is None:
            return None
    return common


def detect_conflicts(
    measures: dict[str, Measure], evidence_by_id: dict[str, Evidence]
) -> list[Conflict]:
    conflicts: list[Conflict] = []

    # 1) 独占性证据被多个措施引用（能源活动 + 措施级污染物证据）
    energy_usage: dict[tuple[str, str], list[tuple[str, MonthSpan]]] = {}
    for m in measures.values():
        for act in m.energy_activities:
            if act.evidence_id:
                energy_usage.setdefault((act.evidence_id, act.kind), []).append(
                    (m.id, act.span)
                )
    for (evidence_id, kind), users in sorted(energy_usage.items()):
        measure_ids = sorted({mid for mid, _ in users})
        if len(measure_ids) < 2:
            continue
        evidence = evidence_by_id.get(evidence_id)
        if evidence is not None and not evidence.exclusive:
            continue
        span = _common_span([s for _, s in users])
        if span is None:
            continue
        conflicts.append(
            Conflict(
                kind="duplicate_evidence",
                summary=(
                    f"证据 {evidence_id} 被措施 {'、'.join(measure_ids)} "
                    f"重复用于能源活动 {kind}，收益可能重复计入"
                ),
                measure_ids=tuple(measure_ids),
                evidence_id=evidence_id,
                subject=kind,
                span=span,
                suggestion="为各措施约定证据分摊比例，或仅保留一个措施的引用",
            )
        )

    pollution_usage: dict[tuple[str, str], list[str]] = {}
    for m in measures.values():
        for evidence_id in m.evidence_ids:
            for pollutant in m.pollutants:
                pollution_usage.setdefault((evidence_id, pollutant), []).append(m.id)
    for (evidence_id, pollutant), mids in sorted(pollution_usage.items()):
        measure_ids = sorted(set(mids))
        if len(measure_ids) < 2:
            continue
        evidence = evidence_by_id.get(evidence_id)
        if evidence is not None and not evidence.exclusive:
            continue
        conflicts.append(
            Conflict(
                kind="duplicate_evidence",
                summary=(
                    f"证据 {evidence_id} 被措施 {'、'.join(measure_ids)} "
                    f"重复用于污染物 {pollutant}，削减量可能重复计入"
                ),
                measure_ids=tuple(measure_ids),
                evidence_id=evidence_id,
                subject=pollutant,
                suggestion="共享监测报告应标记为非独占，否则需拆分证据口径",
            )
        )

    # 2) 同河段同污染物重叠但未声明依赖
    for m1, m2 in combinations(sorted(measures.values(), key=lambda m: m.id), 2):
        shared_reaches = sorted(set(m1.reach_ids) & set(m2.reach_ids))
        shared_pollutants = sorted(set(m1.pollutants) & set(m2.pollutants))
        if not shared_reaches or not shared_pollutants:
            continue
        if not m1.baseline_span.overlaps(m2.baseline_span):
            continue
        sequential = _depends_transitively(measures, m1.id, m2.id) or _depends_transitively(
            measures, m2.id, m1.id
        )
        if sequential:
            continue
        conflicts.append(
            Conflict(
                kind="overlap_unallocated",
                summary=(
                    f"措施 {m1.id} 与 {m2.id} 在河段 {'、'.join(shared_reaches)} "
                    f"上同时考核 {'、'.join(shared_pollutants)}，"
                    "但未声明先后依赖，削减量归属不明"
                ),
                measure_ids=(m1.id, m2.id),
                subject=",".join(shared_pollutants),
                severity="medium",
                suggestion="声明 depends_on 先后关系，或为两措施约定削减量分摊",
            )
        )

    return conflicts
