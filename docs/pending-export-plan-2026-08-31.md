# 修改方案：守恒未闭合的「待核成文」（partial export）——v2（并入 grok 审核三条）

> 提出方：ZCode（GLM）；设计基线：grok 分层表 + grok 审核（2026-09-01，三条
> 全部采纳，其中第 3 条纠正了 v1 §2.4 的方向性错误）。审核后由 ZCode 实施。

## v2 修订（grok 审核结论）

1. **连带口径**：uncovered/preservation 必须连带「声明在该条款块上的 FRE」
   （`source_block_ids ∩ 条款 block_ids`，与检查 5 叙述并集同口径）——只标直接
   点名会让这两类在 xlsx 上零行。定位键 = 条款 block_ids 元组（禁 section_id
   字符串定位，SBD 撞名病理）；finding 无 block_ids 时由标记侧从 sections 按
   id + 内容证据（义务句包含/保留 token 在场）确定性还原，**不 bump 守恒模型**。
   零 FRE 条款不造占位行；duplicates 只标组内成员（组自带 FRE id 清单）。
2. **指纹面**：`conservation-partial-export-v1` 进 requirements-analysis 与
   template-write 的 stage_producer 及两阶段 input fingerprint；开关
   `RATOMIZER_PARTIAL_EXPORT` 的**有效值**同入（=0/=1 不互复用）。不进
   functional-extract 指纹、不 bump 守恒模型。prompt_registry 登记标记算法
   身份（登记与进戳都做）。
3. **直抽资格（纠正 v1 §2.4）**：`FunctionalExtractionIncompleteError` 不整类
   拦——其中 **execution_status=partial（mixed，部分条款 stub）走旁路**
   （SBD result3/flag-on 均此形态，整类拦 = 主语料仍无表）；**failed（整段
   stub）与 draft:true 仍拦**。chain 捕获时读产物 execution_status 分流。
   stub 退化条款的行加独立失败类 `extract_degraded`（与守恒待核区分）。
   `stage_is_reusable` 维持现状（只 functional-extract 的 mixed/partial 可
   复用，`desktop_tasks.py:1666`）——不重开。

## 0. 目标 / 非目标

**目标**：守恒有 blocking 时，分析师仍拿到根目录的 `软件需求列表-成文.xlsx`
（注册名不变），失败行带「待核 + 失败类」标记；机器面全部如实记 partial /
incomplete，不冒充完成代。

**非目标**：守恒 ok 判定不动；READY/Ledger Ready 不动；`functional_direct_basis`
与 Claim 发布继续拒；WS0 门禁继续 FAIL（xlsx 在场 ≠ conservation.ok）；不覆盖
已完成代的根交付物（08-03 R2 原样）；FRE 不打 `draft:true`（stub 水印语义）。

## 1. 现状机械（已逐一核实）

- 闸的抛点：`functional_extract.raise_if_unconserved`（`FunctionalConservationError`），
  由 `requirements_analysis.py:235` 调用（分析阶段内部自检）；chain 在
  `desktop_tasks.py:2677` 接住该异常 → 阶段记 failed → `conservation_blocked=True`
  → 后续 `conservation_gated = {requirements-analysis, template-write,
  clarification-report}`（`desktop_tasks.py:2540`）整段跳过。
- partial 发布路径已存在（I6，`desktop_tasks.py:3162-3171`）：
  `result-package-complete` 遇 `ResultPackagePartialError` → `record_analysis_partial`
  → **首代**（`result_package.py:1371-1373`）`analysis_status=incomplete` +
  `_publish_package_unlocked`（xlsx 落根、注册交付物）→ envelope
  `requested_stage_partial` exit 2；桌面已画「分析未完成（部分阶段降级）」
  （`App.vue:2345`）。**本方案不需要任何新状态。**
- 身份链：`requirements_analysis.py:1492` 把 `functional_requirement_id` 透传进
  engineering_analysis 条目 → template_writer 行可按它回连守恒失败明细。

## 2. 改动清单（按文件）

### 2.1 `functional_extract.py`——旁路参数 + 待核标记权威

1. `raise_if_unconserved(conservation, *, allow_unclosed: bool = False)`：True 时不
   抛、返回待核摘要（不改变守恒报告本身）。
2. 新增纯函数 `conservation_pending_marks(report, items, sections) ->
   dict[str, list[str]]`：FRE id → 失败类列表。类来源（确定性）：
   - `binding` / `evidence`：`binding_mismatches` / `evidence_mismatches` 中点名
     的 `functional_requirement_id`（直接）；
   - `uncovered` / `preservation`：失败项按 `section_id` 定位条款 → 该条款
     `block_ids` 上**声明的** FRE 连带（借道 items 的 `source_block_ids`）。
   未被点名的 FRE 不标记。这是「待核」的单一权威定义，进 prompt_registry。
3. 新常量 `CONSERVATION_PARTIAL_EXPORT_VERSION = "conservation-partial-export-v1"`
   （进 chain producer 与 prompt_registry——分析/成文在未闭合基线上的产物有了
   自己的血统身份，不与闭合代混淆）。

### 2.2 `requirements_analysis.py`——透传标记

- 接 `allow_unclosed`（由 chain 传入；直连调用默认 False 保持现行为）。
- 每条输出条目附 `conservation_pending: {classes: [...]}`（来自 2.1 的权威函数；
   干净条目不带该字段）。

### 2.3 `template_writer.py`——行级标记（v2→v3）

- `build_row_values`：条目有 `conservation_pending` 时，说明列（表头解析后的
  notes 列）前缀 `⚠待核（绑定失配/保留丢失/义务未覆盖…）`；正文兜底链不变；
  **不**打 `draft:true`。
- 报告新增 `conservation_pending_export: {marked_rows: N, classes: {...}}`。
- 文件名保持注册名 `软件需求列表-成文.xlsx`；不动物理模板结构（「封面说明」
  由交付物面板/运行页文案承担，见 2.5）。

### 2.4 `desktop_tasks.py` chain_task——闸改「跑 + 标 partial」

- `FunctionalConservationError` 分支改为：记录 `conservation_blocked`（保留原义：
   未闭合）后**不再置 blocked-skip**；对本阶段与后续 gated 阶段传
   `allow_unclosed=True` 继续执行。
- 阶段 manifest 状态：这三个阶段跑完记 **`partial`**（不是 ok——防下一轮
  `stage_is_reusable` 当干净成文复用；需核 `desktop_tasks.py:1668` 一带的
  partial 不可复用语义并加钉）。
- chain 载荷：保留 `conservation_blocked` / `conservation_block_error`，新增
   `partial_export: true` + `pending_marked_rows: N`——区分「拦住了、没有表」与
   「未闭合、表已出」。
- `FunctionalExtractionIncompleteError`（直抽 stub/mixed）**不在此旁路**：抽取
   不完整仍整段拦（那是数据不完整，不是守恒未闭合）。

### 2.5 `ui/`——文案与呈现

- `App.vue`：payload 有 `partial_export` 时，运行卡从「成文已阻断」改为
  「**成文已出（N 条待核）**」，链接到交付物面板；交付物面板在该文件上标注
  「守恒未闭合的待核成文」。`api-client.ts` 补 `partial_export` /
  `pending_marked_rows` 字段类型。

### 2.6 `config.py`——回滚开关

- 登记 `RATOMIZER_PARTIAL_EXPORT`（默认 `1`；`=0` 回到今天的整段拦截行为）。
  政策反转带一条退路，成本一行。

## 3. 各层语义（沿用 grok 分层表，全部照办）

| 层 | 值 |
|---|---|
| 结果包 `analysis_status`（首代） | `incomplete`（partial 发布路径既有行为） |
| `last_attempt.status` | `partial` |
| CLI / 桌面 | `requested_stage_partial`（exit 2，既有错误面） |
| 就绪判定 | NEEDS WORK（不动） |
| template-write / requirements-analysis 阶段 | `partial`（不可当干净复用） |
| 直抽 `execution_status` | 保持抽取事实（通常 ok） |
| FRE `draft:true` | 不打 |
| Claim 发布 / `functional_direct_basis` | 仍拦（旁路只开给分析·成文·澄清） |
| WS0 门禁 | 仍 FAIL（读 conservation，不看 xlsx 在场） |
| 根交付物覆盖 | 非首代 partial 不覆盖已完成代（R2 原样） |

## 4. 测试清单（先失败后实现）

1. chain：守恒 blocking 的 fr 产物 → 三阶段跑完记 `partial`、载荷
   `conservation_blocked`+`partial_export`+`pending_marked_rows`。
2. 首代包：xlsx 以注册名落根、marker `incomplete`、`last_attempt=partial`、
   envelope exit 2 `requested_stage_partial`。
3. R2 钉：已有 completed 代时 partial 重跑**不**覆盖根交付物。
4. 行标记：binding 点名的 FRE 行说明列带「⚠待核（绑定失配）」；干净行无标记；
   `draft:true` 全文无。
5. 复用钉：partial 的 analysis/template-write 不被 `stage_is_reusable` 放行。
6. `functional_direct_basis` 在未闭合产物上仍返回 None（Claim 路径零变化）。
7. 开关：`RATOMIZER_PARTIAL_EXPORT=0` 时行为与今日逐字节一致（闸整段拦）。
8. UI：`partial_export` 载荷渲染「成文已出（N 条待核）」（vitest）。

## 5. 版本面汇总

`template_writer v2→v3`；新 `conservation-partial-export-v1`（registry + chain
producer）；分析阶段血统经该常量区分闭合/未闭合基线。守恒模型**不 bump**
（判定语义零改动）。golden 零漂移（B 轨分析与成文不在 atomize 钉内）。

## 6. 决策记录

CLAUDE.md 新条目：明示这是对 2026-08-19「守恒拦分析/成文」产品决定的政策反转
（用户 2026-08-31 拍板），理由（多数条款已对、整份扣下惩罚做对的部分）、
分层语义表引用、回滚通道 `RATOMIZER_PARTIAL_EXPORT=0`。

## 7. 刻意不做

路由 v9、大纲 flag 对照腿、门禁重跑、默认开分析富化、翻 EXECUTION_POLICY、
b 类降级（单独立项，届时守恒小版本 bump——语义改动必须 bump，不因「小」豁免）。
