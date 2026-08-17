# ADR：效果优先的单元级自动路由（quality-first unit routing）

**日期：** 2026-08-17
**状态：** 已实施（shadow/机械层；默认执行策略仍 legacy_combined）
**方案：** `docs/quality-first-unit-routing-complete-plan-2026-08-16.md`

## 背景

M0 实测（`docs/m0-baseline-abnt-summary-2026-08-17.md`）证明方案 §3 的判断：
当前默认链对 ABNT 混合文档做文档级 2 调用/235,798 tokens 的整文档直抽且守恒
确定性失败；全文翻译占冷成本 82.6%；失败产物不缓存导致复跑重付。同时 M2 shadow
统计（`docs/unit-routing-shadow-abnt-2026-08-17.md`）显示同一文档 53.5% 单元是
可确定性 join 的 COSEM 结构内容、仅 2.1% 真需 B 轨付费——"无消费者付费工作"
是主要浪费。

## 决策

1. **单元单一事实源**：`extraction_units.py` 从解析产物确定性构建 A/B 共用单元；
   A/B 各自切分被禁止（span/缓存键/守恒不分叉）。每个非空 canonical cell 恰好
   归属一个单元（硬校验）。
2. **路由零 LLM**：`unit_router.py` 硬/弱两级信号（A=白名单 class/OBIS/COSEM
   语境；B=义务模态权威表）；弱信号→review 物化，永不静默丢弃；定义/引用/标题
   恒 context（引用内嵌 shall 归被引条款，防双抽）。
3. **局部升级复用 claim 队列**：`routing_escalation.py` 只匹配已发布 pending
   proposal 走 `execute_claim_queue_proposal`（CAS/WAL/预算/幂等全复用）；
   无匹配如实 no_matching_proposal——**绝不伪造 claim 锚**（§19：不造第八条
   重抽通道）。
4. **付费缓存 successful-only**：`PaidCacheStore` 统一锁/fsync/原子/Windows 退避/
   撕裂恢复；消费者（spec_enrich、ai_extract）逐个迁移，读侧双格式兼容旧缓存。
5. **调用机械统一**：`llm_job_runner.py`（route/identity/缓存/预算/retry 分类/
   usage/attempt ledger `llm_job_attempts.jsonl` 带 stage/processor/unit_id）；
   `llm_client.call_context` 把归属同源写进 llm_trace。tool-loop 暂不纳入。
6. **翻译是交付选项不是技术轨道**：off=零调用（计数 chat 证明）、markers=现状、
   full=sidecar 确定性采纳优先；UI 只呈现业务选择，A/B 开关收进高级区（§20）。
7. **完成以质量证据为准**：结果包完成评估 `quality_gates`（按本次运行阶段收
   作用域；needs_work 拒绝完成；gate 快照入完成证据；needs_review 记录不阻塞，
   blocking 语义留在各自权威）。
8. **默认不翻**：`RATOMIZER_EXECUTION_POLICY` 默认 legacy_combined。翻转前置 =
   WS0 人工真值集 + ab_runner 门禁（§31 红线；"无真值不翻默认"也在方案非目标）。

## 后果

- 全部落地件为零默认行为变化（除显式 opt-in），legacy 路径完整保留可回滚；
- golden `out/` 再生成按既有流程在合并时执行（本分支既有 4 项漂移与本工作无关，
  stash 双向验证）；
- 未完成：大文件拆分（M9 其余项）、quality_first 主执行接线（等 WS0 真值
  门禁）。消费者迁移已全部完成（doc_map / spec_enrich / spot_extract）。
