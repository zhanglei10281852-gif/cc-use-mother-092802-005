"""数据快照：冻结某一时刻的全部登记数据，保证历史报告可按原口径复算。"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import MeasureEvidence
from .domain import Baseline, EvidenceSource, Measure, MonitoringRecord
from .util import stable_hash


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    measures: tuple[Measure, ...]
    evidence: tuple[MeasureEvidence, ...]
    sources: tuple[EvidenceSource, ...]
    monitoring: tuple[MonitoringRecord, ...]
    baselines: tuple[Baseline, ...]


def freeze(
    measures: tuple[Measure, ...],
    evidence: tuple[MeasureEvidence, ...],
    sources: tuple[EvidenceSource, ...],
    monitoring: tuple[MonitoringRecord, ...],
    baselines: tuple[Baseline, ...],
) -> Snapshot:
    payload = {
        "measures": sorted(measures, key=lambda m: m.measure_id),
        "evidence": sorted(evidence, key=lambda e: (e.evidence_id, e.measure_id, e.metric)),
        "sources": sorted(sources, key=lambda s: s.source_id),
        "monitoring": sorted(
            monitoring, key=lambda r: (r.reach_id, r.pollutant, r.month.isoformat())
        ),
        "baselines": sorted(baselines, key=lambda b: (b.metric, b.reach_id, b.revision)),
    }
    sid = stable_hash(payload)
    return Snapshot(
        sid,
        tuple(payload["measures"]),
        tuple(payload["evidence"]),
        tuple(payload["sources"]),
        tuple(payload["monitoring"]),
        tuple(payload["baselines"]),
    )
