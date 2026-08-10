# 批处理优化实施与验收报告

- 日期：2026-08-09
- 分支：`codex/batch-processing-optimization`
- 基线：`origin/main` @ `a207ade`
输入方案：`C:\Users\YYHwudi\Downloads\批处理优化实施方案.md`

## 1. 验收结论

方案中的翻译批处理与复核批处理已实现，并保持默认关闭。自动化回归与真实 GLM 小样均通过，可以进入受控试点；在完成 SBD 50 条人工质量抽评前，不建议把开关改为默认开启。

## 2. 实现范围

### 2.1 翻译批处理

- `RATOMIZER_TRANSLATE_BATCH=0` 保留旧 batch=8 行为；正整数开启优化模式，硬上限 10。
- `RATOMIZER_TRANSLATE_BATCH_MAX_CHARS` 默认 8000；按条数和字符数双上限顺序贪心装包，单条超限不截断、独立发送。
- 批量请求使用 `translation-prompt-v3` 数组契约，要求逐条独立翻译。
- 整批结构非法时最多拆半两层，仍失败再进入原有逐条/句段降级链。
- 缺失、重复、越界 id 均逐条 fail-closed，不污染同批合法结果。
- 每条译文独立检查受保护编码、数字与单位的新增和缺失；漂移结果绝不落为成功译文。
- 缓存仍按内容逐条保存；批大小和字符上限进入策略及阶段指纹；并发失效使用译文 SHA CAS，避免覆盖另一进程写入的新成功译文。

### 2.2 复核批处理

- `RATOMIZER_REVIEW_BATCH=0` 默认关闭；2..20 开启，推荐 15。
- 只批处理 legacy single-shot 路径；默认 `review_pipeline.yaml` 的 tool-loop 始终逐 requirement 执行。
- 批量请求使用 `m2-review-v4-batch`，按原样 `requirement_id` 回填。
- 每条结果仍经过 schema、确定性政策 floor、修订文本受保护 token 漂移、split/merge 批内引用校验。
- 单条非法返回 `needs_expert`/`rule_stub`；整批结构非法最多拆半两层，再回退原有逐条复核。
- 缓存指纹绑定精确批成员集合、模型、prompt、执行器、策略、证据和有效批配置；拆半结果绑定实际成功子批。
- 第一批同步执行，连接失败会在并行 fan-out 前快速中止。

## 3. 自动化验证

| 验证项 | 结果 |
|---|---:|
| 翻译/结果包聚焦测试 | 191 tests OK |
| 复核/tool-loop/schema/config 聚焦测试 | 157 tests OK |
| 后端全量 | 3406 tests OK, skipped=7 |
| 修改 Python 文件编译 | 通过 |
| `git diff --check` | 通过，仅 Windows LF/CRLF 提示 |
| 前端 | 未改动，无需新增前端验证 |

全量命令使用仓库约定的 `python -m unittest discover -s tests`，并配置本机历史样本路径；7 项 skip 为环境/可选依赖类跳过，不宣称零跳过。

## 4. 真实 GLM 小样

模型：`glm-5.2`。密钥仅从本机 Claude Code 配置读入当前子进程的 `RATOMIZER_LLM_API_KEY`，测试结束即移除；未写入本报告、源码或仓库文件。

### 4.1 翻译 A/B

使用 10 条不含客户内容的 DLMS/COSEM 合成技术句，覆盖 OBIS、RS-485、bit/s、V、s、百分比、接口类和结果码。

| 指标 | 逐条基线 | 10 条合批 | 变化 |
|---|---:|---:|---:|
| HTTP 调用 | 10 | 1 | -90.0% |
| 总 tokens | 9083 | 1814 | -80.0% |
| 耗时 | 91.41s | 17.23s | -81.2% |
| 有效回填 | 10/10 | 10/10 | 持平 |
| 严格护栏拒绝 | 0 | 0 | 持平 |

合批译文逐条保留了全部受保护编码、数字和单位。该小样没有主动诱发漂移；漂移、缺 id、重复 id、结构非法、拆半和逐条回退由自动化故障测试覆盖。

### 4.2 复核 15+1

使用 16 条合成原子需求，按 15+1 两批调用，并对返回结果逐条执行生产 schema 与政策处理。

| 指标 | 结果 |
|---|---:|
| HTTP 调用 | 2 |
| 总 tokens | 7883 |
| 耗时 | 59.93s |
| 完成逐条校验 | 16/16 |
| 缺失/重复 id | 0 |
| 拆半或逐条回退 | 0 |
| 非法条目 | 0 |
| 决策分布 | accept 9 / revise 6 / needs_expert 1 |

安全类样本的确定性 policy floor 仍把其中 1 条提升为 `needs_expert`，证明合批没有绕开逐条政策层。默认 tool-loop 未参与该试点，因为其工具证据和逐条 token 预算不可合并；相关禁批契约由自动化测试覆盖。

## 5. 未完成项与上线建议

- 尚未按原方案对 SBD 50 个真实 block 做人工盲评，因此当前结论是“可受控试点”，不是“质量已全量转正”。
- 建议试点配置：翻译 `RATOMIZER_TRANSLATE_BATCH=10`、`RATOMIZER_TRANSLATE_BATCH_MAX_CHARS=8000`；复核只有在明确使用 single-shot 管线时才设 `RATOMIZER_REVIEW_BATCH=15`。
- 真实 SBD 试点应记录调用数、tokens、耗时、护栏拦截、缺失/重复 id、拆半/逐条回退，并由人工对同一 50 条逐条版与合批版做盲评。
- 任何护栏拒绝率、人工错误率或降级率上升，都应保持开关 OFF 并先修复；不得用扩大批量或放宽校验换取吞吐。

## 6. 安全与仓库状态

- 未写入或提交 API key、客户文档、SBD 原文、Blue Book PDF、公司模板或本机评测资产。
- 未修改 `golden_sets/` 与冻结 `out/` 基线。
- 当前改动未提交、未推送、未合入 main，等待用户决定。
