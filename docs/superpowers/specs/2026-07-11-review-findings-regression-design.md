# 0711 Code Review Follow-up Design

## Goal

修复 `e910547..944e9d9` 代码审查确认的九项问题，并用自动化回归锁定数据保真、软件/硬件归属、阶段复用、出处追踪和 UI 状态。

## Chosen Approach

采用局部、版本化修复：保持现有 JSON/XLSX/CLI 字段兼容，在问题所属模块内补齐行为，并通过新的 producer 版本让旧产物自然失效。

没有采用以下替代方案：

- 全面重写阶段缓存协议：长期方向更统一，但超出本轮缺陷范围，迁移风险较高。
- 暂时关闭缓存/复用：能绕开陈旧产物，但会显著增加真实 LLM 调用时间和成本。
- 只增加日志告警：不能阻止 PDF 内容丢失、错误归属和错误复用，不满足修复目标。

## Design

### 1. Trace and provenance

- `llm_client._truncate_for_trace` 对 list/dict 递归遍历，所有超过上限的字符串都截断；结构化键和值形状保持不变。
- `spec_enrich` 将 `blue_book_origin` 写入缓存行，缓存命中时恢复该结构化字段。
- 回归使用真实 OpenAI 兼容响应形状和两次富化调用，不只测试扁平值。

### 2. PDF cell preservation

- `_validate_text_table` 删除稀疏列前，将其中非空文本并入最近的保留列。
- 列清理仍保留原有反伪表守卫，但任何已识别单元格文本都不得因稀疏列删除而消失。
- 回归覆盖生产检测链或至少覆盖“组装 + 校验”完整链，验证偏移 OBIS 在最终矩阵中存在。

### 3. Stage reuse and route truthfulness

- 阶段 producer 与 prompt 版本解耦；本轮影响输出的 `atomize`、`ai-extract`、`assemble`、`functional-synthesis`、`requirements-analysis`、`template-write`、`clarification-report` 使用新的 producer 版本。
- `clarification-report` 的输入指纹加入 `functional_requirements.json`。
- requirements analysis 在富化结束后决定实际 route：至少一条 LLM 富化被采纳才报告 `openai_compatible`；零采纳时报告 `stub`，并保留 requested route 和降级计数。
- 部分成功仍报告 `openai_compatible`，由 `enriched`/`enrich_degraded` 表达混合结果，避免引入新 route 枚举。

### 4. Ownership and template mapping

- CJK 短词只在局部硬件名词上下文且没有软件动作信号时视为假朋友；不同字段或远处硬件词不得压制软件命中。
- 公司模板中有意落入“其他需求(新增)”的模块显式映射到 fallback sheet，使漂移检查只报告意外漂移。
- 漂移测试断言当前无意外 unmapped/extra，而非只检查返回类型。

### 5. UI stage state

- `resetRunStageBoard` 独立根据 LLM 开关设置 `functional-synthesis` 状态，不依赖 `analyze` 是否启用。
- 回归覆盖 `aiExtract=true`、`analyze=false`、LLM 关闭的组合，卡片必须显示未启用而不是待完成。

## Error Handling and Compatibility

- 不删除旧 manifest；producer 不匹配时沿用现有机制重新执行。
- trace full 模式继续原样返回，不改变离线调试能力。
- 缓存旧行没有 `blue_book_origin` 时安全降级为空；新鲜富化或新缓存会补齐。
- PDF 稀疏列文本合并使用空格连接，不覆盖同一行已有文本。
- 不修改标准模板文件、golden 基线或未跟踪的 `硬件` 文件。

## Acceptance Criteria

1. 真实嵌套 LLM 响应正文被限制在 trace cap 内。
2. 偏移 OBIS 经表格校验后仍存在。
3. 旧 producer manifest 不可复用；合成冲突变化会改变澄清阶段指纹。
4. 全部富化失败时 route 为 `stub`，部分/全部成功时 route 为 `openai_compatible`。
5. “软件从计量芯片读取时钟并同步”不再判为 hardware，原有“时钟计数器型号”仍不作为软件词命中。
6. Blue Book 缓存命中保留 `blue_book_origin`。
7. 模块映射漂移当前返回空集合，且有意 fallback 行为不变。
8. LLM 关闭时功能重组卡片不显示待完成。
9. 相关 Python 回归、全部 Python 测试、全部 UI 测试和 UI build 通过。

