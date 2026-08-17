# 03 CLI 使用指南

CLI 入口为 `ratomizer`（`cli.py`），机器契约详见 `docs/cli-contract.md`：
退出码 `0/2/3/4`，stdout 为 UTF-8 JSON 信封。

## 全链运行（最常用）

```powershell
ratomizer run ".\samples\your-standard.docx" `
  --out ".\out\run-001" `
  --kb ".\knowledge_bases\compiled_from_obsidian.json" `
  --export md,csv
```

可选参数：`--domain-pack DIR`、`--chunk-chars N`、`--skip-review`、
`--llm-route stub|openai_compatible`（默认 stub）、`--review-scope targeted|all`、
`--quiet | --verbose`。

## 桌面任务桥（chain 编排）

桌面端与脚本化全链走 `desktop_tasks`：

```powershell
python -m desktop_tasks chain --out ".\out\run-001" --stages ai-extract,requirements-analysis,template-write
```

可用阶段（`CHAIN_ORDER`）：

```text
ai-extract, functional-extract, functional-synthesis, assemble,
requirements-analysis, template-write, clarification-report,
full-translation, compose, export-annotation-html
```

> 功能直抽默认开启时，chain 内的 `ai-extract` + `functional-synthesis`
> 会被整体替换为 `functional-extract`（替换由 chain 单点完成并落账）。

## 分步命令

```powershell
ratomizer atomize <input> --out DIR [--kb FILE]... [--domain-pack DIR]   # 仅原子化
ratomizer review --out DIR [--llm-route stub|openai_compatible]          # 仅审查
ratomizer export --out DIR --format md|csv [--status all|accepted|...]   # 导出
ratomizer compose --out DIR                                              # 装配工程需求
ratomizer analyze --out DIR [--template FILE.xlsx] [--llm-route ...]     # 需求分析
```

`compose` 会写出 `engineering_requirements/`：

- `requirement_functions.md`：按领域分组的可实现需求函数（含确定性验收准则）
- `dlms_objects.md`：DLMS/COSEM 对象（OBIS、接口类、属性、访问权限、可追溯性）

## 需求分析（analyze）

在 AI 抽取与专家裁决之后，把相关原子条目归一为功能需求再分析：

```powershell
python -m desktop_tasks functional-synthesis --out ".\out\run-001"
ratomizer analyze --out ".\out\run-001" --llm-route stub
```

或直接走桌面任务桥：

```powershell
python -m desktop_tasks requirements-analysis --out ".\out\run-001" --llm-route stub
```

要点：

- `--llm-route` 只接受 `stub` 与 `openai_compatible`，默认 `stub`
- `stub` 可以分析已有的 AI 抽取产物，但不会在全新运行里创建 AI 行为需求
- 归属分类、模块映射、评审决定永远走确定性路径；`openai_compatible` 只富化叙述字段
- 模型编造源文中不存在的编码/数字时，条目会被拒绝回退确定性路径并记录 issue

分析产物（写入输出目录）：

```text
engineering_analysis.json
hardware_items.md
co_design_items.md
software_requirements.xlsx
```

## 本地评审 API

```powershell
python .\api_server.py --out ".\out\run-001" --port 8770
```

或一键启动（API + 评审 UI）：

```powershell
.\desktop\start-review-app.ps1 -OutputDir ".\out\run-001" -Port 8770
```

## 结果包生命周期

新桌面运行会写 `result-package.json` 标记（`ratomizer-result-package/v1`，
布局 `result-layout-v1`），根目录只保留注册发布的人类交付物，
其余状态/缓存/日志/阶段产物都在 `.ratomizer/{pipeline,state,cache,logs,stages}`。

```powershell
python -m desktop_tasks result-package-start    --out DIR --input FILE --stages a,b,c
python -m desktop_tasks result-package-complete --out DIR --run-id RUN-ID --completed-stages a,b,c
python -m desktop_tasks result-package-fail     --out DIR --run-id RUN-ID --error MESSAGE
python -m desktop_tasks result-package-status   --out DIR [--verify]
```

`--verify` 会重算所有交付物与完成证据的 SHA-256 与标记比对，
不一致时报 `result_package_modified`（“结果文件已被修改”，退出码 3）。

## 语义质量门禁

```powershell
python -m semantic_quality
```

覆盖合并/拆分行为、生命周期角色、跨模块归并、归属、受保护 OBIS/profile 值、
来源映射、规范/设计分栏、exactly-once 来源分配与已知真实文档误合并防护。
