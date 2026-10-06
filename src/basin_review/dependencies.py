"""措施先后依赖：拓扑排序、环检测与结构校验。"""

from __future__ import annotations

from dataclasses import dataclass

from .domain import Measure


@dataclass(frozen=True)
class DependencyViolation:
    kind: str  # dependency_missing | dependency_order
    measure_id: str
    dependency_id: str
    detail: str


def topological_order(
    measures: tuple[Measure, ...],
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """Kahn 拓扑排序。返回 (可排定的顺序, 环)。未知依赖不参与排序，由校验报告。"""
    ids = {m.measure_id for m in measures}
    deps = {m.measure_id: {d for d in m.depends_on if d in ids} for m in measures}
    indegree = {mid: len(ds) for mid, ds in deps.items()}
    dependents: dict[str, list[str]] = {}
    for mid, ds in deps.items():
        for d in ds:
            dependents.setdefault(d, []).append(mid)
    ready = sorted(mid for mid, deg in indegree.items() if deg == 0)
    order: list[str] = []
    while ready:
        mid = ready.pop(0)
        order.append(mid)
        for nxt in sorted(dependents.get(mid, [])):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
                ready.sort()
    remaining = tuple(sorted(mid for mid, deg in indegree.items() if deg > 0))
    cycles = (remaining,) if remaining else ()
    return tuple(order), cycles


def structural_violations(
    measures: tuple[Measure, ...],
) -> tuple[DependencyViolation, ...]:
    """未知依赖与先后倒置（前置措施尚未完成，后续措施已经开始）。"""
    by_id = {m.measure_id: m for m in measures}
    out: list[DependencyViolation] = []
    for m in sorted(measures, key=lambda x: x.measure_id):
        for dep_id in m.depends_on:
            dep = by_id.get(dep_id)
            if dep is None:
                out.append(
                    DependencyViolation(
                        "dependency_missing",
                        m.measure_id,
                        dep_id,
                        f"措施 {m.measure_id} 依赖未登记的措施 {dep_id}",
                    )
                )
            elif dep.window.ends_on > m.window.starts_on:
                out.append(
                    DependencyViolation(
                        "dependency_order",
                        m.measure_id,
                        dep_id,
                        f"措施 {m.measure_id} 开始于 {m.window.starts_on}，"
                        f"先于前置措施 {dep_id} 完成（{dep.window.ends_on}）",
                    )
                )
    return tuple(out)
