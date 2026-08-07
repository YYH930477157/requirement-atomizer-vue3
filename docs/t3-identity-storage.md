# T3 — 身份与存储地基（S5）

> 切片 `codex/t3-identity-storage`，基于 `codex/t2-orchestrator`。重构结论 §2.5。
> 四项交付：稳定需求身份层 + RTM 边、CAS 分桶、存储抽象收口 + lint、retriever 插件点预研。

## T3-1 稳定需求身份层 + RTM 边持久化

### 稳定 ID（`functional_extract.py`）

- **新增 `requirement_uid`**：跨再生成稳定，按**条款序号**定位（`FR-0001`、`FR-0002`…；同条款多条
  后缀 `.2`/`.3`，按别名 id 稳定排序）。条款序号取自确定性 `sections` 列表顺序（parser 决定，
  不依赖 LLM 输出顺序/数量或叙述内容）。
- **旧 `functional_requirement_id` 保留为别名映射字段，不做原地替换**（下游主键不变）。
- **迁移口径**：`requirement_uid` 是**新增字段**。旧产物（无此字段）仍可读、仍以
  `functional_requirement_id` 为身份键；新一次 functional_extract 运行即补盖 uid。
  `review_state.requirement_identity_keys` 已纳入 `requirement_uid`，RTM 边/生命周期事件可用它寻址。
- **稳定性证明**（`tests/test_functional_extract.py::StableUidTests`）：再生成改叙述 + 交换 LLM
  输出顺序后，同一条款的 `requirement_uid` 不变（旧 id 因含 output index 会漂移）。

### RTM 边（`review_state.py` + `requirements_analysis_rules.py`）

- **append-only 事件流** `requirement_rtm_edges.jsonl`（schema `requirement-rtm-edge/v1`），与
  `append_lifecycle_event` 同锁（`verification_state_lock`）同流纪律。每条边事件带
  `edge_id/kind/from/to/decision/actor/reason/recorded_at`。
- **accept 落边**：物化进既有 `dependency_decisions.jsonl`（下游消费不变）**且**追加 accept 事件。
  **reject 留记录**：只追加 reject 事件（旧实现「拒绝不落库=无声消失」→ 现留痕可回放）。
- **`replay_rtm_edges`** 确定性回放：同一 edge 的 accept→reject→accept 取末尾决策（最后决策胜出），
  两次回放逐字节一致。`GET /rtm-edges` 返回回放后的当前边态。
- `recommend_dependencies_task` 候选状态改为读事件流回放：`accepted`/`rejected`/`pending`。

## T3-2 CAS 分桶（`requirement_schema.py` + `requirements_analysis_rules.py` + `desktop_tasks.py` + `api_server.py`）

- 旧 verification CAS 绑**整条内容指纹**（含 description 等叙述字段）——叙述抖动吊销全部确认。
- **结构指纹** `requirement_structural_fingerprint`（OBIS/编码 + 归属 + 模块 + 来源章节 + 来源 block_ids）
  漂移 → **吊销确认**（`VerificationStateConflict`）。
- **叙述指纹** `requirement_narrative_fingerprint`（objective/behaviors/description/title/…）漂移 →
  **不吊销**，置 `narrative_drift_hint=True` 复核提示。`evidence_fingerprint` 改为结构指纹（客户端
  round-trip 它；GET 端点经索引重绑，避免旧记录残留组合指纹造成首次保存假 409）。
- 回灌（xlsx backfill）闸只比对**结构列**（子模块 + 客户需求章节），描述（叙述）降级为
  `narrative_review` 清单——状态仍回灌，仅提示复核。
- 旧 `requirement_content_fingerprint` 保留为组合指纹（向后兼容），不再是 CAS 闸。
- **两路证明**（`tests/test_ws4_capabilities.py`）：叙述漂移→确认保留 + hint；结构漂移→吊销。

## T3-3 存储抽象收口 + lint（`artifact_store.py`）

- **`ArtifactStore` 门面**：governed 寻址（委托 `governed_artifact_path`）+ 跨进程锁（`process_file_lock`
  + 进程内 RLock）+ JSONL/JSON 原子读写 + append-only。**既有实现不动**——门面给新代码，逐步迁移
  指南见模块 docstring（一次一个文件、每步产物字节不变）。
- **契约 lint** `scan_bare_artifact_joins`（AST 扫 `BinOp(Div, right=Constant("*.jsonl|.lock"))`）+
  `tests/test_artifact_store.py` 冻结现存 (file, filename) 多集为白名单：**新裸拼即失败**，提示走
  `ArtifactStore`/`governed_artifact_path`。把「寻址靠纪律」升级为「寻址靠门禁」（B1 类错误治本）。

## T3-4 retriever 插件点预研（`requirement_schema.py` + `desktop_tasks.py` + `config.py`）

- **`RequirementRetriever` Protocol**（`search(query, limit) -> entries`）+ 默认词面实现
  `LiteralRequirementRetriever`（包装既有 `search_requirement_library`，零向量零 LLM）。
- `build_requirement_retriever(retriever=...)` 支持注入（测试/外部向量插件）；`search_requirements_task`
  消费它。`RATOMIZER_REQUIREMENT_RETRIEVER=vector` 预留可关开关——**当前无向量依赖**，选 vector
  如实回退词面并标 `retriever_kind`，绝不伪造向量召回。
- 任何 retriever 产出仍是同一 entry 形态，**下游确定性校验不放松**（信任前提不动）。

## 验收门禁

- 新增测试全绿；全量回归无新增失败（日志 `/tmp`）。
- 未改 `golden_sets/`、冻结 `out/`、LLM prompt；未 commit、未 push。
