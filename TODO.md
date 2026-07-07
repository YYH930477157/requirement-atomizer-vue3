# TODO — 待办与路线（2026-07-06）

> 来源：架构评审（2026-07-06）+ 组件增强评审 + 项目战略评审。完成一项划一项；
> 重启任何「有据缓建」项前先重跑探针。日常状态速查：输出目录 `run_manifest.json`。

## 架构债（评审编号 F1-F8；F1+F7 已完成 2026-07-06）

- [x] **F2|数据契约 + 版本戳校验**（2026-07-06 done：requirement_record.py 契约+血统戳+消费端校验）（1 天）
  - `requirement_record.py`：ai_requirements 行的字段契约（7 个消费者现全靠防御式 `.get()`；
    映射器 ai_req_id 缺失 bug 即此类），写入端校验。
  - 产物 JSON 头部盖 `producer_version` + 时间戳；消费端不匹配警告（"拿 v9 旧数据当新结果看"
    的另一半保险——manifest 已记账，产物本体也要可自证）。
- [x] **F8|xlsx 写入重试**（2026-07-06 done：xlsx_io.safe_save_workbook，4 写手接入，实际路径如实上报）（1 小时）：用户开着 Excel → 整链写崩（2026-07-05 实况）。统一
    "重试一次 → 加时间戳后缀另存 + 消息提示"。
- [x] **F4|LLM 调用收口**（2026-07-06 done：PURPOSE_MIN_TOKENS + apply_min_tokens，3 处收口）（半天）：max_tokens 下限已在 3 个模块各写一遍（6144/8192/16384）、
    trace 每个驱动手工接线。`llm_client.llm_call(purpose, ...)` 把 floors/trace/429/JSON 修复
    按用途焊死，新 LLM 环节自动继承纪律。
- [x] **F5|配置注册表**（2026-07-06 done：config.ENV_REGISTRY + 全仓扫描强制核对测试）（半天）：17 个 `RATOMIZER_*` env 散在各模块无文档。`config.py` 集中
    声明（名称/默认/说明/GUI 是否暴露）。
- [x] **F3|拆 ai_extract**（2026-07-06 done：extract_units + extract_guards，1319→1105 行，门面保旧名；自检环耦合深暂留主模块）（2 天，回归语料护航下做）：1319 行 8 种职责 →
    extract_units / extract_guards / extract_selfcheck / 主编排。维护性债非正确性债，不急。
- [x] **F6|双渲染器契约测试**（2026-07-06 done：共享夹具 annotation_contract.json，Python 锁 HTML/vitest 锁 Vue）（半天）：DocumentReview.vue 与 doc_annotation_export.py 同一
    语义两处实现（高亮 bug 修过两遍）。同一种子数据断言两边标记结构等价（jsdom 已在链里）。

## 组件增强（2026-07-06 评审，按落地价值排序）

- [x] **裁决样本库**（2026-07-06 done：adjudication_bank.py，env RATOMIZER_ADJUDICATION_BANK 指路，chain 尾自动收割，富化注入；待真实裁决积累生效）：专家 accepted/rejected 裁决 → 黄金 few-shot / 负例，按模块
    +词面检索注入抽取与富化 prompt（机制同模板知识注入）。跨项目积累，越用越准。
    依赖真实使用积攒裁决——越早上线越早开始攒。
- [x] **澄清答复回灌**（2026-07-06 done：必答 sheet 答复列 → 导入（CLI/GUI）→ 富化注入+有据基线扩展 → 报告消解）：clarification_questions.xlsx 评审会答复回来后无回灌
    入口。答复登记 → 按需求 id 回链 → 裁决/覆盖生效 → 免 LLM 重建交付物。
- [x] **Annex 引用解析**（2026-07-06 done：Annex A / A.1.4.6 形引用解析注入，prompt v11）：跨引用解析器只认数字条款号，不认 "Annex A"/"A.1.4.6"
    ——EN 16314 测试程序全在附录，这些引用现在是瞎的。正则扩展 + 测试。
- [x] **JSON schema 模式**（2026-07-06 done：探针证实 mimo 双模型支持 json_object；RATOMIZER_LLM_JSON_SCHEMA=1 启用，失败自动降级；默认关以兼容其它端点）：mimo 若支持 response_format=json_schema，每轮
    1-2 个 JSON 解析失败单元直接归零。
- [x] **术语定向注入**（2026-07-06 done：按单元检出已定义术语注入定义，漂移基线+指纹折入）：术语表现注入头 1800 字（后面截断）。改为按单元检出所用术语、只注入
    其定义。
- [x] **中英术语对照表**（2026-07-06 done：每文档一次 LLM 生成，哈希缓存 term_map.json，注入 doc_context）：每文档一次 LLM 生成术语译法对照（缓存），注入所有调用——交付物
    中文术语一致性（pressure absorption 等不再多种译法）。
- [x] **few-shot 换真样本**（2026-07-06 机制 done：样本库范例按模块+词面注入富化 prompt；范例质量随真实裁决积累提升）

## 战略项（顺序即建议执行序）

- [ ] **真实试点**：一名工程师 × 一份真实客户文档 × 端到端计时，对比纯人工基线 + 数返工量。
    验证的是商业假设（专家愿意裁决而非重写），优先级高于一切新功能。
- [ ] **金标召回率**：专家标注一份真实标准的全量需求（~50-100 条），每版本算真实查全/查准。
    "不漏、不编"从感觉变数字。回归语料（corpus_eval）已就位，缺金标。
- [ ] **数据治理裁定（一次会议）**：①llm_trace.jsonl 含客户文档全文，输出目录外发前须删；
    ②云端点（小米 MiMo）= 客户标准全文发第三方，公司保密政策是否允许需明文裁定
    （本地 Ollama 路径是现成降级方案）。
- [x] **交付物收敛（文档层）**（2026-07-06：ARCHITECTURE.md 明确成文.xlsx=B 轨主交付物 + 系统地图；UI 呈现精简留后续）：B 轨明确「软件需求列表-成文.xlsx」为唯一主交付物，其余降为中间产物，
    UI 相应呈现；给新人的 ARCHITECTURE.md。
- [ ] **Green Book 引入**（A 轨行为层第二本书）：散文语料无 class_id 键，需与蓝皮书不同的
    检索策略（术语倒排 or 受约束语义），先小样探针再立项。
- [ ] **词典重分词**（机翻 PDF 残留碎词的下一刀，2026-07-07 OCR 对比裁定的替代路线）：
    确定性词频/SymSpell 重分词 pass，只在去碎门控开启的文档上跑，数字/编码/单位豁免。
    目标：残留小写碎词（UNI 实测 72 处）与词间缺空格（"ofbytes"/"i sencoded"）修掉大半。
    **裁定背景**：OCR 重排被否——文字层字符 100% 准 vs OCR 引入 0/O、1/l 混淆
    （OBIS 错一位即严重缺陷），拿可修的排版问题换不可修的字符问题，方向反了；
    视觉模型只在将来表格结构不够用时按"视觉出结构、字符取文字层"评估。
- [ ] **M4c 扫描件 OCR**：等英文扫描件语料攒够（5-10 份）再立项。选型已定：Tesseract eng +
    框线 CV 切格；VLM 仅辅助且数字双引擎一致。
- [x] **模型 A/B**（2026-07-06 done，**裁决：pro 保持默认**——EN 16314 全量双跑：mimo-v2.5 覆盖率 69% 略高，但漏值 29 vs 18、重复对 8 vs 3、验收空话 6 vs 3，且并发限流下墙钟无优势（716s vs 741s，调用数反翻倍 460 vs 220）。"快 9 倍"仅单调用成立，吞吐被 429 锁死。数据：ab_arch/deep_test_result.json）

## 有据缓建（探针零收益，勿投机重启；重启前先在新语料重跑探针）

- 整章阅读架构（A/B 已裁决 2026-07-05：覆盖率 -6pt、参数表腰斩——lost in the middle；
  代码保留 `RATOMIZER_AI_UNIT_MODE=chapter` 实验开关，换更强模型一键重测）
- analyze 接蓝皮书（B 轨需求无接口类名，0/288）
- OBIS→class 连接提升蓝皮书覆盖（ABNT 行为正文 0 个 OBIS 形码）
- 类名归一化/别名（ABNT 未命中全是噪声或 Green Book 域引用，救回 0 条）
- Blue Book Part1 OBIS 节消费者（70 节已摄入，暂无消费方）
