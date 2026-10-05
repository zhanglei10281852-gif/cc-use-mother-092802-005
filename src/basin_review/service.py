"""评估后端门面：登记、计算、评审与项目组合视图。

组合接口：
- :meth:`BasinService.portfolio_synergy`   协同收益（共益措施、依赖链、去重合计）
- :meth:`BasinService.portfolio_conflicts` 冲突项（重复引用证据、未声明依赖的重叠）
- :meth:`BasinService.portfolio_pending`   尚待核实的数据（未核实证据、监测缺期、被退回指标）
- :meth:`BasinService.recompute`           按原口径复算历史计算版本
- :meth:`BasinService.compare_boundaries`  不同统计边界的结果对比与差异归因
"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Optional

from .conflicts import Conflict, detect_conflicts
from .engine import compute_run
from .explain import DifferenceReport, explain_difference
from .models import (
    EVIDENCE_VERIFIED,
    INDICATOR_GHG,
    INDICATOR_POLLUTION,
    REVIEW_REJECTED,
    STATUS_ESTIMATED,
    STATUS_NO_DATA,
    Baseline,
    CalculationRun,
    EnergyActivity,
    Evidence,
    Measure,
    MonthSpan,
    MonitoringRecord,
    Reach,
    RuleSet,
    StatisticalBoundary,
)
from .review import ReviewRegistry, dependent_measures
from .store import Ledger


class BasinService:
    def __init__(self) -> None:
        self.ledger = Ledger()
        self.reaches: dict[str, Reach] = {}
        self.boundaries: dict[str, StatisticalBoundary] = {}
        self.rulesets: dict[str, RuleSet] = {}
        self.measures: dict[str, Measure] = {}
        self.runs: dict[str, CalculationRun] = {}
        self.reviews = ReviewRegistry()
        self._run_counter = 0

    # ------------------------------------------------------------------
    # 登记
    # ------------------------------------------------------------------

    def register_reach(self, reach_id: str, name: str) -> Reach:
        reach = Reach(reach_id, name)
        self.reaches[reach_id] = reach
        return reach

    def register_boundary(
        self, boundary_id: str, name: str, reach_ids: list[str]
    ) -> StatisticalBoundary:
        unknown = [r for r in reach_ids if r not in self.reaches]
        if unknown:
            raise ValueError(f"边界引用了未登记的河段: {unknown}")
        boundary = StatisticalBoundary(boundary_id, name, frozenset(reach_ids))
        self.boundaries[boundary_id] = boundary
        return boundary

    def register_ruleset(self, ruleset: RuleSet) -> RuleSet:
        self.rulesets[ruleset.version] = ruleset
        return ruleset

    def register_measure(self, measure: Measure) -> Measure:
        unknown = [r for r in measure.reach_ids if r not in self.reaches]
        if unknown:
            raise ValueError(f"措施 {measure.id} 引用了未登记的河段: {unknown}")
        self.measures[measure.id] = measure
        return measure

    def register_evidence(self, evidence: Evidence) -> Evidence:
        return self.ledger.add_evidence(evidence)

    def add_monitoring(
        self, reach_id: str, pollutant: str, month: str, load, source: str = ""
    ) -> MonitoringRecord:
        """登记（或补齐）监测记录；只增不改，历史口径不受影响。"""
        return self.ledger.add_monitoring(reach_id, pollutant, month, Decimal(str(load)), source)

    def revise_baseline(
        self,
        reach_id: str,
        pollutant: str,
        monthly_load,
        span: MonthSpan,
        version: str,
        permit_ref: str = "",
        note: str = "",
    ) -> Baseline:
        """登记新的基准线版本（如排污许可调整）；旧版本保留。"""
        return self.ledger.add_baseline(
            reach_id, pollutant, Decimal(str(monthly_load)), span, version, permit_ref, note
        )

    # ------------------------------------------------------------------
    # 计算
    # ------------------------------------------------------------------

    def create_run(
        self,
        window: MonthSpan,
        boundary_id: str,
        rule_version: Optional[str] = None,
        data_seq: Optional[int] = None,
        recompute_of: str = "",
    ) -> CalculationRun:
        if rule_version is None:
            rule_version = max(self.rulesets)
        ruleset = self.rulesets[rule_version]
        boundary = self.boundaries[boundary_id]
        self._run_counter += 1
        run = compute_run(
            self.ledger,
            ruleset,
            self.measures,
            boundary,
            window,
            run_id=f"run-{self._run_counter}",
            data_seq=data_seq,
            recompute_of=recompute_of,
        )
        self.runs[run.id] = run
        return run

    def recompute(self, run_id: str) -> dict:
        """按原口径（原规则版本 + 原数据快照 + 原边界）复算历史版本。

        返回 ``matches=True`` 表示补齐监测或调整基准后，历史报告
        仍能逐指标复算出原结果；新版本不覆盖旧版本。
        """
        original = self.runs[run_id]
        rerun = self.create_run(
            window=original.window,
            boundary_id=original.boundary_id,
            rule_version=original.rule_version,
            data_seq=original.data_seq,
            recompute_of=original.id,
        )
        differences = []
        original_by_key = {
            (r.measure_id, r.indicator, r.subject): r for r in original.results
        }
        for r in rerun.results:
            k = (r.measure_id, r.indicator, r.subject)
            o = original_by_key.get(k)
            if o is None or o.value != r.value or o.status != r.status:
                differences.append(
                    {
                        "measure_id": k[0],
                        "indicator": k[1],
                        "subject": k[2],
                        "original": None if o is None else str(o.value),
                        "recomputed": str(r.value),
                    }
                )
        return {
            "original_run": original.id,
            "recomputed_run": rerun.id,
            "rule_version": original.rule_version,
            "data_seq": original.data_seq,
            "matches": not differences,
            "differences": differences,
        }

    def compare_runs(self, run_a_id: str, run_b_id: str) -> DifferenceReport:
        return explain_difference(self.runs[run_a_id], self.runs[run_b_id])

    def compare_boundaries(
        self,
        window: MonthSpan,
        boundary_a: str,
        boundary_b: str,
        rule_version: Optional[str] = None,
    ) -> dict:
        """同一口径下两个统计边界各算一次，并解释差异来源。"""
        run_a = self.create_run(window, boundary_a, rule_version)
        run_b = self.create_run(window, boundary_b, rule_version)
        return {
            "run_a": run_a.id,
            "run_b": run_b.id,
            "difference": explain_difference(run_a, run_b),
        }

    # ------------------------------------------------------------------
    # 评审
    # ------------------------------------------------------------------

    def review(
        self, result_key: str, decision: str, note: str = "", reviewer: str = ""
    ) -> dict:
        """退回或批准单个指标；其他结论不受影响，下游依赖措施仅追加提示。"""
        record = self.reviews.decide(result_key, decision, note, reviewer)
        run_id = result_key.split(":", 1)[0]
        run = self.runs.get(run_id)
        affected: list[str] = []
        if run is not None and decision == REVIEW_REJECTED:
            rejected_measures = {
                k.split(":")[1]
                for k in self.reviews.rejected_keys()
                if k.startswith(f"{run_id}:")
            }
            affected = sorted(dependent_measures(self.measures, rejected_measures))
        return {"decision": asdict(record), "dependent_measures_flagged": affected}

    # ------------------------------------------------------------------
    # 组合视图
    # ------------------------------------------------------------------

    def _valid_results(self, run: CalculationRun):
        rejected = self.reviews.rejected_keys()
        return [
            r
            for r in run.results
            if r.key not in rejected and r.status != STATUS_NO_DATA
        ]

    def portfolio_synergy(self, run_id: str) -> dict:
        """项目组合的协同收益。

        共益措施同时产出污染削减与温室气体减排；合计时对冲突接口
        识别出的重复证据只计一次，扣减额单列。
        """
        run = self.runs[run_id]
        valid = self._valid_results(run)

        # 温室气体结果按 (证据, 活动类型) 去重：同一证据只计一次
        ghg_groups: dict[tuple[str, str], list] = {}
        ghg_kept = []
        for r in valid:
            if r.indicator != INDICATOR_GHG:
                continue
            evidence = r.evidence_ids[0] if r.evidence_ids else ""
            if evidence:
                ghg_groups.setdefault((evidence, r.subject), []).append(r)
            else:
                ghg_kept.append(r)
        deductions = []
        order = {mid: i for i, mid in enumerate(run.measure_ids)}
        for (evidence, subject), group in sorted(ghg_groups.items()):
            measure_ids = {r.measure_id for r in group}
            if len(measure_ids) < 2:
                ghg_kept.extend(group)
                continue
            group.sort(key=lambda r: order.get(r.measure_id, 0))
            kept, dropped = group[0], group[1:]
            ghg_kept.append(kept)
            deductions.append(
                {
                    "evidence_id": evidence,
                    "subject": subject,
                    "kept_measure": kept.measure_id,
                    "dropped_measures": sorted(r.measure_id for r in dropped),
                    "deducted": str(sum((r.value for r in dropped), Decimal("0"))),
                }
            )

        pollution = [r for r in valid if r.indicator == INDICATOR_POLLUTION]
        pollution_by_subject: dict[str, Decimal] = {}
        for r in pollution:
            pollution_by_subject[r.subject] = (
                pollution_by_subject.get(r.subject, Decimal("0")) + r.value
            )
        ghg_raw = sum((r.value for r in valid if r.indicator == INDICATOR_GHG), Decimal("0"))
        ghg_net = sum((r.value for r in ghg_kept), Decimal("0"))

        has_pollution = {r.measure_id for r in pollution}
        has_ghg = {r.measure_id for r in ghg_kept}
        co_benefit = sorted(has_pollution & has_ghg)

        included = set(run.measure_ids)
        chains = sorted(
            (dep, m.id)
            for m in self.measures.values()
            if m.id in included
            for dep in m.depends_on
            if dep in included
        )

        return {
            "run_id": run.id,
            "boundary_id": run.boundary_id,
            "rule_version": run.rule_version,
            "co_benefit_measures": co_benefit,
            "dependency_chains": [{"from": a, "to": b} for a, b in chains],
            "pollution_reduction_by_subject": {
                k: str(v) for k, v in sorted(pollution_by_subject.items())
            },
            "ghg_reduction_raw": str(ghg_raw),
            "ghg_reduction_deduplicated": str(ghg_net),
            "conflict_deductions": deductions,
            "excluded_rejected": sorted(
                k for k in self.reviews.rejected_keys() if k.startswith(f"{run.id}:")
            ),
        }

    def portfolio_conflicts(self) -> list[Conflict]:
        evidence = self.ledger.evidence_as_of(self.ledger.current_seq)
        return detect_conflicts(self.measures, evidence)

    def portfolio_pending(self, run_id: str) -> dict:
        """尚待核实：未核实证据、监测缺期、无数据与被退回的指标。"""
        run = self.runs[run_id]
        evidence = self.ledger.evidence_as_of(self.ledger.current_seq)

        unverified = []
        for r in run.results:
            for ev_id in r.evidence_ids:
                ev = evidence.get(ev_id)
                if ev is not None and ev.status != EVIDENCE_VERIFIED:
                    unverified.append(
                        {
                            "evidence_id": ev_id,
                            "status": ev.status,
                            "measure_id": r.measure_id,
                            "indicator": r.indicator,
                            "subject": r.subject,
                        }
                    )

        gaps = [
            {
                "measure_id": r.measure_id,
                "subject": r.subject,
                "gap_months": list(r.gap_months),
            }
            for r in run.results
            if r.status == STATUS_ESTIMATED
        ]
        no_data = [
            {"measure_id": r.measure_id, "subject": r.subject}
            for r in run.results
            if r.status == STATUS_NO_DATA
        ]
        rejected = [
            {
                "result_key": k,
                "note": (self.reviews.decision_of(k).note if self.reviews.decision_of(k) else ""),
            }
            for k in sorted(self.reviews.rejected_keys())
            if k.startswith(f"{run.id}:")
        ]
        return {
            "run_id": run.id,
            "unverified_evidence": unverified,
            "monitoring_gaps": gaps,
            "no_data": no_data,
            "rejected_awaiting_resubmission": rejected,
        }

    def run_view(self, run_id: str) -> dict:
        """计算版本明细，叠加当前评审状态与依赖提示。"""
        run = self.runs[run_id]
        rejected = self.reviews.rejected_keys()
        rejected_measures = {
            k.split(":")[1] for k in rejected if k.startswith(f"{run.id}:")
        }
        flagged = dependent_measures(self.measures, rejected_measures)
        results = []
        for r in run.results:
            item = asdict(r)
            item["key"] = r.key
            item["review_status"] = self.reviews.status_of(r.key)
            if r.measure_id in flagged and r.key not in rejected:
                item["warning"] = "其依赖的上游措施存在被退回的指标，结论待复核"
            results.append(item)
        return {"run": asdict(run), "results": results}
