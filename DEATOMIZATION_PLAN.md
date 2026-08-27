# 需求分析去原子化改造方案(最终版)

> 2026-08-15 定稿。已吸收评审意见(守恒模型/A-B 验证门/评审权威/Claim 迁移/失败语义/
> 默认值机制/删除顺序全部按评审修正)。第 1 步(开关接入)已合入 main(`8389e1d`);
> 本文是后续全部改造的立项依据与执行顺序,未经 Go/No-Go 门不得翻转默认、不得删旧链。

---

## 一、背景与动机:为什么去原子化

当前 B 轨主链是"先拆散、再拼回":

```
parse → ai-extract(条款拆成原子) → functional-synthesis(原子拼回功能)
      → requirements-analysis → template-write → clarification-report
```

"需求变散"是这条链的结构性后果,不是单点 bug:

1. **抽取端强制拆细**:ai_extract 系统提示要求"不同需求点必须拆开",粒度天然低于功能;
2. **合成端拼命重并**:functional_catalog.py 约 600 行纯规则(家族键聚类/互斥限定词表/
   周期档位分家/型号冲突护栏)+ LLM 分组 + 双份守恒账,唯一职责是把原子粘回功能粒度;
3. **合并刻意保守**:互斥限定、不同事件主体、参数冲突一律保持拆分,LLM 分组失败还回退
   确定性结果(=维持散)——同一功能散在不同章节基本拼不回去;
4. **粒度来回震荡**:条款族 → 原子 → 功能目录 → 下钻再切句子;同一文本过 LLM 最多七八轮。

**核心论断:先拆散再拼回,拆散侧的每一分成本(拆细纪律/重并规则/双份守恒账/逐原子
裁决与批注账本)都是纯开销。** 条款直抽(functional_extract,WS2)以条款为最小抽取单元、
单次 LLM 直出功能需求级条目,是替代形态——但它目前有两类缺陷:基础守恒模型不合理
(§3.1),以及验证与评审配套不完整(§3.2-3.5)。本方案先修这两类,再谈翻转默认。

---

## 二、当前状态基线(第 1 步已交付)

`8389e1d` 已合入 main,默认关、行为零变化:

- `RATOMIZER_FUNCTIONAL_EXTRACT=1` 时 chain 把 `ai-extract`+`functional-synthesis`
  整体替换为 `functional-extract` 阶段;UI/CLI 照旧传旧阶段名,替换单点落账;
- 无原子链形态打通:缺 `ai_requirements.jsonl` 时,`requirements-analysis` /
  `clarification-report` 以直抽产物为唯一依据;
- producer/指纹/版本戳全套就位;修复了"缓存命中不校验产物文件"缺陷;
- 直抽模式下天然可用:功能工作台 FunctionalReview(`/functional-requirements` 直读产物)、
  澄清的功能级弱词/可测性扫描。

**尚未解决、本方案覆盖的缺口**:守恒模型(§3.1)、A/B 验证门(§3.2)、评审权威与
锚点(§3.3)、Claim 绑定(§3.4)、失败语义(§3.5)、默认值机制(§3.6)。

---

## 三、改造项

### 3.1 修正直抽基础模型:obligation/evidence 守恒(最先做)

**问题**:当前守恒是"每个条款 block_id 被且只被一条需求消费"(exactly-once)。这不合理:
一个条款可能包含多个可独立测试的义务(一句多 shall),同一功能需求也可能合法引用多个
章节。exactly-once 会把多义务条款压成一条、或因多消费被误判重复而阻塞成文。

**新模型**:

1. **多对多合法**:一个条款允许产出多条功能需求;一条功能需求允许关联多个来源条款;
   "同一 block 被多条需求引用"不再判为重复抽取。
2. **证据锚(evidence anchors)**:每条需求保存多个证据锚——block_id、原文引句、
   句子/span。锚由确定性后处理派生(复用 functional_drilldown 的句切分与义务模态
   判据),LLM 不得填写(结构字段冻结纪律不变)。
3. **分项检查,各自定性**(替换单一 ok 布尔):
   - **条款覆盖率**:每条款块至少被一条需求的证据锚覆盖(未覆盖=漏抽,blocking);
   - **义务覆盖率**:条款内每个义务句(模态动词支配的独立动作)至少被一条需求的
     证据锚覆盖(未覆盖=义务丢失,blocking;判据复用 drilldown 的多行为信号机制);
   - **无证据需求**:source_block_ids 为空或引句不命中任何声明块(blocking);
   - **重复需求**:同一义务句被多条需求覆盖**且**叙述高度相似(正常多视角引用不判重,
     判重需证据+叙述双重命中);
   - **保留完整性**:条款中的条件(if/unless/当…时)、例外(except/除非)、否定(not/
     不/无)、数值与单位,在对应需求叙述中是否保留(丢失=warning/blocking 分级——
     研发直接执行的字段丢失为 blocking)。
4. **成文闸门同步**:`raise_if_unconserved` 改按新失败类别阻塞;下游消费面
   (requirements_analysis 闸门、desktop_tasks readiness 门、chain 聚合)读新字段。
5. **缓存指纹 bump**:守恒语义变化即产物语义变化,`FUNCTIONAL_EXTRACT_GUARDS_VERSION`
   bump 使旧缓存失效。

**验收**:多义务条款出多条不被压、不被阻;跨条款引用不判重;五项检查各有正反测试。

### 3.2 重做真实语料 A/B 验证门(独立的完整 B 轨 runner)

**问题**:现有 `shadow_run.py` 不能作为翻转依据——它同时切换多个功能开关、不跑完整
B 轨、直抽失败或产物缺失时仍可能判 PASS。

**新增独立 A/B runner**(建议 `tools/ab_runner.py`):

- **A 路**:`ai-extract → functional-synthesis → requirements-analysis → template-write`;
- **B 路**:`functional-extract → requirements-analysis → template-write`;
- **控制变量**:相同文档、模型、温度、提示版本、模板;**唯一差异是
  `RATOMIZER_FUNCTIONAL_EXTRACT`**;
- **失败即 FAIL**:直抽异常、产物缺失、stub/mixed 降级一律判失败,不记 PASS;
- **语料**:至少 2-3 份不同类型真实文档,**逐份判定,不用跨文档平均值掩盖单份问题**;
- **对比对象是最终 xlsx**,不只比中间 JSON。

**量化验收指标(逐文档设门槛,翻转前书面确认数值)**:

| 指标 | 说明 |
|---|---|
| 功能需求 recall / precision | 以人工真值集为基准 |
| 错误合并率 / 错误拆分率 | 该并没并 / 该拆没拆 |
| 条件、例外、否定、数值、单位、编码保存率 | 与 §3.1 保留检查同口径 |
| 重复率 | 重复需求检出数 / 总数 |
| 同一功能在最终 xlsx 中的行数 | 直接量化"变散"程度 |
| 人工评审还需重新拆分/合并的动作数 | 终极标准 |

**前置**:完成功能级人工真值集(WS0 目前 pending-human)——A/B 门没有真值集就没有
recall/precision 可言,这是翻转前必须补的课。

### 3.3 统一功能级评审权威(不新增状态文件)

**问题**:仓库已有 `ai_review_states.jsonl`、`verification_states.jsonl`、
`adjudication_results.jsonl` 三个评审状态文件。若为直抽再新建独立的 FRE 状态文件,
reject/module/ownership 会出现多个权威来源。

**方案**:

1. **定义统一评审对象协议**(所有评审存储共用同一行契约):

```json
{
  "track": "B",
  "level": "functional",
  "subject_id": "FRE-xxx",
  "source_revision": "...",
  "status": "accepted|rejected|needs_discussion",
  "module_override": "...",
  "ownership_override": "..."
}
```

2. **优先扩展现有 `verification_states` 或建统一评审存储**,明确**唯一写权威**,
   其余文件只做投影;`source_revision` 承载产物变化后的 CAS/重新确认语义。
3. **翻转前必须打通的能力**(缺一不可):
   - 文档批注定位(批注卡片锚到功能条目,quote→block 匹配复用
     `merged_consistency.match_source_quote_blocks`,不重写);
   - 功能工作台(FunctionalReview)查看与裁决;
   - module/ownership 覆盖;
   - reject;
   - 澄清问题生成(直抽条目的护栏信号 `rejected_codes`/`numeric_drift_flag` 投影进
     `collect_questions`,补齐缺席的原子级 suspicion 来源);
   - `requirements_analysis` 对专家结果的投影;
   - 产物变化后的 CAS/重新确认(`source_revision` 不匹配 → 状态置待重新确认,
     不静默沿用旧裁决)。

### 3.4 Claim 迁移(不能延后)

**问题**:B 轨 Claim 发布绑定 `ai_requirements.jsonl`,而全量闭合门要求 Claim Ready。
"直抽模式 Claim 暂不可用"与翻转默认**互斥**——翻转后所有目录的发布门都会卡死在
Claim 为空,或更糟:被误判为已完成。

**翻转默认前必须完成**:

1. Claim target 从原子需求迁移到功能需求(FRE- 为主键,§3.1 的多证据锚进 Claim 记录);
2. Claim authority 绑定新的功能需求产物与评审 revision(与 §3.3 的 source_revision 同源);
3. 直抽模式下 Ledger Ready / full closure 可正常达到(端到端验证,不是单测);
4. 旧结果的迁移或只读兼容路径明确(存量原子 Claim 目录仍可打开、可审、不误报);
5. **空账本 ≠ 已完成**:Claim 为空时 readiness 必须显式缺口,不得静默放行。

### 3.5 补齐失败与降级语义

**问题**:直抽 LLM 调用失败可能生成 stub 条目;预算功能默认关闭时不一定拦得住成文。

**规定**:

1. 真实生产运行出现 **stub、mixed、部分条款失败或预算耗尽** → 直抽阶段不得记 `ok`
   (manifest 状态用 `partial`/`failed`,复用 ai-extract 的 failed_sections 语义);
2. 下游分析与模板导出被阻止,或产物显式标记"不可发布草稿"(draft watermark + 
   result-package 完成证据拒绝);
3. **缓存不得把失败产物恢复成成功产物**:缓存行记录执行结果类别,重放时保留失败语义;
4. run manifest、readiness、结果包完成证据使用**相同**失败语义(三处对同一事实的
   表述必须一致);
5. **测试矩阵**:网络异常、超时、非法 JSON、部分成功、缓存命中、重试——每类至少
   一条"失败不被洗白"的测试(风格同 tests/test_audit_fixes.py,名字可倒查病灶)。

### 3.6 默认值翻转的真实机制(不只是改注册表)

**问题**:只改 `config.ENV_REGISTRY` 的默认字符串不够——运行逻辑直接读环境变量,
变量缺失时直抽仍是关。必须先建立**统一配置读取函数**(单源默认值),使以下入口全部
经它取值:CLI、Electron 后端子进程、`chain_task`、阶段指纹、单步命令、测试、打包版本。

**翻转动作**:统一读取函数默认值 `0 → 1`;保留 `RATOMIZER_FUNCTIONAL_EXTRACT=0`
显式回滚通道**一个完整发布周期**;重建 golden 基线(当前 main 存在 4 个预存 golden
失败,系本地基线过期——翻转前必须逐项说明并清零,否则新失败被旧失败掩盖)。

### 3.7 旧合并机器最后删除(带能力迁移)

**观察期内保留**:`functional_synthesis.py`、`functional_catalog.py`、旧缓存与结果
读取兼容、`=0` 回滚路径。

**观察期结束(建议一个发布周期无真实项目回退)后才删合并逻辑**。删除
`functional_catalog.py` 前,先把以下公共能力迁到独立模块(它们被直抽产物和评测依赖,
不属于"合并机器"):

- 功能需求 schema(objective/behaviors/… 字段模型——直抽复用的就是它);
- normalize / validate;
- ID 与 evidence 契约;
- 仍需保留的安全护栏(§3.1 后护栏收敛的单源);
- `agent_eval`、`semantic_quality` 等评测依赖。

**明确不做**:
- 不删 A 轨(atomize→llm-review→assemble→compose 是 DLMS 对象表文档的另一条轨);
- 不在直抽路径重新引入确定性合并规则——直抽"该并没并"时修 prompt 与条款族上下文包,
  不回头加合并,否则重蹈拆散再拼回。

---

## 四、执行顺序

1. 修正 obligation/evidence 守恒模型(§3.1);
2. 建立只切直抽开关的完整 B 轨 A/B runner(§3.2);
3. 完成功能级人工真值集与量化验收门(§3.2);
4. 跑 2-3 份真实语料 A/B;
5. 统一功能级评审权威(§3.3);
6. 迁移文档批注、澄清与 Claim(§3.3/§3.4);
7. 补齐失败、缓存、结果包与旧结果兼容测试(§3.5);
8. 小范围灰度开启直抽(真实项目试点,非默认翻转);
9. 验证通过后翻转默认(§3.6);
10. 观察一个发布周期;
11. 无回退后删除旧合并链(§3.7,先迁公共能力);
12. 最后收敛护栏、loader 与缓存公共实现(原第 4 步:四份护栏/三份指纹/两处词表收敛
    单源——放在最后,因为 §3.1/§3.7 会先消掉其中两份,收敛成本更低)。

## 五、Go/No-Go 条件(翻转默认,须同时满足)

1. 真实语料 A/B 达到预先定义的量化指标(逐文档判定);
2. 多义务条款不会因 block exactly-once 被压成一条或阻塞(§3.1 交付的直接验收);
3. 文档批注、裁决、归属覆盖和澄清完整可用(§3.3);
4. Claim Ledger / full closure 在直抽模式可达(§3.4);
5. stub/mixed/部分失败不会形成可发布成功产物(§3.5);
6. 新旧结果包都能正确打开(§3.4 兼容路径);
7. 全量单测、前端测试、打包测试通过;
8. Golden 失败已逐项说明并清零;
9. `=0` 回滚路径经过实际验证(不只是代码审查)。

## 六、风险与纪律(全程有效)

1. **缓存指纹纪律**:每步动产物语义必须 bump 对应版本戳(prompt/guards/阶段实现戳),
   否则 chain 续跑静默复用旧产物;
2. **每步双验证**:机制测试(单测)证明"没改坏",语料对比证明"确实更好",缺一不可;
3. **单一权威原则**:评审状态、配置默认值、失败语义各只有一个权威源,其余全是投影;
4. **回滚优先**:观察期内一切问题先走 `=0` 回滚,不在压力下修新链。

---

## 结论

去原子化方向确认继续,但**先完成"语义守恒(§3.1)、可靠 A/B(§3.2)、统一评审权威
(§3.3)、Claim 迁移(§3.4)、失败门禁(§3.5)",再经灰度与 Go/No-Go 翻默认(§3.6);
旧合并链在观察期结束后、公共能力迁移完毕后删除(§3.7)。**
