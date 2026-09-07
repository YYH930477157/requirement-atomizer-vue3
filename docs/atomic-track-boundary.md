# 原子轨边界与直抽默认策略

状态：accepted（2026-09-07）

当前产品把**功能需求直抽**作为默认需求路径。输入条款按自然上下文交给
`functional-extract`，同一目标下的多个行为保留在一条功能需求中；原子化条目
不属于日常需求 KPI，也不应成为默认评审对象。`assemble`、`compose` 和逐原子
`llm-review` 不进入功能需求默认交付链，只在高级设置或显式 A 轨场景开启。

仓库中的 `atomize.py` 仍然承担两种不同职责，不能整体删除：

- 文档解析：生成 `blocks.jsonl`、`chunks.jsonl`、表格行和物理单元。这些产物由
  功能直抽、批注和证据定位继续使用。
- 旧 A 轨候选：规则生成 `atomic_requirements.jsonl` 和 `llm_tasks.jsonl`，供
  DLMS/COSEM 兼容链和历史结果读取。

两类职责后续应继续隔离。新功能不得把 `atomic_requirements.jsonl` 当作功能需求
输入，也不得把逐原子 LLM 审查重新接入默认链。功能直抽可以保留细粒度来源证据锚，
但证据锚不自动变成独立需求。`RATOMIZER_FUNCTIONAL_EXTRACT`
缺省值为 `1`；显式 `0` 只用于旧结果迁移、A 轨对照或回放。任何默认值变更都必须
先更新本文件、补边界测试，并说明对 token 成本和需求上下文的影响。

如果未来确认永久停止 DLMS/COSEM A 轨，删除顺序应为：先迁移 API、结果包和
缓存读者，再移除 A 轨命令与测试，最后删除候选生成和 schema。解析主干与物理
表格证据必须保留。一次性删除 `atomize.py` 会同时破坏解析主线，不能作为普通
代码清理执行。

## 执行边界（2026-09-07）

- 桌面 `run` 接受 `--track functional|legacy_a`。当前 UI 总是显式传入：日常运行
  为 `functional`，勾选逐原子审查、旧装配或旧组装时为 `legacy_a`。单独勾选装配
  即可生成所需候选，不必开启逐原子审查；测试运行仅按实际执行的阶段选择。
- `functional` 必须同时跳过逐原子审查（`--skip-review`）；冲突参数在解析前报错。
  未传 track 的旧桌面桥接/脚本保留原来的环境开关与 skip-review 兼容选择。
  独立 `ratomizer run` CLI 默认走完整需求（functional）轨道；需要旧原子兼容行为时，
  使用 `--track legacy_a`。`ratomizer atomize` 仍是显式的解析加原子候选入口。
- `manifest.json.track` 标记解析结果类型，pipeline/chain 响应同样返回 track。
  `GET /pipeline-track` 提供结果包或旧目录的只读契约：功能需求接口为
  `/functional-requirements`，`/requirements` 保持旧原子诊断列表协议。
  无 track 的历史结果返回 `unknown` / `undeclared`，不猜测或写回其来源。
- functional 结果禁止 `llm-review`、`assemble`、`compose` 以及直接调用旧
  `ai-extract` / `functional-synthesis`。默认 chain 先将旧 B 轨阶段名转换为
  `functional-extract`，再检查边界；环境开关显式关掉转换时不能绕过结果类型。
  chain 在执行任何阶段前检查，底层入口也检查，防止单命令绕过。
- 解析缓存按流程模式区分。纯文字文档可以产生空表格 JSONL；仅当 manifest
  对应计数明确为 0 时允许复用空表文件，文件缺失仍须重跑。旧 A 轨切回功能
  流程时继续清除旧原子候选和任务文件。

验收使用合成 DOCX、stub/mock 与 HTTP 本地服务，覆盖流程切换、重复运行、
缺失文件、旧阶段拦截、旧目录和结果包寻址。它证明流程边界，不代表真实语料
的需求抽取质量或 token 节省比例；后者仍需真实文档评测。
