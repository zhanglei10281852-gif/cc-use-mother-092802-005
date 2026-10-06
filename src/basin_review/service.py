"""评估后端服务接口。

流程：登记 → 冻结快照 → 按规则版本与统计边界评估 → 评审 →
组合视图 / 边界对账 / 原口径复算。
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import MeasureEvidence
from .domain import (
    Baseline,
    Boundary,
    EvidenceSource,
    Measure,
    MonitoringRecord,
    Reach,
)
from .evaluation import Engine, Report
from .portfolio import portfolio_view
from .reconcile import IndicatorDiff, diff_reports
from .review import ReviewBoard, ReviewDecision
from .rules import RuleSet
from .snapshot import Snapshot, freeze
from .util import canonical_json


@dataclass(frozen=True)
class ReplayCheck:
    report_id: str
    matches: bool
    detail: str


class BasinReviewService:
    def __init__(self) -> None:
        self._reaches: dict[str, Reach] = {}
        self._measures: dict[str, Measure] = {}
        self._evidence: list[MeasureEvidence] = []
        self._sources: dict[str, EvidenceSource] = {}
        self._monitoring: list[MonitoringRecord] = []
        self._baselines: list[Baseline] = []
        self._rulesets: dict[str, RuleSet] = {}
        self._boundaries: dict[str, Boundary] = {}
        self._snapshots: dict[str, Snapshot] = {}
        self._reports: dict[str, Report] = {}
        self.review_board = ReviewBoard()
        self._engine = Engine()

    # ---- 登记 ----

    def register_reach(self, reach: Reach) -> None:
        self._reaches[reach.reach_id] = reach

    def register_measure(self, measure: Measure) -> None:
        self._measures[measure.measure_id] = measure

    def register_evidence(self, evidence: MeasureEvidence) -> None:
        self._evidence.append(evidence)

    def register_source(self, source: EvidenceSource) -> None:
        self._sources[source.source_id] = source

    def register_monitoring(self, record: MonitoringRecord) -> None:
        self._monitoring.append(record)

    def register_baseline(self, baseline: Baseline) -> None:
        self._baselines.append(baseline)

    def verify_source(self, source_id: str) -> None:
        src = self._sources[source_id]
        self._sources[source_id] = EvidenceSource(
            src.source_id, src.origin, src.evidence_ids, True
        )

    def publish_ruleset(self, ruleset: RuleSet) -> None:
        if ruleset.version in self._rulesets:
            raise ValueError(
                f"规则版本 {ruleset.version} 已存在：规则修订必须发布新版本，不得覆盖"
            )
        self._rulesets[ruleset.version] = ruleset

    def define_boundary(self, boundary: Boundary) -> None:
        if boundary.name in self._boundaries:
            raise ValueError(f"统计边界 {boundary.name} 已存在")
        self._boundaries[boundary.name] = boundary

    # ---- 快照与评估 ----

    def take_snapshot(self) -> str:
        snap = freeze(
            tuple(self._measures.values()),
            tuple(self._evidence),
            tuple(self._sources.values()),
            tuple(self._monitoring),
            tuple(self._baselines),
        )
        self._snapshots[snap.snapshot_id] = snap
        return snap.snapshot_id

    def run_evaluation(
        self, ruleset_version: str, boundary_name: str, snapshot_id: str | None = None
    ) -> Report:
        sid = snapshot_id or self.take_snapshot()
        report = self._engine.evaluate(
            self._snapshots[sid], self._rulesets[ruleset_version],
            self._boundaries[boundary_name],
        )
        self._reports[report.report_id] = report
        return report

    # ---- 评审 ----

    def review_indicator(
        self,
        report_id: str,
        indicator_key: str,
        decision: str,
        reason: str,
        reviewer: str,
    ) -> None:
        report = self._reports[report_id]
        if indicator_key not in {i.key for i in report.indicators}:
            raise ValueError(f"报告 {report_id} 中不存在指标 {indicator_key}")
        if decision not in ("approved", "rejected"):
            raise ValueError("decision 必须是 approved 或 rejected")
        self.review_board.record(
            ReviewDecision(report_id, indicator_key, decision, reason, reviewer)
        )

    # ---- 查询 ----

    def portfolio(self, report_id: str) -> dict:
        """项目组合视图：协同收益、冲突项与尚待核实的数据。"""
        report = self._reports[report_id]
        snap = self._snapshots[report.snapshot_id]
        ruleset = self._rulesets[report.ruleset_version]
        return portfolio_view(report, snap, self.review_board, ruleset.dedupe_shared_evidence)

    def reconcile(
        self,
        ruleset_version: str,
        boundary_a: str,
        boundary_b: str,
        snapshot_id: str | None = None,
    ) -> tuple[IndicatorDiff, ...]:
        """同一口径、同一数据在两种统计边界下的结果对账，逐项解释差异。"""
        sid = snapshot_id or self.take_snapshot()
        ra = self.run_evaluation(ruleset_version, boundary_a, sid)
        rb = self.run_evaluation(ruleset_version, boundary_b, sid)
        return diff_reports(
            ra,
            rb,
            boundary_a,
            boundary_b,
            absent_reason_a=f"河段不在「{boundary_a}」统计边界内（权重为 0）",
            absent_reason_b=f"河段不在「{boundary_b}」统计边界内（权重为 0）",
        )

    def explain(
        self, report_id_a: str, report_id_b: str
    ) -> tuple[IndicatorDiff, ...]:
        """任意两份报告之间的差异归因。"""
        ra, rb = self._reports[report_id_a], self._reports[report_id_b]
        return diff_reports(
            ra,
            rb,
            f"{ra.ruleset_version}/{ra.boundary_name}",
            f"{rb.ruleset_version}/{rb.boundary_name}",
        )

    def replay(self, report_id: str) -> ReplayCheck:
        """按原口径复算历史报告：冻结快照 + 原规则版本 + 原统计边界。"""
        report = self._reports[report_id]
        fresh = self._engine.evaluate(
            self._snapshots[report.snapshot_id],
            self._rulesets[report.ruleset_version],
            self._boundaries[report.boundary_name],
        )
        matches = canonical_json(fresh) == canonical_json(report)
        return ReplayCheck(
            report_id,
            matches,
            "复算结果与历史报告一致" if matches else "复算结果与历史报告不一致",
        )
