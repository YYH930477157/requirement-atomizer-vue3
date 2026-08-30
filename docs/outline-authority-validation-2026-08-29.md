# 大纲权威 flag 真实语料验证报告（RATOMIZER_OUTLINE_AUTHORITY）——建议 No-Go，暂缓默认翻转

**日期：** 2026-08-29（执行：next-steps-plan-2026-08-29 任务 A 全流程，机器 `E:\Codex` 主检出 HEAD `49a1a66`）
**结论先行：** 五条 Go 判定线过四条；唯一不过的是义务覆盖未收敛（统一口径实质义务未覆盖 18→22，
对同代码基线 6 是明显恶化、归因混合）——按计划 §1.4 第 5 步判定线，**建议 No-Go**：
`RATOMIZER_OUTLINE_AUTHORITY` 默认保持 `0`，缺陷修复后重来。病灶条款 BLK-000240 的修复
本身验证成功（切出 + 义务全覆盖 + FRE 无借位）。

---

## 1. 验证设计与成本账（§5.3 纪律）

| 项 | 值 |
|---|---|
| 对照文档 | SBD 招标 PDF `1780709839_SBD_ZETDC.pdf`（900 块 / 207 chunks / 条款覆盖域 821 块） |
| flag 开运行 | `result-outline-on`（隔离目录，result3 未动一字节） |
| 阶段集 | `run`（本地解析）→ `chain --stages functional-extract,requirements-analysis,clarification-report`（裁掉 full-translation 省 80% 成本） |
| env | `RATOMIZER_OUTLINE_AUTHORITY=1`；策略未设（生效 clause_family）；预算账本未开（与 result3 当时一致）；route=openai_compatible，model=deepseek-v4-flash，温度 0（yaml 默认，与 result3/m0 同） |
| **成本实账** | **241 calls / 输入 494,366 tok（其中缓存命中 235,904）/ 输出 789,120 tok / 合计 1,283,486 tok ≈ ¥7.30**（缓存折扣后 ≈¥6.83）；全程 103 分钟（22:05–23:48）；用户上限 ¥10 内 ✓ |
| 成本偏差说明 | 估算 ¥5-8 的下沿被突破：deepseek-v4-flash 为 reasoning 模型，输出 token 占 62%，且 `max_tokens` 截断自动升级重试放大输出消耗（较 result3 旧 trace 字符折算口径高约 3 倍）——如实记录，非估算方法错误而是口径盲区 |

## 2. 零成本证据链（第 1/2/2.5 步）

- **第 1 步（离线回放，`out/tools/replay_outline2b.py`）**：207→**339** 条款（134 confirmed 吞并全切开 + 2 demoted 并前 + 25 suspect 只审计），BLK-000240「2.3 STATEMENT OF REQUIREMENTS (TECHNICAL)」从病理父条款（错挂"3 Any conflict of interest… / 2.2 Delivery Schedule"）切出为独立条款（块序 `[240,241,242,244,245]`），块守恒 **821=821**（零缺失/零多余/无重复，无 `OutlineAuthorityError`）。
  **勘误：** 计划书 §1.1 写的「207→239（39 demoted + 34 confirmed）」与代码事实不符——实测与 `bef6a86` 提交信息（339/134/2）逐项吻合，合并无问题，计划书数字系笔误。
- **第 2 步（ABNT 对照）**：ABNT docx（结构良好）358→**361**（仅 +3），3 个吞并 heading 全 confirmed 切开，0 demoted/0 toc/0 suspect，守恒 763=763——**重切不过激**，Go 判定线 5 通过。
- **第 2.5 步（归因底账，`out/tools/replay_outline2b_attribution.py`，scratch 副本零写入 result3）**：

| 指标 | result3 记录（08-20 代码） | 当前代码 flag 关 ×旧 388 FRE | flag 开 ×旧 FRE（确定性重放） | **flag 开真实全链（新 LLM 输出）** |
|---|---|---|---|---|
| 条款 / 抽取条款 | 207 / 131 | 207 / 95 | 339 / 179 | 339 / 179 |
| 路由版本 | router v3（76 表格出/402 review） | v6（53 表格出/222 review/22 程序性/83 跨度） | 同左 | 同左 |
| FRE | 388 | 281（过滤后） | 303（过滤后） | **323（新产）** |
| duplicates 组 | 6（FAIL） | **0** | 0 | **0（ok）** |
| obligation 未覆盖 | 39 | **12** | 12 | **43** |
| evidence 失配 | 15 | 7 | 7 | **6** |
| binding 失配 | 50 | 37 | 50 | **30** |
| preservation blocking / warning | 50 / 20 | 50 / 10 | 50 / 10 | **50 / 16** |
| execution_status | partial | — | — | partial（analysis/clarification 被守恒闸拦：evidence=36/obligation=43/preservation=50，强制人工） |

## 3. 关键下钻（第 4 步）

### 3.1 obligation 未覆盖 43 的解剖

- **统一碎片口径重算**（确定性判据：<8 词或以 and/or/that/which/: 结尾 → 碎片类；两边同尺）：

| 腿 | 未覆盖总数 | 碎片类（检测器噪声） | 实质义务类 |
|---|---|---|---|
| result3（08-20 代码，flag 关） | 39 | 21 | **18** |
| 重放（当前代码 flag 关 ×旧 FRE） | 12 | 6 | **6** |
| **flag 开真实全链** | 43 | 21 | **22** |

- 43 条按条款归属：**22 在新切条款 / 21 在老条款**（老条款 21 条与新边界无关，属 LLM 方差；最大单点"8.12 Security Requirements"×11 是老条款）。
- 技术主题**没有整块丢失**（探针核对：EAL 认证 32/35 条 FRE 在、密钥更换 2/3、审计日志 1/2、EXPORT CREDIT 1/2、3G/2G 回退 1/2、MODEMS 热插拔 2/3；唯一归零："20 tokens 记录" 1→0）——是主题内兄弟句粒度漏抽，不是主题性缺失。
- **BLK-000240（2.3 STATEMENT OF REQUIREMENTS）：义务未覆盖 = 0** ✓——本 flag 立项的病灶条款修复验证成功。

### 3.2 FRE 抽样（新切条款 143 条中随机 10 条）

**10/10 引句锚定正确、10/10 无跨条款借位**。质量瑕疵 1 例：「5. CLIMATE CONDITIONS OF THE INSTALLATION」条款的 objective 是标题回声式退化文案（"实现…并满足来源条款"）——LLM 对 heading-only 条款的质量瑕疵，非边界缺陷。

### 3.3 claim 发布维度

本次阶段集未含 claim 队列阶段（省成本裁剪），无 claim 产物可比。代理指标 binding_mismatches 50→30 收敛（flag 不动块、锚定几何以块为基）。完整 claim 对照留作翻转立项时的补充验证项。

## 4. 对照有效性声明（第 4.5 步，强制章节）

- **基线代码版本差（完整跨度）**：result3 实跑于 2026-08-20（routing v3 / tender v2 / conservation v3）；当前 main 为 routing v6（中间 v4 句子锚点、v5 逐标题否决、v6 单元级聚合）/ tender v4 / conservation v5 / guards v6，另有队列收敛第 2/3 步等非路由改动。**直接对比 = 旧代码 flag 关 vs 新代码 flag 开，不是干净 flag 对照**。
- **干净的部分（第 2.5 步底账）**：确定性层（路由计数、守恒基线构成）与守恒指标本身（388 FRE 重算）已把中间版本贡献隔离——duplicates 6→0、obligation 39→12、evidence 15→7、binding 50→37 均为中间版本在 flag 关下即实现；flag 在这些项上的净效应 ≈ 0 或不可分离。
- **混淆的部分**：flag 开真实运行的 obligation 22（实质口径）vs 同代码 flag 关重放 6——差值 16 混合了「新边界」与「新 LLM 输出（323 vs 388 条，粒度变粗）」两个变量，**抽样归因不可判**。唯一干净的拆解是补一条「当前代码 + flag 关」付费全链（计划第 3.5 步，预算 ≈¥7，**未执行——按计划需另行批准**）。
- 抽样人读已做：43 条逐条分类（碎片/实质）、10 条 FRE 逐条锚定核验、技术主题探针核对。

## 5. Go/No-Go 判定（第 5 步，建议——最终由用户拍板）

| # | 判定线（计划 §1.4） | 结果 |
|---|---|---|
| 1 | 守恒失败面净收敛或持平且可解释（尤其 obligation 与 binding） | **✗** binding/evidence/duplicates/preservation 收敛或持平 ✓，但 obligation 实质口径 18→22（+4）、对同代码基线 6 恶化 |
| 2 | 收敛可归因于 flag 重切本身 | **✗** 收敛项主要来自中间版本（底账证明）；obligation 恶化归因混合不可判 |
| 3 | 无新增块丢失/守恒违例（OutlineAuthorityError 零出现） | ✓ 821=821、无违例 |
| 4 | 新切条款 FRE 抽样无跨条款借位/引句失锚 | ✓ 10/10 |
| 5 | ABNT 对照无过激重切 | ✓ 358→361 |

**建议：No-Go（暂缓默认翻转）。** 缺口集中且可修复：

1. 义务检测器碎片误报（两边各 21 条碎片）：新切条款上的句子切分把"shall include:"类片段当义务——裁决/检测器细化可削减假阳性基数；
2. 新切小条款的主题内粒度漏抽（8.4.1 密钥三连、8.12 审计/EAL 余量、净计量兄弟句）：prompt 对短条款的覆盖强化或近邻条款合并策略；
3. heading-only 条款的退化 objective（标题回声）：prompt 硬化；
4. 可选第 3.5 步（¥7）干净拆解 LLM 方差 vs 边界效应——需用户批准后执行。

**积极证据（保留）：** 病灶条款 BLK-000240 修复成功且义务全覆盖；重切边界本身无守恒代价；ABNT 上克制；duplicates 归零在新产品中保持。

## 6. 数据与产物路径（机器本地，不进仓）

- flag 开结果包：`C:\Users\YYHwudi\Desktop\Canna-29\1780709839_SBD_ZETDC\result-outline-on\`（含 llm_trace.jsonl 全量账本）
- 只读基线：同目录 `result3\`（本次验证全程零写入，审计工具前后哈希一致）
- 回放/底账脚本与数据：`out/tools/replay_outline2b.py`、`out/tools/replay_outline2b_attribution.py`、`out/outline2b-replay-result3.json`、`out/outline2b-replay-abnt_nbr_16968_atomizer_v5.json`、`out/outline2b-attribution.json`、`out/outline2b-paid-run-meta.json`
- 运行元数据：chain producer 含 `outline-authority-v1` 血统；run_manifest 记录 requirements-analysis/clarification-report 被守恒闸拦截的原始理由
