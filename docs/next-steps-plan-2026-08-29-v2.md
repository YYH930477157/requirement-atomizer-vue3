# 交接文档:下一阶段实施方案(v2 补强版,2026-08-29)

> 读者:接手实施的代理(Claude Code/GLM 或 grok)与审核方。
> 本文档假设读者未参与之前的会话,所有背景、路径、命令、验收标准都在文内自包含。
> **v2 修订说明(审查补强,4 处,均以【补强 v2】标注):**
> ① 任务 A 新增「对照组混淆」强制章节与归因分层(原计划拿 08-20 旧代码基线比当前
> 代码 flag 开,不是干净对照);② 任务 C 裁撤前置条件补「启动/GET 自动对账」;
> ③ 新增两项跟踪 TODO(队列 O(n²) append、幂等键装饰性);④ 任务 D 补第四候选与
> 去原子化历史教训对照。
> 配套上下文:`CLAUDE.md`(2026-08-29 条目及以前)、`TODO.md`(当前待办)、
> `docs/architecture-convergence-plan-2026-08-27.md`(架构收敛总纲)、
> `docs/review-queue-convergence-design-2026-08-27.md`(队列收敛设计)。

---

## 0. 环境事实(本机,执行前先核对)

| 项 | 值 | 说明 |
|---|---|---|
| 主检出 | `D:\Codex\requirement-atomizer-vue3` | main,HEAD=`49a1a66`(2026-08-29) |
| 全量测试 | `python tools/run_tests_parallel.py` | 主检出基线 **4199 OK / skipped=20 / ~312s**;串行 `python -m unittest discover -s tests` 是权威兜底 |
| golden | `tests/test_golden_regression.py` 6 项 | 只在主检出实跑(依赖 `out/abnt_nbr_16968_atomizer_v5/` 冻结基线);worktree 里会环境性跳过(skipped=26 是 worktree 正常口径) |
| `RATOMIZER_HISTORICAL_SAMPLE` | **本机必须不设** | 指向的 YYHwudi 路径在本机不存在,设了会出 1 failure + 1 error(环境性,非代码回归) |
| SBD 真实语料 | `D:\Users\YunHeYang\Desktop\Canna\Canna-29\17388\1780709839_.pdf` | 招标 PDF(源文件) |
| SBD 已有结果包 | `D:\Users\YunHeYang\Desktop\Canna\Canna-29\17388\result3` | flag 关基线(2026-08-20 跑,131 条款 → 388 FRE,守恒 blocked)。**只读,绝不修改** |
| ABNT 真实语料 | `D:\Users\YunHeYang\Desktop\Canna\Canna-29\Appendix 9-ABNT NBR 16968-2022 EN.docx` | 本机存在(注意:CLAUDE.md 旧条目里的 `C:\Users\YYHwudi\...` 是旧机器路径) |
| WS0 warm A 缓存 | `%TEMP%\ab-runner.uqw4d3je\A_atoms` | **本机不存在**(旧机器产物)——WS0 重跑 A 轨须全冷,成本见任务 B |
| result3 大纲回放脚本 | `out/tools/replay_outline2b.py`(主检出,已从 worktree 抢救) | 机器本地,out/ 不进仓 |
| LLM key | deepseek(用户提供,仅进程环境注入,绝不落盘/进仓) | flash=`deepseek-v4-flash`,pro 探针结论见 CLAUDE.md 2026-08-25 前后条目:pro 全局替换已否决 |
| PowerShell 5.1 | 无 `&&`/`??`;`npm.ps1` 被执行策略拦 | 用 `;` 串联;npm 用 `cmd /c "npm test"` |
| 实施纪律 | `codex/*` 分支 + 独立 worktree;先失败测试后实现;合并由用户决定;push 需用户同意 | worktree 命令模板见 §5 |

四个任务的依赖关系:

```
任务A(大纲 flag 验证)──决定默认翻转──┐
                                        ├──> 任务B(WS0 门禁重跑,付费)在 A 出结论后跑一次即可
任务C(队列收尾审计)──独立,随时可做──┘
任务D(表格保留率)──先诊断出设计文档,再立项实施(可与 A 并行)
```

**推荐顺序:C(零成本、小)与 A(核心)并行先做;A 出结论后做 B(付费只付一次);D 的诊断片随时可插。**

**【补强 v2】新增跟踪 TODO(不单独立任务,挂入 TODO.md 当前待办区):**
- 队列 append 增量化:第 3 步后四主体全部入链,`review_queue.py` 的 append 仍是
  整文件重写+全链校验(O(n²));裁决是高频写入,事件量上来后锁持有时间与耗时会
  同步恶化(任务 C 的审计工具每次也全链扫描,会放大可见性)。触发条件:单文件
  事件数 > 数千 或 锁超时出现;改造为追加写+滚动校验点,版本进 `REVIEW_QUEUE_VERSION`。
- 幂等键接线:`api_server` 的裁决端点(omission/澄清内部核对/atom_expert/ai_review)
  把 HTTP request id 透传为 `idempotency_key`——当前默认 uuid,重试/双击各记新事件,
  "恰好一次记账"在真实流量上不生效。几行改动,可与任一任务搭车。

---

## 1. 任务 A:大纲权威 flag 真实语料验证 → 默认翻转评估(最高优先)

### 1.1 背景与现状

Phase 2b 第一片已合 main(merge `6fe5250`,实现提交 `bef6a86`):

- `RATOMIZER_OUTLINE_AUTHORITY`(config.ENV_REGISTRY 已登记,**默认 `0`**)。
- flag 开时 B 轨条款装配按 `document_outline.py` 裁决重切边界:
  - `demoted_body_sentence`(被解析器升格成 heading 的正文义务句)→ 并入前条款;
  - 被吞并的 `confirmed` heading(非首位出现在条款块序列里)→ 切开成新条款,
    身份 = `[heading 文本]`,不继承病理父链;
  - `toc_entry` → 出正文基线,只审计不删块;
  - `suspect` → 宁漏勿错,不动。
- 重切是纯函数 `document_outline.recut_clauses`;唯一 flag 检查点
  `document_outline.apply_outline_authority`;两个消费点
  `extract_units.assemble_sections_detailed` 与 `functional_extract.load_clauses_detailed`。
- 块守恒硬校验(输入块恰好归属一个条款或登记排除,违例抛 `OutlineAuthorityError`);
  大纲报告不可得时如实回退旧切分,产物记 `outline_authority: unavailable:<reason>`。
- flag 开时 `outline-authority-v1` 进 functional-extract 抽取缓存指纹(legacy/clause_family
  两键空间)、chain 阶段 producer、ai-extract 付费缓存/发布 lineage——**flag 开必然缓存
  全 miss,重抽是预期行为**。
- **已有零成本证据**(result3 离线回放):207→239 条款(39 demoted 并入 + 34 confirmed
  吞并切开),BLK-000240「2.3 STATEMENT OF REQUIREMENTS (TECHNICAL)」切出为独立条款,
  块守恒 821=821。

**还没有的证据**(本任务要补的):flag 开的**真实付费全链**表现——新边界下守恒四项
(duplicates/obligation/preservation/binding)、路由计数、claim 发布与锚定、成文闸
是否比 flag 关基线更好或至少不更差。

### 1.2 目标与非目标

**目标**:产出一份对照报告(flag 开 vs flag 关,同一文档、同一模型、同一策略),
数据充分到能对「默认翻转」做 Go/No-Go 判定。

**非目标(本任务禁止做)**:
- 不翻默认(`config.ENV_REGISTRY` 里 `RATOMIZER_OUTLINE_AUTHORITY` 保持 `"0"`);
- 不改 `document_outline.py`/`recut_clauses` 语义(发现缺陷 → 记录 + 单独提修复分支);
- 不放宽守恒、不动 prompt、不动 `RATOMIZER_EXECUTION_POLICY`;
- 不修改 result3 原目录(只读基线)。

### 1.3 前置条件

- deepseek key(用户提供),余额确认够(估算见 1.4 第 3 步)。
- SBD 源 PDF 在场:`D:\Users\YunHeYang\Desktop\Canna\Canna-29\17388\1780709839_.pdf`。
- 主检出 4199 基线绿(执行前跑一次确认起点干净)。

### 1.4 实施步骤

**第 1 步(零成本):重建离线回放确认合并后行为一致。**

```powershell
cd D:\Codex\requirement-atomizer-vue3
python out\tools\replay_outline2b.py  # 参数看脚本头部,指向 result3 只读副本
```

预期与 `bef6a86` 提交信息一致:207→239、BLK-000240 切出、块守恒 821=821。
不一致 → 停下排查(合并出了问题),不许继续付费步骤。

**第 2 步(零成本):ABNT 边界对照(B 轨影响面预估)。**

对 ABNT docx 的 blocks 跑 `document_outline.build_outline_report` + `recut_clauses`
(写个一次性脚本进 `out/tools/`,参照 replay_outline2b.py 的加载方式)。记录:
条款数变化、demoted/swallowed/toc/suspect 计数、块守恒。ABNT 是结构良好的 DOCX,
**预期变化应当很小**(吞并/降格主要是招标 PDF 病理);如果 ABNT 也大量重切,
说明裁决过激,翻转评估直接倾向 No-Go,记录进报告。

> 注意:ABNT 的 A 轨 atomize/golden 与本 flag 无关(flag 只接在 B 轨条款装配),
> 这一步不需要跑 golden。

**【补强 v2】第 2.5 步(零成本,新增):中间版本归因底账。**

result3 基线是 **2026-08-20 代码**跑的;当前 main 与其之间隔着 routing v5→v6、
conservation v4→v5(守恒分轨/委托剔除)、tender filter v3→v4、队列第 2/3 步等
多个行为版本。**直接对比 = 「旧代码 flag 关」vs「新代码 flag 开」,不是干净的
flag 对照**——本任务必须先建立归因底账,否则第 4/5 步的结论证据强度是虚的:

1. 用离线回放(第 1 步同款机械)在 **result3 的原始 blocks/chunks 上**以当前代码
   重放确定性层(条款装配、路由计数、守恒基线构成),得到「同输入、当前代码、
   flag 关」的确定性层数字,与 result3 记录值对照——差异即为**中间版本贡献**,
   零成本可量化;
2. 该底账进报告附录;第 4 步对照表每行标注归因:`flag 重切` / `中间版本` /
   `混合(无法区分)` / `LLM 方差`;
3. LLM 相关项(FRE 质量、叙述覆盖类守恒)无法零成本归因——如实标「混淆」,
   靠抽样人读逐条归因,不许默认归给 flag。

**第 3 步(付费,核心):SBD flag 开全链跑。**

```powershell
# 新建隔离输出目录(不进仓、不碰 result3),例:
$out = 'D:\Users\YunHeYang\Desktop\Canna\Canna-29\17388\result-outline-on'
$env:RATOMIZER_OUTLINE_AUTHORITY = '1'
$env:RATOMIZER_LLM_API_KEY = '<用户提供的 key>'
# 其余 env 与 result3 当时一致:直抽默认开、策略未设(生效 clause_family)
python desktop_tasks.py chain --input 'D:\Users\YunHeYang\Desktop\Canna\Canna-29\17388\1780709839_.pdf' --out $out <--llm 路由参数与 result3 相同:openai_compatible + deepseek-v4-flash>
```

具体 chain 参数以 `desktop_task_args.py` 的 `chain` 子命令为准(读代码确认,
不要凭记忆写)。成本预估:result3 当时 131 条款直抽 ~112 分钟(flash);
flag 开后 239 条款,条款数近 2 倍但单条款更短(吞并块被切开),token 总量
接近(同一份文档内容),但**调用次数近 2 倍、时长上浮风险高于 token 风险**,
预估 2-3 小时、成本与 result3 直抽同数量级。
翻译阶段可跑可不跑(与本验证无关,跳过可省 80% 成本——如 chain 支持阶段裁剪,
只跑 atomize→functional-extract→requirements-analysis 即可)。

**第 4 步:对照报告。**

从两个结果包(result3 = flag 关基线,result-outline-on = flag 开)提取并对照:

| 维度 | 数据源 | 关注点 | 【补强 v2】归因要求 |
|---|---|---|---|
| 条款数/路由计数 | `functional_requirements.json` 的 `unit_routing` 审计块 + `outline_authority` 审计块 | sections_extracted、routed_out 分布是否合理;`outline_authority.status=applied` | 用 2.5 步底账区分 flag 与中间版本贡献 |
| 守恒四项 | conservation report(产物内 `conservation` 块) | duplicates / obligation_coverage / preservation blocking / binding_mismatches 各自升降;**重点:BLK-000240 所在的 2.3 STATEMENT OF REQUIREMENTS 切出后,其义务是否被正确覆盖** | 基线构成变化(委托/路由)先按 2.5 步归因,再看 flag 净效应 |
| FRE 数量与质量抽样 | `functional_requirements.json` items | 新切出条款产出的 FRE 抽 10 条人读核对(引句锚定、无跨条款借位) | 抽样逐条标注:缺陷是否与新边界相关(旧边界下同样会有的问题不算 flag 的账) |
| claim 发布 | `.ratomizer/pipeline` claim 产物 + fold 结果 | 发布成功、锚定失配计数不升高 | 锚定几何以块为基,flag 不动块——失配变化应能追溯到条款归属变化 |
| 执行状态 | `run_manifest.json` | functional-extract=ok/partial;requirements-analysis 是否仍被守恒闸拦(拦了要看拦的理由是否比基线更收敛) | — |

**【补强 v2】第 4.5 步(新增,强制章节):对照组混淆声明。**

报告必须含独立章节「对照有效性」:写明基线代码版本差(08-20 vs 当前)、
2.5 步底账量化结果、哪些结论是干净的(确定性层、同代码回放可比)、哪些是混淆的
(LLM 相关项)及其抽样归因结果。**没有这一章,报告不接受进入第 5 步判定。**

**第 5 步:Go/No-Go 判定建议(写进报告,最终由用户拍板)。**

Go(可提默认翻转立项)的判定线:
- 守恒失败面净收敛(尤其 obligation uncovered 与 binding)或持平且可解释;
- **【补强 v2】上述收敛/持平可归因于 flag 重切本身(经 2.5 步底账与抽样归因),
  不依赖无法区分的混合变化撑数字**;
- 无新增的块丢失/守恒违例(`OutlineAuthorityError` 零出现);
- 新切条款的 FRE 抽样无跨条款借位/引句失锚;
- ABNT 对照(第 2 步)无过激重切。

任一不满足 → No-Go,缺陷逐条记录,回到 `document_outline` 裁决语义修复后再来。

### 1.5 交付物与验收

- 对照报告:`docs/outline-authority-validation-2026-08-XX.md`(数据带来源路径;
  结果包本身不进仓;**含 4.5 步「对照有效性」强制章节与 2.5 步归因底账附录**)。
- CLAUDE.md 新条目(结论 + 数据 + Go/No-Go 建议)。
- 代码零修改(如发现缺陷,单独开分支修,不混在验证里)。
- 主检出全量 4199 基线不动(本任务不该动任何测试)。

### 1.6 红线

- key 只进进程环境;结果包含客户内容,不进仓;报告里引用原文要脱敏截断。
- flag 开的运行绝不写回 result3;两个结果包目录物理隔离。
- 不许为了「让数字好看」调整任何守恒/路由参数——本任务是测量,不是调优。

预计工作量:零成本部分 0.5-1 天(含 2.5 步底账);付费跑 2-3 小时挂机 + 对照分析
0.5-1 天。

---

## 2. 任务 B:WS0 真值门禁重跑(付费,在任务 A 出结论后执行)

### 2.1 背景与现状

WS0 门禁 = `tools/ab_runner.py` 的 A/B 双轨对照 + 真值集阈值门(报告 schema
`ab-runner-report/v3`),决定 `RATOMIZER_EXECUTION_POLICY` 能否默认翻转(计划 §31)。
2026-08-17 执行过一次,**FAIL**(`docs/ws0-gate-result-2026-08-17.md` 有完整记录),
三个根因当时已定位、如今全部修复在案:

1. XLSX 读取器认不出模板正文列 → 已修(2026-08-17b:模板行界校准 + 写入器列契约兜底);
2. B 轨表格内容混入致守恒失败(duplicates=6)→ 已修(§17 unit 路由接线 + clause_family 策略);
3. guards 表格 marker 假失配 → 已修(guards-v6 剥 `[TBL-NNNNNN]`)。

### 2.2 为什么放在任务 A 之后

如果任务 A 判定默认翻转 Go,B 轨条款边界会变——门禁应当在**最终形态**下跑,
否则要付两次钱。若 A 判 No-Go,则按现状(flag 关)跑。

### 2.3 前置条件(执行前逐项确认,缺一不跑)

- **真值集**:2026-08-17 用的是「Canna29 xlsx 中文 Analysis 列,190 行」。
  本机 `D:\Users\YunHeYang\Desktop\Canna\Canna-29\` 下有多个候选 xlsx
  (`Canna-29电表软件标准化需求列表-V1.2 ...xlsx`、`Canna29 ...Especificacao_Tecnica_Final.xlsx` 等),
  **旧真值转换产物在旧机器上,本机路径需要向用户确认**;确认后按
  `schemas/functional_truth.schema.json` 校验(坏行响亮报错)。
- **阈值文件**:14 必需键(`tools/ab_runner.py` 的 `REQUIRED_THRESHOLD_KEYS`),
  上次用 runbook 示例阈值——本次是否沿用需用户确认。缺阈值 = NO_GATE,不是 PASS。
- **模板**:公司模板 xlsx(`电表软件标准化需求列表-V2.3.12`),本机路径需确认。
- **warm A 缓存不存在**(`%TEMP%\ab-runner.uqw4d3je\A_atoms` 已核实 False):
  A 轨全冷。**成本估算:A 轨 2026-08-17 中止时 70/343 节已花 ¥8.07,外推全量 ¥40+;
  B 轨直抽 ~24 万 token。总预算按 ¥60-80 报给用户批准后再跑。**
- key 余额确认覆盖上述预算。

### 2.4 实施步骤

1. 精读 `docs/ws0-gate-result-2026-08-17.md` 的 runbook 段落(命令形状以它为准)。
2. 核对本机路径(真值/模板/被测文档),逐项替换 runbook 里的旧机器路径。
3. 环境:`RATOMIZER_CONTEXT_PACK_STRATEGY=clause_family` **必设**(gate_verify 实证
   上次门禁 B 腿即此策略);若任务 A 判 Go 且用户同意按新形态测,另设
   `RATOMIZER_OUTLINE_AUTHORITY=1`(并在报告里显式记录 flag 状态)。
4. `$env:PYTHONPATH='.'` 后跑 ab_runner(CLI 需要 PYTHONPATH=.,2026-08-17 实证)。
5. 报告归档 `docs/ws0-gate-result-2026-08-XX.md`:PASS(0)/NO_GATE(1)/FAIL(2) 如实记,
   **FAIL 不许通过调阈值洗成 PASS**;FAIL 根因逐条带 file:line 定位。

### 2.5 验收

- 三态结论 + 完整成本账(calls/tokens/金额)+ 报告文档入仓。
- PASS → 提 `RATOMIZER_EXECUTION_POLICY` 默认翻转议案(单独立项,含回滚通道);
  FAIL → 根因清单转修复任务。

预计工作量:路径确认 0.5 天 + 挂机数小时 + 报告 0.5 天。

---

## 3. 任务 C:队列收敛收尾——投影一致性审计工具 + 兼容期观察(独立,随时可做)

### 3.1 背景与现状

四主体已全部入统一事件链 `review_queue_events.jsonl`(第 2 步 `9652e89`:omission +
clarification_internal;第 3 步 `441fde8`:atom_expert + ai_review)。旧四文件
(`omission_states.jsonl` / `clarification_check_states.jsonl` / `review_states.jsonl` /
`ai_review_states.jsonl`)现在是**逐字节兼容投影**,承诺保持 ≥ 两个桌面发布周期
(设计文档 §6)。

投影正确性目前只有单元测试钉着;**真实结果包上的持续一致性没有独立审计工具**。
崩溃窗口补投影逻辑(尤其 A 轨的 merge+单行替换对账,与 llm_pipeline 批量 merge
共存)是第 3 步风险最高的部分,值得在兼容期内有工具可随时体检。

### 3.2 目标

新增只读审计工具 `tools/audit_review_queue_projection.py`(零 LLM、零写入):

1. 读 `review_queue_events.jsonl`(复用 `review_queue.py` 的扫描/验链函数,
   不重新实现哈希链校验);
2. 对四个 subject_kind 各自按该主体的投影语义重放出「期望的旧文件内容」:
   - omission / ai_review / clarification_internal:append-only 序(第 2 步/第 3 步 B 轨语义);
   - atom_expert:merge+单行替换语义(照抄 `review_state._project_missing_expert_rows`
     的身份键索引,**调用它而不是复制它**——单一权威);
3. 与磁盘上的旧文件逐主体比对,输出 JSON 报告:每主体 `consistent | drift`(drift 带
   具体 requirement/clarification id 与差异摘要)+ 链完整性 + 事件计数;
4. 特别豁免:`review_states.jsonl` 上由 llm_pipeline 批量 merge 产生的**非 expert 行**
   不在队列链上(自动化路径刻意不入链,设计 §5.3)——审计只比对链上有事件的主体行,
   文件里多出的自动化行不算 drift(但要计数上报 `non_queue_rows`)。

CLI 契约:`python tools/audit_review_queue_projection.py --out-dir <结果包>`,
stdout JSON envelope,exit 0=一致 / 2=发现 drift / 3=输入损坏(与 cli-contract 同族)。

### 3.3 测试要求

`tests/test_audit_review_queue_projection.py`(unittest.TestCase):
- 四主体各一条正例(写入→审计一致);
- 人为篡改旧文件一行 → drift 检出并定位;
- 崩溃窗口构造(队列有事件、旧文件缺行)→ drift 检出(这正是补投影该修的场景);
- llm_pipeline merge 的非 expert 行在场 → 不算 drift、计入 non_queue_rows;
- 队列文件损坏 → exit 3 fail-closed。

### 3.4 兼容期观察与裁撤评估(工具就位后)

- 在真实结果包(result3 及日常使用产生的新包)上定期跑审计,drift 零容忍
  (出现即为第 3 步实现缺陷,立即开修复分支);
- 两个桌面发布周期后出「读者迁移盘点」:设计文档 §3 已列旧文件全部读者
  (API GET / clarification_report 就绪门 / agent_state / xlsx 导入回读等),
  逐读者评估改读队列投影 API 的成本——**这一步只出评估文档,不动代码**。

**【补强 v2】裁撤前置条件补两条(写进「读者迁移盘点」的开工条件,顺序在盘点之前):**

1. **启动/GET 自动对账(告警级)**:审计工具是"有人跑才发现",兼容期靠流程纪律可接受;
   但**旧文件裁撤的那一刻**,崩溃窗口从"陈旧但可审计"变成"陈旧且无人知道"。
   裁撤前必须完成:api_server 启动维护或读者首次加载路径上的一次队列↔投影对账,
   发现 drift 即告警/结构化 503 引导修复(复用 `missing_projection_payloads` 机械,
   只加触发点)。审计工具先行的价值正是为这一步验证对账语义。
2. **append 增量化落地或量化豁免**:见 §0 新增 TODO——若裁撤评估时事件量已到
   数千行,O(n²) 重写必须先改增量,否则自动对账的每次启动扫描会放大锁竞争。

### 3.5 红线与验收

- 工具绝对只读(打开文件一律只读模式;不修复、不补投影——修复是写路径的职责);
- 不改 `review_queue.py`/`review_state.py`/`ai_review_actions.py` 任何行为;
- 全量并行门绿(4199 + 新增审计测试数)。

预计工作量:1 天(适合作为一个独立 GLM 线程任务)。

---

## 4. 任务 D:技术表格保留率课题——先诊断后设计(中期,可与 A 并行)

### 4.1 背景与现状

SBD result3 的 preservation blocking ~50 项集中在「6 TECHNICAL DATA REQUIREMENTS
TABLE」表格数字(2026-08-26/27 两轮路由收敛后,程序性噪声出清,失败面如实归因
到该表)。WS-A 已实证:可整块委托的表(BLK-000271/273)早被 clause_family 的
all_table 路由出基线;**剩余 blocking 全在带真实义务模态的 b_track/review 表上**
(hard_b_only 证据)——即真需要 B 轨抽取、但 flash 直抽丢表内数字的表。

### 4.2 本任务范围:只出诊断 + 设计文档,不写生产代码

(照 WS-E 评审队列收敛设计的模式:先设计、评审通过再立项实施。)

**诊断步骤(零成本,用 result3 现有产物):**

1. 从 conservation report 提取全部 preservation blocking 项,逐项标注:
   所属块/行/格、丢失的 token(数字/单位/编码)、该块的 disposition 与 unit 路由;
2. 分类统计:
   - a 类:行级 FRE 已存在但叙述丢数字(LLM 输出质量问题);
   - b 类:该行根本没有对应 FRE(覆盖缺口);
   - c 类:数字在表头/题注/合并格,行渲染文本就没带到(输入侧问题);
3. 对照 guards-v16 参数表行展开(A 轨已有确定性逐行机制 `PROW-DET-*`):这些表
   是否满足参数表判定?不满足的差在哪个判据。

**设计文档要回答的问题(`docs/table-preservation-design-2026-0X-XX.md`):**

- **【补强 v2】四个候选方向的取舍(原三个 + 新增第四个,按诊断数据说话,不拍脑袋):**
  1. **行/格粒度 B 轨抽取**:义务表按行成单元进直抽 prompt(extraction_units 已有
     row leaf 机械),每行独立 FRE——成本上升多少、对非表格条款零影响怎么保证;
  2. **确定性行展开进 B 轨**(照搬 A 轨 guards-v16 `PROW-DET` 思路):满足参数表
     判定的义务表行直接确定性生成 FRE(零 LLM、引句逐字)——判定边界怎么划,
     误判成本是什么;
  3. **专家定点闭环**:保留现状守恒拦截,靠 claim 队列 targeted_reextract + 专家
     裁决逐表收敛——人工成本估算;
  4. **(新增)行数据挂功能语义而非独立 FRE**:表格行不生成独立需求条目,而是作为
     所属功能需求的 `data_constraints`/参数附表结构化挂载(直抽 prompt 已有该
     语义:「表格行机械事实归并入所属需求的 data_constraints」)——a 类丢失
     (行 FRE 在但叙述丢数字)本质上是这个语义没执行到位,把它做实可能是
     **零新增条目数**的修法。**设计必须对照去原子化的历史教训评估候选 1/2:**
     行级独立 FRE 与被否掉的原子化在形态上是近亲,须回答"行条目如何挂回功能
     语义、会不会重演『该并没并、需求变散』",以及最终 xlsx 里同一功能占几行
     (去原子化方案的原始验收指标)。
- 版本面影响:动到哪些 `*_VERSION`、缓存失效范围、golden 是否受影响(B 轨不触
  atomize,预期 golden 零漂移,要写明依据)。
- 与任务 A 的交互:大纲重切后表格块的条款归属可能变化,设计要声明对 flag 开/关
  两形态都成立。

### 4.3 验收

- 诊断数据表(50 项逐项分类,进设计文档附录,客户内容脱敏);
- 设计文档过审核(方向选择有数据支撑,四个候选全部评估);
- 零生产代码改动。

预计工作量:诊断 1 天 + 设计 1-2 天。

---

## 5. 执行方式与审核流程(所有任务通用)

### 5.1 worktree 与线程模板

```powershell
cd D:\Codex\requirement-atomizer-vue3
git worktree add D:\Codex\ratomizer-wt-<名字> -b codex/<分支名>
# GLM 线程启动(后台,日志落盘):
$env:DISABLE_AUTOUPDATER='1'
cd D:\Codex\ratomizer-wt-<名字>
claude --dangerously-skip-permissions -p "请读取 D:\Codex\claude-task-<名字>.md 并严格按其中全部要求执行任务。注意:worktree 已经建好,你当前就在 D:\Codex\ratomizer-wt-<名字> 里,不要再执行 git worktree add,直接开始调查和实施。" 2>&1 | Tee-Object -FilePath D:\Codex\glm-<名字>.log
```

任务书(`claude-task-*.md`)必须自包含:背景、精确文件与行为要求、硬约束红线、
测试要求、验证命令、「只 commit 不 push」、提交信息三段式(原因/现象/解决方法)。
参考现成样例:`D:\Codex\claude-task-queuestep3.md`、`D:\Codex\claude-task-outline2b.md`。

### 5.2 审核清单(合并前逐项过)

1. `git diff` 逐文件审产线代码(测试可抽查);红线逐条核对(各任务 §红线);
2. worktree 全量并行门绿(4199 基线 + 新增数;skipped=26 是 worktree 正常口径);
3. 主检出合并后再跑一次全量(golden 实跑,skipped=20 口径);
4. 涉及行为版本 bump 的:核对指纹/registry/producer 同步(历史教训:缓存指纹
   缺版本 = 新行为被旧缓存静默绕过);
5. CLAUDE.md 条目 + TODO.md 勾选随合并提交;
6. push 前问用户。

### 5.3 付费任务附加纪律(任务 A 第 3 步、任务 B)

- 跑前把成本预算报用户批准;
- key 只进进程环境变量,跑完即清(`Remove-Item Env:RATOMIZER_LLM_API_KEY`);
- 成本事实(calls/tokens/金额/中断)如实进报告——失败与中止不许从账上抹掉;
- 结果包(含客户内容)永不进仓;报告引用原文须截断脱敏。

---

## 6. 后续排期(本文档不展开,完成上述后再立项)

- **默认翻转两件套**(若 A、B 均 Go):`RATOMIZER_OUTLINE_AUTHORITY` 与
  `RATOMIZER_EXECUTION_POLICY` 各自单独立项翻转(各带回滚通道 + golden 重生成评估)。
- **架构收敛 Phase 3**:SQLite 状态存储 + 内容寻址 DAG 指纹
  (`docs/architecture-convergence-plan-2026-08-27.md` §Phase 3)。
- **测试套件有据瘦身**(可选低优先):全量已并行化至 ~5 分钟,痛点已解;
  如仍要做,逐文件审计清单制,禁止按数量指标批量删钉。
