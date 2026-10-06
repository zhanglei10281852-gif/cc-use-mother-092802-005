"""项目组合视图：协同收益、冲突项与尚待核实的数据。"""

from __future__ import annotations

from .evaluation import ACTIVE_STATUSES, Report, compute_totals
from .review import ReviewBoard
from .snapshot import Snapshot
from .util import to_canonical


def portfolio_view(
    report: Report, snapshot: Snapshot, board: ReviewBoard, dedupe: bool
) -> dict:
    rejected = board.rejected_keys(report.report_id)
    effective = [i for i in report.indicators if i.key not in rejected]
    active = [i for i in effective if i.status in ACTIVE_STATUSES]

    # 协同收益：同一措施在污染与温室气体两个域都有指标
    by_measure: dict[str, list] = {}
    for ind in effective:
        by_measure.setdefault(ind.measure_id, []).append(ind)
    synergies = []
    for mid, inds in sorted(by_measure.items()):
        domains = {i.domain for i in inds}
        if domains >= {"pollution", "ghg"}:
            synergies.append(
                {
                    "measure_id": mid,
                    "pollution": {
                        i.metric: str(i.value)
                        for i in inds
                        if i.domain == "pollution" and i.value is not None
                    },
                    "ghg_tco2e": next(
                        (
                            str(i.value)
                            for i in inds
                            if i.domain == "ghg" and i.value is not None
                        ),
                        None,
                    ),
                    "pending_metrics": [
                        i.metric for i in inds if i.status not in ACTIVE_STATUSES
                    ],
                    "note": "同一工程同时产生污染削减与温室气体减排（协同收益）",
                }
            )

    # 尚待核实：未核实来源的证据
    src_by_evidence: dict[str, list] = {}
    for s in snapshot.sources:
        for eid in s.evidence_ids:
            src_by_evidence.setdefault(eid, []).append(s)
    unverified = []
    seen_ev: set[str] = set()
    for ind in active:
        for eid in ind.evidence_ids:
            if eid in seen_ev:
                continue
            seen_ev.add(eid)
            for s in src_by_evidence.get(eid, []):
                if not s.verified:
                    unverified.append(
                        {
                            "evidence_id": eid,
                            "source_id": s.source_id,
                            "origin": s.origin,
                            "used_by": ind.key,
                        }
                    )

    pending = {
        "待补数据": [
            {"indicator": i.key, "notes": list(i.notes)}
            for i in effective
            if i.status == "pending_data"
        ],
        "依赖阻塞": [
            {"indicator": i.key, "notes": list(i.notes)}
            for i in effective
            if i.status == "blocked"
        ],
        "未核实证据": unverified,
        "退回待整改": [
            {"indicator": d.indicator_key, "reason": d.reason, "reviewer": d.reviewer}
            for d in board.decisions_for(report.report_id)
            if d.decision == "rejected"
        ],
    }

    return {
        "report_id": report.report_id,
        "ruleset_version": report.ruleset_version,
        "boundary": report.boundary_name,
        "totals": {k: str(v) for k, v in sorted(report.totals.items())},
        "gross_totals": {k: str(v) for k, v in sorted(report.gross_totals.items())},
        "adjusted_totals_after_review": {
            k: str(v)
            for k, v in sorted(compute_totals(effective, dedupe).items())
        },
        "synergies": synergies,
        "conflicts": [to_canonical(c) for c in report.conflicts],
        "pending": pending,
    }
