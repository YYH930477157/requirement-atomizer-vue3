# T4 / S3 全开关影子运行 —— 工具链与合成演示报告

> 切片 `codex/t4-shadow-run`，基于 `codex/t3-identity-storage`。重构结论 §2.3（影子运行）。
> 工具：`tools/shadow_run.py`；测试：`tests/test_shadow_run.py`。

## ⚠️ 真实语料状态

**真实金标 ABNT / 未见过的文档本机没有，真实语料影子跑批 pending-human。** 本报告基于
**合成 docx fixture**（`tests/docx_fixtures.py` 脚本生成）自证**机制**——工具链就绪、归因
分类器闭合、HARD 门可裁决。它**不是**真实语料的查全/查准/角色准确率证据，工具也**不伪造**
任何真实语料对比结论。真实语料产物对就绪后，用 ``--baseline-roots OLD NEW`` 离线套用即可。

## 这是什么

把"首次全开关实跑"从用户现场前移到开发侧，拆解库存代码的集成爆雷风险：对同一文档跑

- **旧路径** —— 四个新开关全 OFF（``RATOMIZER_TABLE_DUAL_TRACK`` / ``RATOMIZER_FUNCTIONAL_EXTRACT``
  / ``RATOMIZER_LLM_BUDGET`` / ``RATOMIZER_CLAIM_LEDGER_MODE`` 回默认）= 生产当前确定性原子化路径；
- **新路径** —— 四开关全 ON（双轨 / 直抽 / 抽检 / 预算）。

并排对比产物，逐条差异归因（``expected_difference`` / ``defect`` / ``unexplained``）；三道 HARD 门
任一失败即 ``exit 2`` 停线。

## 三道 HARD 门（任一失败 → exit 2 停线）

| 门 | 含义 | 实现 |
|---|---|---|
| `protected_encoding_zero_drift` | 受保护编码（OBIS / 事件号 / hex）在新路径确定性核里**零丢失**（"OBIS 错一位即严重缺陷"） | `cosem_behavior_spec.extract_codes` 同源口径，扫五件确定性核产物的编码并集 |
| `conservation_closed` | 功能需求级守恒（exactly-once 覆盖条款集合）；**仅权威 route 产物**未闭合才红灯 | 读 `functional_requirements.json` 的 `conservation` 块；stub/degraded 未闭合=预期降级 |
| `deterministic_core_byte_stable` | **CAS**：开关翻动不污染确定性核——`blocks` / `atomic_requirements` / `chunks` / `table_items` / `table_cell_items` 五件产物新旧逐字节一致 | 逐文件 sha256 比对（manifest 剥离 `generated_at`/`output_dir` 运行身份字段） |

退出码对齐 `docs/cli-contract.md`：**0** 达标 / **2** HARD 门失败或输入错误 / **3** 校验或报告写错误 /
**4** 环境错误。stdout 为 UTF-8 JSON 信封；`--report` 写 JSON、`--human` 写人读 Markdown。

## 两种调用模式

```bash
# live 模式：合成文档自证（跑两条路径，产物写 <work-dir>/old 与 /new）
python tools/shadow_run.py --input synthetic.docx --work-dir /tmp/shadow \
    --report /tmp/shadow/report.json --human /tmp/shadow/report.md

# 离线模式：复跑既有产物对（不重跑流水线）——真实语料 / 真实 LLM 产物对就绪后直接套用
python tools/shadow_run.py --baseline-roots /path/old_run /path/new_run --real-corpus \
    --report report.json
```

`--llm-route openai_compatible` 时双轨提议器才会真正挂载（与 `desktop_tasks` 同源）；默认 `stub`
时双轨诚实降级（不写假设文件，归因为 `expected_degradation_no_llm`）——这正是"无 LLM 时开关
是否优雅降级"的集成信号。

## 归因模板

| 模板 | 触发 | 归因 |
|---|---|---|
| `direct_extract_granularity` | 直抽开关 ON：`functional_requirements.json` 新增/重生成 | expected |
| `dual_track_header_judgment` | 双轨签发假设 → `table_structure_hypotheses.jsonl` 差异 / header 判定差异 | expected |
| `sampling_verifier_coverage` | 抽检模式：`claim_sampling_summary.json` 差异（未抽中 claim 延迟到发布门禁） | expected |
| `budget_cost_report` | 预算单开关 ON：`cost_report.json` 产物差异 | expected |
| `expected_preserved` | 确定性核五件产物新旧逐字节一致（**正向 CAS 证据**，非缺陷） | expected |
| `expected_degradation_no_llm` | 开关 ON 但无 LLM → 诚实降级（无假设 / 无 cost） | expected |
| *(none)* | 确定性核字节漂移 / 意外产物 / 核心产物消失 | **defect / unexplained** |

## 合成演示结果（实测）

两份合成 fixture 由 `tests/docx_fixtures.py` 生成（脚本生成、明确 fixture 身份、非真实语料）：

| fixture | 大小 | sha256 | 受保护编码 | 差异数 | 归因分布 | 模板分布 | HARD 门 | exit |
|---|---|---|---|---|---|---|---|---|
| `synthetic_rich.docx` | 37227 | `15380391…1dd06` | old=2 new=2 lost=[] | 2 | expected=7 defect=0 unexplained=0 | expected_preserved×5 + direct_extract_granularity×1 + expected_degradation_no_llm×1 | 全 pass | **0** |
| `minimal.docx` | 36827 | `7ff78a79…df6f9` | old=0 new=0 lost=[] | 2 | expected=7 defect=0 unexplained=0 | expected_preserved×5 + direct_extract_granularity×1 + expected_degradation_no_llm×1 | 全 pass | **0** |

`synthetic_rich.docx` 含 OBIS `0-0:1.0.0.255` 与事件码 `G1-SG10-E1`（受保护编码）；`minimal.docx`
无受保护编码（如实 old=0）。两份 demo 的**全部差异都落入预期归因**，**defect / unexplained = 0**。

差异清单（两份一致；"差异数"只计非 unchanged 的两条）：

- `functional_requirements.json`（**added**）→ `expected_difference` / `direct_extract_granularity`
  —— 直抽开关 ON：`functional_extract` 侧车新增 `functional_requirements.json`。
- `(switch:RATOMIZER_TABLE_DUAL_TRACK)`（**degraded**）→ `expected_difference` /
  `expected_degradation_no_llm` —— 双轨开关 ON 但 stub 路由无提议器，atomize 诚实降级走确定性
  `analyze_table`，未签发 `table_structure_hypotheses.jsonl`（真实 route 下此条消失）。
- `blocks.jsonl` / `atomic_requirements.jsonl` / `chunks.jsonl` / `table_items.jsonl` /
  `table_cell_items.jsonl`（**unchanged**）→ `expected_difference` / `expected_preserved`
  —— 确定性核新旧逐字节一致（CAS 身份稳定）。

### 复现命令

```bash
python -m unittest tests.test_shadow_run          # 25 项全绿（含三道 HARD 门注入回归）
python tools/shadow_run.py --input <合成docx> --work-dir /tmp/shadow --human /tmp/shadow/r.md
```

## 缺陷回归钩子（T4-3）

`tests/test_shadow_run.py::HardGateInjectionTests` 把三道 HARD 门的"注入失败"各自钉成回归测试，
任一即 exit 2 停线（不带病前进）：

- `test_protected_encoding_drift_stops_line` —— 从新路径 `atomic_requirements.jsonl` 抹掉仅在它
  出现的事件码 `G1-SG10-E1` → `protected_encoding_zero_drift=fail` / exit 2 / `codes_lost=["G1-SG10-E1"]`。
- `test_authoritative_conservation_not_closed_stops_line` —— 把 stub 产物改标权威 route
  （`openai_compatible`）再破坏守恒 → `conservation_closed=fail` / exit 2（stub 未闭合是预期降级，
  真实 route 未闭合才是红灯，此测试守住这条边界）。
- `test_deterministic_core_byte_drift_stops_line` —— 给新路径 `blocks.jsonl` 追加一字节 →
  `deterministic_core_byte_stable=fail` / exit 2。
- `test_core_product_removed_is_defect` —— 确定性核产物在新路径消失 → `defect` / exit 2。

## 真实语料 pending 的确切前置条件

要在外部把真实语料影子跑批从 pending 推进到 done，需依次就绪：

1. **S2 微型真值集落地**（`golden_sets/gold_functional_v1/truth.jsonl` 由 pending_annotation →
   annotated）：至少 1 份 ABNT 家族文档、100–200 条功能需求级人工标注（双专家独立标注→仲裁→冻结）。
2. **真实 LLM 路由**（`RATOMIZER_LLM_API_KEY` + openai_compatible 端点）：双轨提议器 / 直抽 / 抽检
   verifier / 预算单才真正激活（非降级）。
3. **两份真实产物对**：同文档跑两次 atomize（旧/新开关），产物目录拷到本机或可访问路径。
4. 套用：``python tools/shadow_run.py --baseline-roots <old_run> <new_run> --real-corpus --report r.json``。

工具会按与合成 demo **完全相同**的对比/归因/HARD 门逻辑产出报告——只是这次差异里会出现
`dual_track_header_judgment` / `sampling_verifier_coverage` / `budget_cost_report` 等真实开关
激活的预期差异，以及（若有）需要人工的 `unexplained`。

## 设计取舍与诚实限制

- **live 模式跑确定性核 + 直抽侧车**（LLM-free 或 stub），不跑全链 ai_extract/review/analyze。
  双轨提议器 / claim verifier / 预算扣款在 stub 模式诚实降级——这正是"开关无 LLM 是否优雅降级"
  的集成信号，归因为 `expected_degradation_no_llm`，不冒充已激活。
- **CAS 门 = 确定性核字节稳定**（而非逐条 requirement 结构指纹比对）：对影子运行这是最强不变量
  ——开关只应是旁路增量，不该改动确定性核一个字节。逐条结构指纹稳定性在字节稳定时平凡成立。
- **守恒门只对权威 route 产物红灯**：stub 直抽不落地 `source_block_ids`，未闭合是预期降级（文档
  NEEDS WORK 已是真实门禁）；强行把 stub 未闭合判为 HARD 失败会把"无 LLM"误报为 defect。
- **manifest 运行身份字段**（`generated_at` / `output_dir`）从对比中剥离——同文档两次运行必然
  不同，不属内容漂移。
- **`_discover_products` 扫描根目录额外 JSONL/JSON**：捕获 `ALL_TRACKED_FILES` 之外的意外产物
  （集成爆雷信号），归 `unexplained` 供人工。
- **真实双轨 header 判定差异 / 抽检 verifier 面差异**在合成 demo（stub）中不触发——它们的分类
  路径由 `AttributionClassifierTests` 逐模板钉死，等真实 route 产物对就绪即在生产报告里出现。
