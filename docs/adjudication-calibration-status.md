# 裁决阈值校准现状（A-2，2026-08-07）

> 本文记录 WS-B 自动裁决阈值校准的**当前实现现状**与一项**显式延后**的设计承诺，
> 用以关闭"声明空壳"——代码与文档对同一件事说法一致。

## 现状：单层校准（single-stratum）

`adjudicate.calibration_state` 对**整份真值集**计算单一指标：

- `precision` / `recall`：真值条目与产物（`functional_requirements.json`）的整体匹配。
- `far = 1 - precision`：误受率，**单一标量**。
- `status`：`pending_annotation`（真值集空 → 自动通过硬禁用）/ `insufficient`
  （far ≥ threshold）/ `calibrated`（far < threshold）。

KB 命中**不进入校准门槛**：`adjudicate._kb_hit_for_item` 只在 `adjudicate_item` 的
"不熟但忠实（unfamiliar_but_faithful）"分流里作**加分项**，让客户特殊内容不因"不熟"被
自动拒绝；它不参与 FAR 计算，也不产生按 KB 命中拆分的阈值。

`CalibrationState` dataclass 因此**不含任何分层字段**（无 `strata` / `kb_hit_far` /
`kb_miss_far` / `by_stratum`），由 `tests/test_adjudicate.py::TestCalibrationStratumHonesty`
钉死。

## 显式延后：KB 命中/未命中分层校准

V4 设计（《需求分析 agent 演进方案 v4》）曾设想：

> 阈值按 KB 命中/未命中分层校准（招标类真值文档提供 non-KB 标定样本），防止熟悉度成分
> 系统性歧视特殊需求。

该分层**当前不实现，显式延后**，理由：

1. **依赖真实真值标注**：分层门槛要求真值集在 KB 命中层与未命中层各有足够样本可标定。
   真值集标注是纯人工硬阻塞（评审报告行动清单 #5），当前为空/pending。
2. **FAR 可达性未验证**：评审报告 #3 指出 `far = 1 - precision` 对微型真值集系统性偏高，
   真值标注后须实测能否 `< 2%`，否则自动通过门永远不开。分层 FAR 同样依赖该可达性。
3. **不建无法验证的机制**：在空真值集上构建分层校准，其门级可观测行为与单层完全一致
   （pending 即硬禁用），只是更精致的空壳——违背"宁漏勿错 / stub 诚实"纪律。

**何时重启**：当真值集完成标注、且报告 #3 的 FAR 可达性在真实数据上验证通过后，再按真实
的 KB 命中/未命中样本分布设计分层（层划分规则、空层处置、各层 threshold），并同步更新
`CalibrationState`、本文档与 `TestCalibrationStratumHonesty`。

无论分层与否：**真值 pending 时 `pending_annotation` 硬禁用自动通过**的语义不变。
