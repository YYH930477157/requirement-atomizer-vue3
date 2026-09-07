# 任务 D：表格 preservation blocking 分类（只读诊断）

> 本文由 `tools/task_d_classify.py` 生成。分类不改变 `functional_extract` 的守恒语义；输入结果包按其已记录的 conservation report 读取。`manual_review` 保留证据不足项。
两个语料合计 blocking：**53**。
数据限制：仓库内 SBD 结果包记录的是 v3、ABNT 临时 B 结果包记录的是 v6；当前代码已经是 v7。两者不能直接作为当前 v7/v8 门禁 PASS 证据。旧报告还只保存 `section_id`，无法在同名 Security 等条款之间复原唯一条款序号。

## sbd_result3

- 结果包：`E:\Codex\requirement-atomizer-vue3\out\attribution-result3`
- conservation model：`functional-conservation-obligation-evidence-v3`；execution_status：`partial`
- blocking 总数：**50**；分类：`{'manual_review': 41, 'a_narrative_loss': 9}`

| section | kind | token | 类别 | FRE | baseline/cell | 证据 |
|---|---|---|---|---:|---:|---|
| CH-000004 | number | `0` | manual_review | 2 | 1/0 | source=N, cell=N, narrative=N, table_out=0 |
| CH-000004 | number | `3` | a_narrative_loss | 2 | 1/0 | source=Y, cell=N, narrative=N, table_out=0 |
| CH-000004 | number | `94` | a_narrative_loss | 2 | 1/0 | source=Y, cell=N, narrative=N, table_out=0 |
| CH-000004 | number | `95` | a_narrative_loss | 2 | 1/0 | source=Y, cell=N, narrative=N, table_out=0 |
| CH-000004 | number | `96` | a_narrative_loss | 2 | 1/0 | source=Y, cell=N, narrative=N, table_out=0 |
| CH-000004 | number | `99` | a_narrative_loss | 2 | 1/0 | source=Y, cell=N, narrative=N, table_out=0 |
| 3 All Bidders must complete all schedules without fail for them to be  | number | `10` | manual_review | 8 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 3 All Bidders must complete all schedules without fail for them to be  | number | `3` | manual_review | 8 | 0/0 | source=Y, cell=N, narrative=N, table_out=0 |
| 3 All Bidders must complete all schedules without fail for them to be  | number | `4` | manual_review | 8 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 3 All Bidders must complete all schedules without fail for them to be  | number | `7` | manual_review | 8 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 3 All Bidders must complete all schedules without fail for them to be  | number | `8` | manual_review | 8 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 3 All Bidders must complete all schedules without fail for them to be  | number | `9` | manual_review | 8 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 11 Valid Tax Clearance Certificate issued by ZIMRA for local bidders o | number | `11` | manual_review | 4 | 0/0 | source=Y, cell=N, narrative=N, table_out=0 |
| 11 Valid Tax Clearance Certificate issued by ZIMRA for local bidders o | number | `12` | manual_review | 4 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 11 Valid Tax Clearance Certificate issued by ZIMRA for local bidders o | number | `4` | manual_review | 4 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 11 Valid Tax Clearance Certificate issued by ZIMRA for local bidders o | number | `99` | manual_review | 4 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 13 Delivery period is two (2) months or better from receipt of order a | number | `13` | manual_review | 6 | 0/0 | source=Y, cell=N, narrative=N, table_out=0 |
| 13 Delivery period is two (2) months or better from receipt of order a | number | `14` | manual_review | 6 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 13 Delivery period is two (2) months or better from receipt of order a | number | `15` | manual_review | 6 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 13 Delivery period is two (2) months or better from receipt of order a | number | `16` | manual_review | 6 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 13 Delivery period is two (2) months or better from receipt of order a | number | `17` | manual_review | 6 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 13 Delivery period is two (2) months or better from receipt of order a | number | `18` | manual_review | 6 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 19 The warranty period for the specified STS Smart Single Phase DIN an | number | `19` | a_narrative_loss | 3 | 1/0 | source=Y, cell=N, narrative=N, table_out=0 |
| 19 The warranty period for the specified STS Smart Single Phase DIN an | number | `20` | a_narrative_loss | 3 | 1/0 | source=Y, cell=N, narrative=N, table_out=0 |
| 19 The warranty period for the specified STS Smart Single Phase DIN an | number | `5` | a_narrative_loss | 3 | 1/0 | source=Y, cell=N, narrative=N, table_out=0 |
| 19 The warranty period for the specified STS Smart Single Phase DIN an | number | `99` | a_narrative_loss | 3 | 1/0 | source=Y, cell=N, narrative=N, table_out=0 |
| 22 Manufacturer's supply history for the past five (5) years (between  | number | `22` | manual_review | 4 | 0/0 | source=Y, cell=N, narrative=N, table_out=0 |
| 22 Manufacturer's supply history for the past five (5) years (between  | number | `23` | manual_review | 4 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 22 Manufacturer's supply history for the past five (5) years (between  | number | `24` | manual_review | 4 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 22 Manufacturer's supply history for the past five (5) years (between  | number | `25` | manual_review | 4 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 26 There shall be no change of Original Equipment Manufacturer (OEM) f | number | `26` | manual_review | 10 | 0/0 | source=Y, cell=N, narrative=N, table_out=0 |
| 26 There shall be no change of Original Equipment Manufacturer (OEM) f | number | `6` | manual_review | 10 | 0/0 | source=Y, cell=N, narrative=N, table_out=0 |
| 26 There shall be no change of Original Equipment Manufacturer (OEM) f | number | `99` | manual_review | 10 | 0/0 | source=Y, cell=N, narrative=N, table_out=0 |
| 26 There shall be no change of Original Equipment Manufacturer (OEM) f | number | `2` | manual_review | 2 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 26 There shall be no change of Original Equipment Manufacturer (OEM) f | negation | `not` | manual_review | 4 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 26 There shall be no change of Original Equipment Manufacturer (OEM) f | number | `4` | manual_review | 4 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 26 There shall be no change of Original Equipment Manufacturer (OEM) f | number | `5` | manual_review | 4 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 26 There shall be no change of Original Equipment Manufacturer (OEM) f | number | `6` | manual_review | 4 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 26 There shall be no change of Original Equipment Manufacturer (OEM) f | number | `7` | manual_review | 4 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 26 There shall be no change of Original Equipment Manufacturer (OEM) f | number | `99` | manual_review | 4 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 1 have the legal capacity to enter into a contract; | number | `7` | manual_review | 8 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 1 have the legal capacity to enter into a contract; | number | `8` | manual_review | 8 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 6 have the nationality of an eligible country as specified in the Spec | negation | `no` | manual_review | 1 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 6 have the nationality of an eligible country as specified in the Spec | number | `1` | manual_review | 6 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 6 have the nationality of an eligible country as specified in the Spec | number | `11` | manual_review | 6 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 6 have the nationality of an eligible country as specified in the Spec | number | `12` | manual_review | 6 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 6 have the nationality of an eligible country as specified in the Spec | number | `13` | manual_review | 6 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 6 have the nationality of an eligible country as specified in the Spec | number | `9` | manual_review | 6 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 6 have the nationality of an eligible country as specified in the Spec | number | `99` | manual_review | 6 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |
| 1 Letterhead of registered commercial bank (i.e. the Supplier of the B | negation | `not` | manual_review | 1 | 0/0 | source=N, cell=N, narrative=N, table_out=0 |

分类规则

- `a_narrative_loss`：源扁平文本和已声明 FRE 都存在 token，FRE 叙述缺失。
- `b_missing_functional_requirement`：可定位源条款，但没有 FRE 声明。
- `c_table_or_baseline_input`：token 在物理 cell 中可见，却不在当前扁平守恒基线，或条款仅存在于路由外上下文。
- `manual_review`：证据不够，必须人工裁决。

## abnt_ws0_b_direct

- 结果包：`C:\Users\YYHwudi\AppData\Local\Temp\ab-runner.9gqsr665\B_direct`
- conservation model：`functional-conservation-obligation-evidence-v6`；execution_status：`partial`
- blocking 总数：**3**；分类：`{'manual_review': 3}`

| section | kind | token | 类别 | FRE | baseline/cell | 证据 |
|---|---|---|---|---:|---:|---|
| Security | negation | `no` | manual_review | 27 | 6/187 | source=Y, cell=N, narrative=Y, table_out=5 |
| Security | number | `5` | manual_review | 27 | 6/187 | source=Y, cell=Y, narrative=Y, table_out=5 |
| Security | number | `64` | manual_review | 27 | 6/187 | source=Y, cell=N, narrative=N, table_out=5 |

分类规则

- `a_narrative_loss`：源扁平文本和已声明 FRE 都存在 token，FRE 叙述缺失。
- `b_missing_functional_requirement`：可定位源条款，但没有 FRE 声明。
- `c_table_or_baseline_input`：token 在物理 cell 中可见，却不在当前扁平守恒基线，或条款仅存在于路由外上下文。
- `manual_review`：证据不够，必须人工裁决。

