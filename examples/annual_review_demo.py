"""年度复盘演示：组合视图、边界对账与原口径复算。

运行：python examples/annual_review_demo.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parents[1] / "tests"))

from basin_review.util import to_canonical
from scenario import build_service, fill_gap_and_adjust_baseline


def show(title, obj):
    print(f"\n=== {title} ===")
    print(json.dumps(to_canonical(obj), ensure_ascii=False, indent=2))


def main():
    svc = build_service()

    # 1) 年末：冻结数据，按 rules-v1 / 流域边界评估
    sid1 = svc.take_snapshot()
    r1 = svc.run_evaluation("rules-v1", "流域边界", sid1)

    # 2) 评审：退回 M2 重复计入的温室气体指标（其余结论保留）
    svc.review_indicator(r1.report_id, "M2:ghg:co2e", "rejected",
                         "与 M1 重复引用票据 E1，退回核实归属", "评审员甲")
    show("项目组合视图（rules-v1 / 流域边界）", svc.portfolio(r1.report_id))

    # 3) 统计边界对账：流域边界 vs 行政边界
    show("边界对账（流域边界 → 行政边界）",
         svc.reconcile("rules-v1", "流域边界", "行政边界", sid1))

    # 4) 复盘之后：补齐监测、许可调整改变基准、发布新规则
    fill_gap_and_adjust_baseline(svc)
    sid2 = svc.take_snapshot()
    r1b = svc.run_evaluation("rules-v1", "流域边界", sid2)  # 原口径 × 新数据
    r2 = svc.run_evaluation("rules-v2", "流域边界", sid2)   # 新口径 × 新数据

    show("补齐监测后（原口径复算 vs 历史报告）",
         svc.explain(r1.report_id, r1b.report_id))
    show("口径升级（rules-v1 → rules-v2）",
         svc.explain(r1b.report_id, r2.report_id))

    # 5) 历史报告按原口径复算验证
    show("原口径复算验证", svc.replay(r1.report_id))


if __name__ == "__main__":
    main()
