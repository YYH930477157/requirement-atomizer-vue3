# 06 LLM 配置

## 默认行为

默认路由是本地 **stub**：不调用任何外部 API。要启用 OpenAI 兼容服务，
编辑 `llm_agents/review_pipeline.yaml`：

```yaml
model_routes:
  default: openai_compatible
```

`openai_compatible` 路由的 `base_url`/`model`/温度/超时/并发等都在同一文件配置。
也可用环境变量覆盖（优先于 yaml）。

## 关键环境变量

所有配置变量的唯一权威来源是 `config.ENV_REGISTRY`，常用项：

| 变量 | 默认 | 说明 |
|---|---|---|
| `RATOMIZER_LLM_API_KEY` | 空 | API 密钥，**只走环境变量**，配置文件只存变量名 |
| `RATOMIZER_LLM_BASE_URL` | 空 | 覆盖 yaml 的端点 base URL |
| `RATOMIZER_LLM_MODEL` | 空 | 覆盖模型名 |
| `RATOMIZER_LLM_TEMPERATURE` | 0 | 采样温度（可复现默认 0） |
| `RATOMIZER_LLM_MAX_TOKENS` | 空 | 输出上限（各环节另有用途下限） |
| `RATOMIZER_LLM_CONCURRENCY` | 8 | 抽取/富化并发度（1..16） |
| `RATOMIZER_LLM_ADAPTIVE` | 1 | 429 自适应闸门（全局冷却 + 在飞上限 AIMD） |
| `RATOMIZER_LLM_TRACE` | 1 | `llm_trace.jsonl` 消息级追踪（含文档全文，外发前注意） |
| `RATOMIZER_LLM_BUDGET` | 0 | 文档级统一预算单开关（=1 启用 `llm_budget` 预算账本） |
| `RATOMIZER_FUNCTIONAL_EXTRACT` | 1 | 功能直抽开关（=0 回滚旧原子化路径） |

> 预算开关默认关闭。启用后每份文档一份预算单：总调用数/token 上限 +
> 各环节子预算，全部 LLM 调用从同一份账本扣减，耗尽即降级 stub
> （provenance 如实记录，绝不伪装成 LLM 产物）。

## 路由降级与出处纪律

- 未设置 `RATOMIZER_LLM_API_KEY` 时，`openai_compatible` 请求降级为确定性路径，
  产物记录 `route: "stub"` 与 `route_requested` —— **出处永不伪造**
- stub 输出绝不标注为 LLM 产物；缓存/合并结果保留真实来源
- LLM 只富化叙述字段；结构化字段（OBIS/class_id/access 等）只走确定性关联，
  编造的编码/数字会被拒绝（宁漏勿错）

## 审查流水线操作

`llm_agents/review_pipeline.yaml` 定义五个操作及其执行器：

| 操作 | 执行器 | 说明 |
|---|---|---|
| `classify_risk` | `tool_loop` | 与 `correct_errors` 合并为每条需求一次有界 tool-loop 调用 |
| `correct_errors` | `tool_loop` | 模型可调用 `review_tools.py` 的确定性只读工具取证 |
| `merge_duplicates` | `deterministic` | 结构化裁决由确定性索引承担 |
| `gap_find` | `deterministic` | coverage_gaps + 澄清遗漏档承担 |
| `test_point_generate` | `deferred` | schema 存在但暂零生产者 |

## 安全纪律

- API Key 只放环境变量，绝不入库、不进配置文件明文
- 蓝皮书 PDF、公司模板 xlsx、客户文档、含客户措辞的评测资产、
  API Key 均**禁止提交**
- `llm_trace.jsonl` 含客户文档全文，外发目录前必须检查
