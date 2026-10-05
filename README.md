# 流域协同评估

流域治理项目的污染削减与温室气体减排一体化评估后端。每个治理措施登记
适用河段、污染物、能源活动、基准期间与证据来源；规则修订、基准调整、
监测补齐都生成可比但不互相覆盖的计算版本，历史报告始终可按原口径复算。

## 设计要点

- **措施登记**（`models.Measure`）：适用河段 `reach_ids`、考核污染物
  `pollutants`、能源活动 `energy_activities`、基准期间 `baseline_span`、
  证据来源 `evidence_ids`、先后依赖 `depends_on`。
- **只增不改的台账**（`store.Ledger`）：监测记录、基准线版本、证据版本
  追加时分配单调序号；排污许可调整、监测补齐都是新版本，旧版本保留。
- **不可变计算版本**（`models.CalculationRun`）：每次计算固定
  `rule_version + boundary_id + data_seq`，结果携带 provenance
  （基准版本、排放因子、数据快照、分河段明细）。规则修订后生成新版本，
  旧版本不覆盖。
- **冲突检测**（`conflicts`）：独占性证据（电费单、计量读数）被多个措施
  用于同一指标 → `duplicate_evidence`；同河段同污染物重叠但未声明
  先后依赖 → `overlap_unallocated`。共享监测报告标记 `exclusive=False`
  不误报。
- **监测缺期**（`engine`）：缺期不阻断计算，结果标记 `estimated` 并列出
  缺期月份，按已观测月份折算；完全无观测标记 `no_data`。
- **指标级评审**（`review`）：退回单个指标不改动计算版本，其他结论保持
  有效；下游依赖措施仅追加待复核提示。
- **差异归因**（`explain`）：两个计算版本之间的差异分解到措施与指标，
  并归因于边界组成 / 规则版本 / 基准线调整 / 监测数据。
- **组合视图**（`service`）：协同收益（共益措施、依赖链、重复证据只计
  一次）、冲突项、尚待核实（未核实证据、缺期、被退回指标）。

## 目录结构

```
src/basin_review/
  models.py      领域模型（期间、河段、证据、措施、规则、计算版本、评审）
  store.py       只增不改的版本化台账
  engine.py      计算引擎（依赖拓扑排序、缺期标记、provenance）
  conflicts.py   重复引用证据 / 未声明依赖的重叠检测
  review.py      指标级评审登记簿
  explain.py     版本间差异归因
  service.py     评估后端门面（组合接口）
  api.py         标准库 HTTP JSON 接口
  demo.py        端到端演示情景
tests/           unittest 测试（41 项）
```

## 运行

```bash
# 测试
python3 -m unittest discover -s tests -v

# 编译检查
python3 -m compileall -q src tests

# 端到端演示（年度复盘全情景）
PYTHONPATH=src python3 -m basin_review.demo

# 启动 HTTP 接口（载入演示数据）
PYTHONPATH=src python3 -m basin_review.api --demo --port 8000
```

## HTTP 接口

| 方法与路径 | 说明 |
| --- | --- |
| `POST /api/runs` | 生成计算版本（窗口 + 边界 + 规则版本） |
| `GET /api/runs/{id}` | 计算版本明细（叠加评审状态与依赖提示） |
| `POST /api/runs/{id}/recompute` | 按原口径复算校验，`matches=true` 表示逐指标一致 |
| `GET /api/runs/{a}/diff/{b}` | 版本间差异归因 |
| `GET /api/portfolio/synergy?run_id=` | 组合协同收益（重复证据只计一次） |
| `GET /api/portfolio/conflicts` | 冲突项 |
| `GET /api/portfolio/pending?run_id=` | 尚待核实的数据 |
| `GET /api/portfolio/boundary-diff?...` | 两个统计边界的对比与归因 |
| `POST /api/reviews` | 评审退回/批准单个指标 |
| `POST /api/monitoring` | 登记或补齐监测记录 |
| `POST /api/baselines` | 登记新基准线版本（如许可调整） |

