# next-steps-plan-2026-08-29 执行总结论（2026-08-30，用户裁定：剩余付费步骤不跑，以已跑数据收口）

**总花费：≈¥43.73**（任务 A flag 开验证 ¥7.30 + 任务 B 门禁 ¥36.43，余额权威；
key 现透支 -¥0.70，`is_available=false`——后续任何付费使用前需充值）。

---

## 结论一：大纲权威 flag（RATOMIZER_OUTLINE_AUTHORITY）——**No-Go，默认保持 0**

依据 `docs/outline-authority-validation-2026-08-29.md`（含对照有效性强制章节）：

- **过线的四条**：块守恒 821=821 无违例（OutlineAuthorityError 零出现）；新切条款
  FRE 抽样 10/10 引句锚定正确、零跨条款借位；ABNT 结构良好文档上重切克制
  （358→361）；duplicates 6→0、binding 50→30、evidence 15→6 全线收敛、
  preservation 50 持平（表格数字，任务 D 课题域）。
- **卡线的一条**：义务覆盖未收敛——统一碎片口径下实质义务未覆盖 18（result3）
  →22（flag 开真实运行），且对同代码 flag 关基线（6）明显恶化、归因混合
  （新边界×新 LLM 输出不可分，3.5 步对照腿未获批准执行）。
- **病灶条款本身修复成功**：BLK-000240「2.3 STATEMENT OF REQUIREMENTS
  (TECHNICAL)」从病理父条款切出为独立条款、义务零未覆盖——立项目标达成，
  但整体判定仍以义务覆盖红线为先。
- **计划书勘误**：§1.1 的「207→239（39 demoted+34 confirmed）」与代码事实不符，
  实测 207→**339**（134+2），与 `bef6a86` 提交信息吻合。
- 若重启翻转评估，修复方向已在报告 §5：义务检测器碎片误报削减（两边各 21 条
  假义务）、新切短条款的主题内粒度漏抽（prompt/近邻合并）、heading-only 条款
  退化 objective。

## 结论二：WS0/去原子化主线——**两旧根因实证已修，B 轨守恒真实语料闭合；门禁 FAIL 的两个残留都不是 B 轨管线问题**

依据 `docs/ws0-gate-result-2026-08-30.md`：

- **08-17 根因①（XLSX 读取器别名缺口）实证已修**：A 轨成文 932 行全部可读。
- **08-17 根因②（B 轨守恒 duplicates=6）实证已修**：本次 B 轨在 ABNT 真实语料
  **conservation_ok=True**（176 条 FRE）——功能直抽主线（clause_family 策略 +
  路由收敛）的正确性拿到最硬的一块正向证据。
- **残留一（A 轨新缺陷，待修）**：模板成文 60 条"只有序号无正文"的追加行
  （状态字/事件类；写入侧 `template_writer` 序号分配与合成载荷不齐——
  读取器列定位已验证正确）。这是门禁的价值产出：A 轨交付物质量真 bug。
- **残留二（经费，非缺陷）**：key 在 B 轨 171/176 条款处 402 耗尽，末段退 stub
  → execution_status=failed（stub 如实记败，未伪装）。
- **重跑通道随时可开**（用户暂缓）：材料齐备（truth 190 行/14 键阈值/模板/
  parsed），`%TEMP%\ab-runner.hywzdhbl\A_atoms\ai_extract_cache.jsonl` 温缓存
  保留——先修空行缺陷，再充值 ≈¥8-12 即可重跑。EXECUTION_POLICY 默认翻转
  议案在门禁 PASS 前不具条件。

## 结论三：交付的资产与纪律事实

- **任务 C 完成**：`tools/audit_review_queue_projection.py`（队列投影只读审计，
  exit 0/2/3 契约）+ 12 测试，分支 `codex/queue-projection-audit` 提交 `65fe90f`
  （**未 push，合并待用户**）；worktree 全量 4211 OK；真实 result3 包审计前后
  全树哈希一致（零写入证明）。
- **成本口径教训**：deepseek-v4-flash 为 reasoning 模型，输出 token 占 62% +
  `max_tokens` 截断升级重试，实际单价 ≈¥6-7/百万混合 token——旧 trace 字符
  折算口径低估约 3 倍，后续预算按此校准。
- **安全备注**：`out/ab-gate-*.json` 的 env_snapshot 含明文 key（out/ 不进仓）；
  key 全程只走进程环境，未落任何仓内文件。

## 遗留清单（全部为可选项，按价值排序）

1. A 轨空正文行缺陷修复分支（`template_writer`/合成侧载荷缺失）——门禁重跑前置；
2. 门禁重跑（warm cache ≈¥8-12）→ 若 PASS 提 EXECUTION_POLICY 翻转议案；
3. 大纲 flag 三修复方向 + 可选 3.5 对照腿（¥7）后重启翻转评估；
4. 任务 D：技术表格保留率诊断（零成本，未启动）——preservation blocking 50 项
   的归类与四候选设计文档；
5. 任务 C 分支合并 + 两份报告/CLAUDE.md 条目提交（用户决定）。
