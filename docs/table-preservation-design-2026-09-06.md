# 技术表格 preservation / 绑定修复裁决（2026-09-06）

本设计基于 `table-preservation-classification-2026-09-06.*` 的只读归类。当前真实产物不能证明所有失败项属于模型丢值：SBD 旧包有 41 项缺少唯一条款/块身份，ABNT 的 3 项来自重复的 Security 条款号。因此先补证据身份，再决定是否改变守恒基线。

## 结论

1. **近期采用候选 4：强化“行事实归入 data_constraints”的提示与回归诊断。** 这保持一个功能目标对应一个需求条目的产品形态，不重新引入原子化工作台；不做确定性回填，避免把表头序号、示例值或上下文数字误写成需求约束。
2. **对输入侧乱序表采用候选 3 的专家定点闭环。** 只有在物理 cell/row 证据能唯一定位时，才通过现有 claim 队列定点重抽；证据不足的条目继续显示“待核”，不自动降级或放行。
3. **候选 1（每行独立 FRE）暂不采用。** 它会改变功能产品粒度并重新制造原子化的行数膨胀，除非新真值集证明候选 4/3 无法达到目标。
4. **候选 2（零 LLM 行展开）只保留为受限实验。** 仅可用于已通过参数表结构判定、且每行拥有稳定 cell 身份的行；不得覆盖普通叙述表或无表头表。

## 实施顺序

### 1. 先补可审计身份（零付费）

preservation finding 必须携带 `section_block_ids`，并保留 `section_path` 与 `section_id`。同名条款号因此可以按物理块区分，任务 D 分类器可在证据充分时继续判定 a/b/c，否则仍为 `manual_review`。这是诊断字段扩展，不改变 blocking 条件。

### 2. 提示强化与回归

在 functional extract 的两套系统提示中明确：参数行的“字段名 + 值 + 单位 + 适用条件”应逐字进入所属需求的 `data_constraints`；表头/示例/上下文数字只有在条款把它们定义为约束时才进入。新增真实夹具回归要求检查 `data_constraints` 与 source quote 的受保护 token 集合，而不是只检查 objective。

### 3. 专家闭环

对任务 D 标为输入侧或身份不足的条目，优先生成待核清单；专家确认后复用现有 targeted reextract/claim queue。重抽必须满足同一 clause family、目标块不越界、未受影响 FRE 字节稳定且守恒重新通过，才原子替换产品。

### 4. 重新跑门禁

候选 4/3 完成后，用同一真值集和模板重跑 A/B；报告同时记录 conservation model、table structure、outline 与 routing 版本。只有 preservation、binding 与 14 项真值阈值全部有证据通过，才讨论 `RATOMIZER_EXECUTION_POLICY` 默认翻转。

## 明确不做

- 不把所有 preservation 数字自动塞回需求字段。
- 不把重复文本统一降为 warning；该语义需要单独的审核裁定。
- 不删除 atomize/A-track 后端代码；旧结果包、CLI 与回滚路径仍需可读。
