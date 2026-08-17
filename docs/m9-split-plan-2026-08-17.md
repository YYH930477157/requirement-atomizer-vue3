# M9 大文件拆分蓝图（机械执行计划）

**日期：** 2026-08-17（数据实测：AST 顶层符号扫描 + tests/ 全量 `patch.object`/`patch("mod.sym")` 目标统计）
**目的：** 让 §25 M9 的"大型文件拆分"成为可按步执行的机械工作，而不是临场判断。
**红线（全文最 important 的一条）：** 本仓库测试大量使用 `mock.patch.object(<模块>, "<符号>")`——
**被 patch 的符号如果移走，留在原模块的调用路径不会经过 patch**（测试静默失去保真）。
因此拆分的硬约束是：*patch 目标符号要么留在原模块，要么原模块内所有调用点改为经
原模块命名空间引用（`from x import y` 后调用 `<原模块>.y` 或保持本地名但禁止
被移动代码内部直连）*。每个候选文件的 patch 目标清单见下。

## 候选与实测数据（2026-08-17 工作树）

| 文件 | 行数 | 顶层函数 | patch 目标数 | 建议顺序 |
|---|---:|---:|---:|---|
| doc_annotation_export.py | 5473 | 90 | **4** | **第 1 刀**（目标最少且全在翻译子系统边缘） |
| api_server.py | 3448 | 53 | 20 | 第 2 刀（端点 mixin 化） |
| desktop_tasks.py | 3944 | 92 | **32** | 第 3 刀（目标最多，按任务族拆 + 全量 patch 路由审计） |
| ai_extract.py | 4836 | 120 | 25 | 第 4 刀（最难：120 函数交织） |
| claim_review_actions.py | 3240 | 62 | 7 | 第 5 刀（语义最重，最后动） |
| ui/src/App.vue | 6210 | — | — | 独立前端会话（SFC 模板/脚本耦合，vitest 277 兜底） |

## 第 1 刀：doc_annotation_export → annotation_translations（翻译子系统）

**patch 目标（全部 4 个）**：`ANNOTATION_TRANSLATION_GUARDS_VERSION`、
`_read_translation_sidecar`、`export_annotation_bundle`、`generate_annotation_translations`。
前两个是**读侧引用**（重导出即可满足）；后两个是**入口**（留在原模块）。
→ patch 风险最低的恰好是最大的子系统（~800 行）。

**移动集（逐字搬运，不改逻辑）**：
- 常量：`_TRANSLATION_BATCH`、`ANNOTATION_TRANSLATION_STRATEGY_VERSION(_OPTIMIZED)`、
  `TRANSLATION_BATCH_PROMPT_VERSION`、`_TRANSLATION_BATCH_MAX_CHARS_DEFAULT`、
  `_TRANSLATION_SPLIT_ROUNDS`、`_TRANSLATION_SIDECAR_VERSION`、`_TRANSLATION_JOURNAL_*`、
  `_TRANSLATION_REPLACE_*`、`_TRANSLATION_LOCK_*`、`_TRANSLATION_PROCESS_LOCKS(+GUARD)`；
- 护栏：`_DIGIT_GROUP_RE`、`_PAREN_ENUM_MARKER_RE`、`_TRANSLATION_ENUM_MARKER_RE`、
  `_norm_int_text`、`_fabricated_translation_tokens`、`_translation_drift`、
  `_translation_guard_source`、`_translation_entry_is_reusable`；
- IO：journal 三件（read/nonempty/truncate）、`_read_translation_sidecar`、
  `_merge_translation_update`、`_write_translation_sidecar`、
  `_translation_process_lock_for`、`_translation_sidecar_lock`；
- 批次：`_translate_batch_count/max_chars`、`_active_translation_strategy_version`、
  批次打包与 `_translate_marker_*` 家族；
- 编排：`generate_annotation_translations`、`_adopt_full_sidecar_translations`、
  `_resolve_export_translation_mode`。

**共享可变态（留在原模块、新模块写穿）**：`_active_translations`、
`_active_translation_notes`、`_collected_marker_texts`——渲染侧（HTML 嵌入）与
翻译侧共用。方案：这三个容器**留在 doc_annotation_export**，annotation_translations
通过参数/回调写穿（或反向：移到新模块，原模块 from-import——dict 引用共享，
但赋值型重置必须经新模块函数）。**推荐后者 + 提供 `reset_translation_state()`**。
- 外部依赖：`api_server.translation_key`（新模块顶层 import，无环——api_server
  对 doc_annotation_export 是惰性导入）。

**验证**：`tests/test_doc_annotation_export.py`（158）+ `tests/test_translation_mode.py`（7）
+ `tests/test_api_server.py` 全绿后跑全量。

## 第 2-5 刀（要点）

- **api_server**：按 GET/POST 端点族抽 handler mixin（`RequirementAPIHandler` 组合
  `ClaimEndpointsMixin`/`AiEndpointsMixin`/...）。patch 目标 20 个多为模块级 helper——
  helper 移动时必须保持 `api_server.X` 可 patch 且 handler 调用经 `api_server.X`。
- **desktop_tasks**：32 个 patch 目标 = 任务函数本身（`ai_extract_task` 等）。拆分
  按 CHAIN_ORDER 任务族分模块后，原模块 `from .tasks_x import *` 重导出，且
  chain_task 的 runners 字典引用**原模块命名空间**符号。
- **ai_extract**：最后。建议先做纯"常量+prompt 文本"抽取（低风险），函数族
  （extract/guards/publish）每移一个跑一次 3898 全量。
- **claim_review_actions**：语义最重（effective ledger 权威），只在其余全部稳定后动。

## 每一刀的完成条件（方案 §25 M9）

不改变已验收执行语义；独立通过全量（当前基线：3929 项 / 4 项既有 golden 漂移）
+ 前端不动时无需 npm；每刀独立提交，可单独回滚。
