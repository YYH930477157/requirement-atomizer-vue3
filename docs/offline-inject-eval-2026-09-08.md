# 离线注入评估（2026-09-08c）——无 DeepSeek：助理模型注入抽取；守恒 v9 全绿；暴露 WS0 真值集语言断层（P1 新发现）

> 用户裁定「你直接解析吧，不用 deepseek了」。DeepSeek 余额耗尽（402）后，改用
> 仓库既有 chat 注入通道：47 个条款包提示词（100 节口径，与限量冒烟完全同参）
> 由助理模型逐包产出，回放 `run_functional_extract`。**血统诚实**：解析 route=mixed
> （injected），产物带真实注入标记；本评估**不是 WS0 门禁 PASS/FAIL，不是 Go/No-Go
> 依据**。工件：`out/inject/`（prompts/responses/replay.py，git-ignored）、
> `out/inject-workdir/`、真值指标 `out/inject/truth_metrics.json`。

## 结果

| 层 | 结果 |
|---|---|
| B 轨直抽 | 47 条款 → 47 FRE（28 实质注入 + 19 纯表格标记条款诚实空响应→stub 占位）；route=mixed、exec=partial（标记条款语义，如实标 extract_degraded） |
| **守恒 v9** | **全绿**（binding/duplicates/obligation/evidence/preservation 五检查 0 失败；gap_rows=0）——早间冒烟的 2 条否定词丢失 + 单条款 stub 回退全部消除 |
| 下游确定性链 | 分析 47 行 → 成文 47 行（英文节题不中公司词表→「其他需求(新增)」，09-01d 已知映射行为）→「守恒待核」sheet 19 行 extract_degraded 红字 → 澄清 NEEDS WORK 2 问 |
| 门禁读取器 | OK：47 产出行、剥离 2046 模板行、守恒待核 sheet 在场 |

抽取质量迭代（门禁作为质量仪器的实证）：首轮 4 条 preservation blocking（key2 意译丢
字面 "no"；key11 把 Irregularity 10/11/13/14 与 "without" 压缩掉；key18 丢引用号
"[18]"）→ 修正响应两轮 → 全绿。**②结论成立：preservation 否定词/数字丢失是抽取
质量问题，忠实抽取即消；「2 20 Control of」病理条款族可被完整抽取，重复 section_id
不阻塞守恒。**

## P1 新发现：WS0 真值集与产物语言断层（门禁基础设施缺口）

真值评估 **TP=0（190 真值 × 47 产出，P=R=F1=0）**，归因不是抽取：

1. **语言不匹配**：真值 `expected_text` 为**中文分析文本**（Canna29 条目化 xlsx 的
   Chinese Analysis 列），而 B 轨提示词契约（⑤）强制**叙述与条款同语言（英文）**——
   token 重叠匹配器跨语言恒为 0。
2. **节域零交集**：真值节为 `3.1. CCEE`/`3.4. Memória de Massa` 等（定义/前言域，
   B 轨路由判定为 context），真值集中**不存在** Security / 2 20 Control of 节。
3. 08-17 门禁从未到达真值匹配层（A 轨 reader 别名 FAIL、B 轨守恒 FAIL 先行短路），
   故该断层从未暴露——**即使完美的全量 A/B 跑，对该真值集也会 TP≈0**。

**修复前置（真值层，非模型层）**：真值需按源条款重建成英文（或 matcher 增加跨语种
裁定的对齐层——须审核方决定），且节域须与 B 轨守恒基线对齐。此前任何 P/R 类阈值
评估无意义。

## 其他诊断

- 重复率：47 行 0.19 / 实质行 0.21 > 阈值 0.05——归因：19 条表格标记 stub 天然相似
  + 「Table N presents the objects of X」表格引导句族的形态同构。0.05 阈值对表格
  引导句密集语料是否合适，须随真值重建一并裁定。
- A 轨未跑（legacy 诊断轨；本评估聚焦 B 轨产品面）。

## 下一步

1. 真值集重建（英文、节域对齐 B 轨基线）——审核方裁定口径后 `tools/truth_from_review.py`
   可改造复用；
2. 真值就绪后：全量 343 节正式门禁（DeepSeek 充值 + `--warm-a-cache out/ws0-warm-a-100`
   暖启动，命令见 handover §2③）；
3. 表格标记条款（19 条）的 extract_degraded 形态：任务 D 框架内裁定是否归并入
   表格引导句族需求或维持占位（routing_gaps 已按块锚接好升级通道）。
