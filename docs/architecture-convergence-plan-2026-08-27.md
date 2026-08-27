# 目标架构与收敛路线图（2026-08-27 定稿）

> 背景：用户裁定"框架先搭建正确，之前的框架很明显是不正确的"，并要求快速完成架构切换。
> 本文冻结目标架构终态与绞杀式收敛路线；此后所有实施对照本文推进，不再打局部补丁。
> 纪律不变：宁漏勿错、血统如实、失败不冒充成功、版本 bump 进指纹、客户内容不进仓。

## 一、诊断（四个框架级错误）

1. **无文档结构权威**：管线直接信任解析器 heading/section_path。实证病理：正文句升格
   heading（"26 There shall be no change of OEM..."）、section_path 撞名（ABNT 337/358
   chunk 共享一个 id）、chunk 节无自身标题（CH-000004）、块流吞下一章 heading
   （"2.2 Delivery Schedule" 吞进 "2.3 STATEMENT OF REQUIREMENTS (TECHNICAL)"）。
   tender 路由 v3/v4/v5 全部是这个地基错误的下游代偿。
2. **路由两套权威、粒度错、信号错**：unit_router（单元级）与 tender 词表路由（节级、
   长在 functional_extract）并存；节级 all-or-nothing 制造假两难（15 GUARANTEED LIFE
   SPAN）；最有区分度的信号——义务主体（bidder shall vs meter shall）——完全未用。
3. **守恒对内容类型不分轨**：token 级 preservation 把表格数字当散文义务背账
   （section 6 的 49/50 blocking），同一数字在 A 轨 cell 守恒与 B 轨叙述保留被记两次账。
4. **验证框架单点化**：ABNT golden 是单文档回归钉却占了合并门权重；真实故障
   （招标 PDF 病理、B 轨守恒）它一项不覆盖。质量金标应是人工真值集，回归保护应是
   文档类型组合钉。

## 二、目标架构终态

- **单一内容模型**：文档 → 验证过的大纲 → 带类型的内容单元（extraction_units 为唯一
  分解权威：散文义务句/表格事实/定义/程序性文本/引用），全部下游（路由/抽取/守恒/
  评审/批注）挂单元。
- **单一路由权威**：unit_router 吸收 tender 区域判定，义务主体为一等信号；节级结论 =
  单元级判定的聚合，tender_regions 词表降级为辅助证据。
- **分轨守恒**：散文义务走义务覆盖，表格事实走既有 cell 级守恒（table_cell_dispositions
  恰好一次处置），B 轨 preservation 基线只含 b_track 单元内容；被委托给 cell 守恒的
  内容留审计痕，不静默消失。
- **单一账本 + 单一评审队列**（Phase 2/3）：单元生命周期状态收敛进一个账本，守恒闸
  退化为账本查询；六套评审状态文件收敛为一个带类型主体的队列。
- **验证框架**：人工真值集为质量金标；回归保护为文档类型组合钉（DLMS 表格 DOCX /
  招标 PDF 病理 / 散文标准 / xlsx 的脱敏合成 fixture），ABNT 降级为组合一员。
- **基础设施收敛（Phase 3，明确延后）**：SQLite 状态存储、内容寻址 DAG 指纹。不阻塞
  产品正确性，不在快速切换范围。

## 三、收敛原则

- **绞杀式**：每一步必须写明"退役了什么旧系统"；新旧并存期短且有明确退役条件。
- **不放宽任何质量门**：守恒分轨是"把账记对"，不是"少记账"；被移出 B 轨基线的内容
  必须有 A 轨/cell 守恒兜底证据或审计痕。
- **版本纪律**：行为变化 bump 对应版本常量并穿透指纹（routing_lineage_versions 已单源，
  新增维度走同一通道）；legacy 策略指纹逐字节不变由测试钉住。
- **验收优先真实语料**：SBD result3 离线回放（机器本地，零 LLM）是每步的必验项。

## 四、Phase 1（本期，快速切换核心）——两工作流并行

### WS-C：多文档回归组合（先行/并行，纯增量低风险）

范围：tests/ 新增 fixture 与测试，不改生产代码。

1. 扩展 `test_synthetic_doc_corpus.py` 模式，新建 `tests/test_regression_portfolio.py` +
   `tests/fixtures/portfolio/`（全部合成中性语料，禁止客户词面）：
   - **招标 PDF 病理 fixture**：含正文句升格 heading、块流吞下一章 heading、
     section_path 撞名、chunk 无自身标题四类实证病理的合成 blocks 流；
   - **散文标准 fixture**：无 COSEM 表、名词短语式规格、义务句主导；
   - **混合表格 fixture**：技术表（数字/单位密集）+ 散文义务混排的节（section 6 形态）；
   - **程序性/技术混排 fixture**：bidder 义务与 meter 义务同文档（义务主体信号正反例）。
2. 每个 fixture 钉确定性输出（路由决策、守恒基线构成、单元分解计数）——小体积
   JSON 期望值随测试进仓（不是 out/ 冻结目录模式）。
3. 组合钉与 ABNT golden 并列跑，互不替代；本期不动 ABNT golden 的门槛地位（降级
   在 Phase 2 与大纲重建一起做，避免同期双变量）。

验收：新测试全绿；fixture 病理形态与 CLAUDE.md 记载的实证一一对应（注释标注出处）；
全量套件无回归。

### WS-A+B：守恒分轨 + 路由收编（同一 worktree 串行实施，核心切换）

范围：functional_extract.py、unit_router.py、tender_regions.py、extraction_units.py
及新测试。**先 A 后 B**（B 改变 b_track 单元集，A 的基线口径先立好）。

**WS-A 守恒分轨**：

1. `conservation_report` 基线按单元类型构建：
   - 义务单元只从散文型单元（clause_segment/narrative）与 b_track/mixed 表格单元取；
   - a_track/context 表格单元的内容（含数字 token）不进 narrative preservation 基线，
     改记 `preservation.delegated_to_cell_conservation` 审计清单（单元 id + 委托理由）；
   - cell dispositions 产物缺席时该表格块退回全量入基线（诚实保守，同
     apply_unit_routing 的 unavailable 语义）。
2. 版本：`FUNCTIONAL_CONSERVATION_MODEL_VERSION` bump；进缓存指纹/registry/producer
   （既有单源通道）。
3. 预期效果（SBD result3 回放验证）：section 6 的 49 条表格数字 blocking 转为委托审计
   项；剩余 preservation blocking 只含散文义务的真实丢失。

**WS-B 路由收编**：

1. `unit_router` 新增义务主体信号（确定性、句级）：
   - 程序性主体白名单（bidder/tenderer/bid/tender/employer/purchaser 等，词边界匹配）
     → 单元记 `procedural_subject`；产品主体（meter/device/DCU/equipment 等）与
     歧义主体（supplier/manufacturer/contractor）一律不判程序性（宁漏勿错）；
   - 信号进 routing decision 载荷，可审计。
2. 节级 tender 判定改为聚合：条款路由出 B 轨当且仅当（a）全部义务承载单元为
   procedural_subject 或落在程序性跨度内，且（b）无 technical 硬信号（既有
   `_section_has_tender_technical_title` 保护保留）。tender_regions 词表锚点降级为
   辅助证据（跨度锚点仍由它供给），不再单独决定整节路由。
3. 退役声明：`functional_extract` 内节级词面判定（`_section_is_tender_procedural` 的
   独立词表分支）被聚合逻辑替代；v4 句子锚点保留为跨度锚点来源。
4. 版本：`UNIT_ROUTER_VERSION`、`FUNCTIONAL_UNIT_ROUTING_VERSION` bump（血统通道
   已就位，P1 2026-08-27）；legacy 指纹不变测试钉住。

验收（两项合并验）：

- 新增单元测试覆盖：义务主体正反例（bidder→路由出证据、manufacturer→保留、
  meter→保留）、聚合规则正反例、委托审计清单形状、dispositions 缺席回退；
- SBD result3 离线回放：15 GUARANTEED LIFE SPAN 的产品指标句（15 年寿命/故障率≤3%）
  因产品主体信号被保留或进 review（节级两难消解）；技术章 1/6/7/8/9/11/21 保留；
  程序性目标条款仍全部路由出；守恒数字如实记录进报告（预期 preservation blocking
  大幅下降、uncovered 重新计数）；
- 全量后端套件绿；ABNT golden 零漂移（A 轨不受本期改动影响）或逐项说明。

## 五、Phase 2（紧随其后，单独立项）

- **大纲重建（文档结构权威）**：确定性大纲验证阶段——编号序列一致性、目录交叉验证、
  字体/位置证据校验 heading；升格正文句降回正文；重切条款边界。爆炸半径：重解析、
  atomize producer 指纹连锁、golden 重生成、claim 锚迁移。须在 Phase 1 守恒能诚实
  衡量之后做，效果才可验证。
- **ABNT golden 降级**：组合钉转正后，ABNT 成为组合一员，摘除单独合并门地位。
- **产品库/评审队列收敛启动**：atoms 退出交付物、四评审队列合并设计。

## 六、Phase 3（延后，不阻塞切换）

SQLite 状态存储、内容寻址 DAG 指纹、产品库物理合一。单独方案另立。

## 七、实施与验收纪律

- 实施在 `codex/*` 分支隔离 worktree；实施者不派生子代理；全量
  `python -m unittest discover -s tests` 绿 + 修改文件 py_compile + `git diff --check`；
  合并由用户决定；合并后主检出跑 golden。
- 每个 WS 完成后由审核方（Claude）做代码审读 + SBD result3 回放实测，数字如实
  记入 CLAUDE.md（含不利结果）。
