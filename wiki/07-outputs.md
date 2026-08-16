# 07 输出产物说明

## 全链运行的基础产物

`ratomizer run` 在 `--out` 目录下写入：

```text
blocks.jsonl                  # 解析后的结构化块
table_items.jsonl             # 表格行/单元格
atomic_requirements.jsonl     # 原子需求候选
llm_review_results.jsonl      # LLM 审查结果
review_states.jsonl           # 评审状态
quality_report.json           # 质量报告
manifest.json                 # 运行清单
summary.md                    # 摘要
```

## B 轨交付物

```text
ai_requirements.jsonl            # AI 抽取行契约（requirement_record）
ai_extract_quality.json          # 抽取质量信号
functional_requirements.json     # 功能需求级条目（直抽或合成产物）
engineering_analysis.json        # 需求分析结果
software_requirements.xlsx       # 软件/协同设计条目工作簿
hardware_items.md                # 硬件条目摘要
co_design_items.md               # 协同设计条目摘要
软件需求列表-成文.xlsx           # 公司模板成文交付物（V2.3.x 格式）
clarification_questions.xlsx     # 澄清问题（必答/参考分级）
```

## result-package 布局（新桌面运行）

新运行会写 `result-package.json` 标记（schema `ratomizer-result-package/v1`，
布局 `result-layout-v1`）：

```text
<out>/
├── result-package.json          # 生命周期标记（发布事务的锚点）
├── <注册发布的人类交付物>        # 根目录只保留交付物
└── .ratomizer/
    ├── pipeline/                # 流水线产物
    ├── state/                   # 评审/账本状态（review_states.jsonl 等）
    ├── cache/                   # 追加式缓存
    ├── logs/                    # 日志
    └── stages/                  # 阶段产物
```

寻址规则：所有状态/缓存/日志/阶段路径必须经过
`result_package.governed_artifact_path`（注册交付物用 `package_artifact_path`），
**不允许**对输出根目录做裸文件名拼接——`package_v1` 布局下旧式
`root / "review_states.jsonl"` 拼接会静默错址。

发布纪律：

- 尝试进行中，阶段命令只写 `.ratomizer/` 内部；根目录交付物保持上一次完成的世代
- `result-package-complete` 事务性发布；任一请求阶段降级/失败时拒绝完成提交
  （`requested_stage_partial`），上一次完成的世代逐字节保留
- `result-package-status --verify` 重算交付物 SHA-256 与标记比对，
  不一致报 `result_package_modified`（“结果文件已被修改”）

## 运行清单（run_manifest.json）

每个输出目录的 `run_manifest.json`（manifest v2）记录：阶段状态、producer 版本、
路由（route）、配置与上游文件 SHA-256 输入指纹。缺少账本或任一输入指纹变化时
不得复用缓存；stub 请求可保留已验证的 OpenAI 产物，但不能在新目录伪装完成 AI 抽取。

## 每个 JSON 产物的血统

产物带 `provenance`（`producer`/`version`/`generated_at`），消费端校验并告警；
缓存结果存储的是后护栏输出，行为版本（如 `EXTRACT_GUARDS_VERSION`、
`*_PROMPT_VERSION`）钉进缓存指纹，任何护栏/校验行为变更都必须 bump 版本号，
否则旧缓存会静默绕过新行为。
