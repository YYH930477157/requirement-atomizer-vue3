<template>
  <n-config-provider>
    <div class="shell">
      <aside class="side-nav">
        <div class="side-brand">
          <div class="brand-mark" aria-hidden="true"><ScanSearch :size="19" :stroke-width="2.1" /></div>
          <div class="brand-text">
            <div class="brand-name">标准需求抽取与审查平台</div>
            <div class="brand-sub">Requirement Atomizer</div>
          </div>
        </div>
        <nav v-for="grp in navGroups" :key="grp.title" class="nav-group">
          <p class="nav-title">{{ grp.title }}</p>
          <button
            v-for="item in grp.items"
            :key="item.id"
            class="nav-button"
            :class="{ active: activeNav === item.id }"
            :data-testid="`nav-${item.navTestId}`"
            type="button"
            @click="handleNavAction(item.id)"
          >
            <component :is="item.icon" class="nav-icon" :size="17" :stroke-width="1.9" aria-hidden="true" />
            <span>{{ item.label }}</span>
          </button>
        </nav>
        <nav class="nav-group">
          <p class="nav-title">交付物</p>
          <button class="nav-button" type="button" data-testid="nav-实现规格" @click="openDeliverable('dlms_cosem_spec_requirements.json')">
            <Braces class="nav-icon" :size="17" :stroke-width="1.9" aria-hidden="true" /><span>实现规格</span>
          </button>
          <button class="nav-button" type="button" data-testid="nav-软件需求列表" @click="openDeliverable('软件需求列表-成文.xlsx')">
            <FileSpreadsheet class="nav-icon" :size="17" :stroke-width="1.9" aria-hidden="true" /><span>软件需求列表</span>
          </button>
          <button class="nav-button" type="button" data-testid="nav-澄清清单" @click="openDeliverable('clarification_questions.xlsx')">
            <CircleHelp class="nav-icon" :size="17" :stroke-width="1.9" aria-hidden="true" /><span>澄清清单</span>
          </button>
        </nav>
        <div class="nav-spacer"></div>
        <nav class="nav-group">
          <button
            v-for="item in phaseNavItems.filter((i) => i.id === 'settings')"
            :key="item.id"
            class="nav-button"
            :class="{ active: activeNav === item.id }"
            :data-testid="`nav-${item.navTestId}`"
            type="button"
            @click="handleNavAction(item.id)"
          >
            <component :is="item.icon" class="nav-icon" :size="17" :stroke-width="1.9" aria-hidden="true" />
            <span>{{ item.label }}</span>
          </button>
        </nav>
        <div class="side-user">
          <div class="side-avatar" aria-hidden="true"><UserRound :size="15" :stroke-width="2" /></div>
          <div><b>需求评审专家</b><span>GUI Phase 1</span></div>
        </div>
      </aside>

      <main class="main">
        <header class="app-bar">
          <div class="page-title-area">
            <h3 class="page-title">{{ activeNavLabel }}</h3>
            <span class="doc-chip" :title="documentDisplayName"><FileText :size="13" aria-hidden="true" />{{ documentDisplayName }}</span>
          </div>

          <div class="app-actions">
            <button class="button" type="button" data-testid="action-open-document" @click="handleOpenDocument"><FolderOpen :size="15" aria-hidden="true" /><span class="button-label">导入文档</span></button>
            <button class="button" type="button" data-testid="action-select-output-dir" @click="handleOpenOutput"><FolderOutput :size="15" aria-hidden="true" /><span class="button-label">选择输出目录</span></button>
            <button class="button" type="button" data-testid="action-open-existing-output" :disabled="isRunning" @click="handleOpenExistingOutput"><History :size="15" aria-hidden="true" /><span class="button-label">打开已有结果</span></button>
            <span class="action-divider" aria-hidden="true"></span>
            <label class="llm-toggle">
              <input v-model="llmMode" type="checkbox" data-testid="llm-mode-toggle" />
              <span class="llm-track" aria-hidden="true"></span>
              <Sparkles :size="14" aria-hidden="true" /><span>LLM 富化</span>
            </label>
            <span class="action-divider" aria-hidden="true"></span>
            <button class="button" type="button" data-testid="action-test-pipeline" :disabled="isRunning" @click="handleRunPipeline({ llmReviewLimit: TEST_LLM_REVIEW_LIMIT })"><FlaskConical :size="15" aria-hidden="true" /><span class="button-label">测试运行</span></button>
            <button class="button primary" type="button" data-testid="action-run-pipeline" :disabled="isRunning" @click="() => handleRunPipeline()">
              <RefreshCw v-if="isRunning" class="spin" :size="15" aria-hidden="true" />
              <Play v-else :size="15" fill="currentColor" aria-hidden="true" />
              <span>{{ isRunning ? "运行中" : "运行" }}</span>
            </button>
            <button v-if="activeNav === 'document'" class="button icon-tool" type="button" data-testid="action-export-html" aria-label="导出批注 HTML" title="导出批注 HTML" @click="handleExportAnnotationHtml"><Download :size="16" aria-hidden="true" /></button>
            <button v-if="activeNav === 'document'" class="button icon-tool" type="button" data-testid="action-import-decisions" aria-label="导入裁决" title="导入裁决" @click="handleImportDecisions"><Upload :size="16" aria-hidden="true" /></button>
            <button v-if="activeNav === 'document'" class="button icon-tool" type="button" data-testid="action-import-answers" aria-label="导入澄清处置" title="导入澄清处置" @click="handleImportAnswers"><MessageSquareReply :size="16" aria-hidden="true" /></button>
          </div>
        </header>

        <!-- 统一消息 testid:与审查页 api-message 互斥渲染,任意页面都能拿到运行反馈 -->
        <div v-if="apiMessage && activeNav !== 'review'" class="global-message" data-testid="api-message"
             role="status">
          <CircleHelp :size="15" aria-hidden="true" class="global-message-icon" />
          <span class="global-message-text" :class="{ clamped: !apiMessageExpanded }">{{ apiMessage }}</span>
          <button v-if="apiMessage.length > 120" class="global-message-toggle" type="button"
                  data-testid="api-message-toggle" @click.stop="apiMessageExpanded = !apiMessageExpanded">{{ apiMessageExpanded ? "收起" : "详情" }}</button>
          <button class="global-message-close" type="button" aria-label="关闭消息" title="关闭消息"
                  @click.stop="apiMessage = ''"><X :size="14" aria-hidden="true" /></button>
        </div>

        <section v-if="activeNav === 'run'" class="run-home" data-testid="run-paths-panel">
          <div class="ov-stats">
            <div class="ov-stat" :class="{ 'is-empty': runOverview.functionalReqs == null }" data-testid="ov-functional">
              <div class="k">功能需求</div>
              <div class="v">{{ runOverview.functionalReqs != null ? runOverview.functionalReqs.toLocaleString("zh-CN") : "待运行" }}</div>
              <div class="d" :class="runOverview.selfCheck != null ? 'up' : 'flat'">{{ runOverview.selfCheck != null ? `↑ ${runOverview.selfCheck} 条来自自检补充` : "条款直抽，不是碎原子" }}</div>
            </div>
            <div class="ov-stat" :class="{ 'is-empty': !runOverview.verdict }" data-testid="ov-deliverable">
              <div class="k">交付状态</div>
              <div class="v">{{ runOverview.verdict || "待运行" }}</div>
              <div class="d" :class="runOverview.verdict === 'READY' ? 'up' : (runOverview.verdict ? 'warn' : 'flat')">
                {{ runOverview.deliverableHint || "成文或缺口见运行结束说明" }}</div>
            </div>
            <div class="ov-stat" :class="{ 'is-empty': runOverview.coverage == null }">
              <div class="k">章节覆盖率</div>
              <div class="v">{{ runOverview.coverage != null ? `${runOverview.coverage.toFixed(1)}%` : "待运行" }}</div>
              <div class="d" :class="runOverview.coverage != null ? 'up' : 'flat'">{{ runOverview.chapters || "跑完整链后统计" }}</div>
            </div>
            <div class="ov-stat" :class="{ 'is-empty': runOverview.questions == null }">
              <div class="k">必答澄清</div>
              <div class="v">{{ runOverview.questions != null ? runOverview.questions : "待运行" }}</div>
              <div class="d" :class="runOverview.verdict ? (runOverview.verdict === 'READY' ? 'up' : 'warn') : 'flat'">
                {{ runOverview.verdict ? `就绪判定:${runOverview.verdict}` : "评审会前必答清单" }}</div>
            </div>
          </div>

          <div class="flow-card">
            <div class="board-head">
              <h4>交付物流水线</h4>
              <span>run_manifest 台账 · 中断可续跑
                <em class="path-hint" data-testid="selected-input-path" :title="currentInputPath || undefined">{{ currentInputPath || "尚未选择文档" }}</em>
              </span>
              <strong class="pchip plain" data-testid="result-package-status">{{ resultPackageStatusLabel }}</strong>
            </div>
            <div class="run-meter" data-testid="run-progress">
              <div class="run-meter-head">
                <span>{{ runStage }}</span>
                <strong>{{ runProgress }}%</strong>
              </div>
              <div class="run-meter-detail" data-testid="run-progress-detail">{{ runProgressDetail }}</div>
              <div v-if="runStallHint" class="run-meter-stall" data-testid="run-stall-hint">{{ runStallHint }}</div>
              <div class="run-meter-track">
                <div class="run-meter-fill" :style="{ width: `${runProgress}%` }"></div>
              </div>
            </div>
            <div class="run-stage-board" data-testid="run-stage-board" role="list" aria-label="交付物流水线阶段">
              <div
                v-for="card in runStageCards"
                :key="card.key"
                class="run-stage-card"
                :class="`stage-${card.status}`"
                :data-testid="`run-stage-${card.key}`"
                role="listitem"
                :aria-current="card.status === 'running' ? 'step' : undefined"
                :aria-label="`${card.label}，${card.statusText}，${card.detail}`"
              >
                <span class="stage-title-row">
                  <span class="stage-name">{{ card.label }}</span>
                  <span class="stage-signal" aria-hidden="true"></span>
                </span>
                <strong class="stage-status">{{ card.statusText }}</strong>
                <small v-if="card.detail && card.detail !== card.statusText" class="stage-detail">{{ card.detail }}</small>
                <small v-if="card.status === 'running' && card.elapsedS >= 10" class="stage-elapsed">已用时 {{ formatDuration(card.elapsedS) }}</small>
                <small v-if="card.stalled" class="stage-stall" :data-testid="`run-stall-${card.key}`">已 {{ formatDuration(card.idleS) }} 无新进度 · 等待 LLM 响应</small>
                <span
                  class="stage-bar"
                  :class="{ 'is-indeterminate': card.status === 'running' && card.percent <= 0 }"
                >
                  <i :style="{ width: `${card.status === 'ok' || card.status === 'skipped' ? 100 : card.percent}%` }"></i>
                  <span class="stage-indeterminate-runner" aria-hidden="true"></span>
                </span>
                <span
                  v-if="card.relayStatus"
                  class="stage-relay"
                  :class="`relay-${card.relayStatus}`"
                  :data-testid="`run-relay-${card.key}`"
                  aria-hidden="true"
                ><i class="stage-relay-baton"></i></span>
              </div>
            </div>
          </div>

          <div class="run-grid">
            <div class="panel-card">
              <div class="board-head">
                <h4>功能需求 · 去评审</h4>
                <button class="link-button" type="button" @click="handleNavAction('functional')">进入功能需求 <ChevronRight :size="14" aria-hidden="true" /></button>
              </div>
              <div class="preview-wrap">
                <div class="preview-empty" data-testid="run-review-preview">
                  <Layers :size="22" aria-hidden="true" />
                  <p>条款直抽的功能条在「功能需求」里确认</p>
                  <span>碎原子不再作为评审对象。对照原文用「文档批注」，覆盖缺口看「覆盖审计」。</span>
                </div>
              </div>
            </div>
            <div class="panel-card">
              <div class="board-head">
                <h4>最新交付物</h4>
                <span class="path-hint" data-testid="selected-output-dir" :title="currentOutputDir || undefined">{{ currentOutputDir || "尚未选择输出目录" }}</span>
              </div>
              <div class="dl-files" data-testid="deliverable-html">
                <div v-for="f in DELIVERABLE_FILES" :key="f.key" class="dl-file">
                  <span class="dl-icon" :class="f.tone"><component :is="f.icon" :size="16" :stroke-width="1.9" aria-hidden="true" /></span>
                  <span class="dl-name"><strong>{{ f.name }}</strong><small>{{ f.hint }}</small></span>
                  <button class="deliverable-open" type="button" :aria-label="`打开 ${f.name}`" :title="`打开 ${f.name}`" @click="openDeliverable(f.name)"><ExternalLink :size="15" aria-hidden="true" /></button>
                </div>
              </div>
              <div v-if="lastStageNotes.length" class="note-warn">
                <b>注意</b>
                <span>{{ lastStageNotes.join("；") }}</span>
              </div>
              <div v-if="reviewInsights.length" class="note-insight" data-testid="review-insights">
                <b>裁决复盘建议（{{ reviewInsights.length }}）</b>
                <ul class="insight-list">
                  <li v-for="(s, i) in reviewInsights" :key="i">{{ s }}</li>
                </ul>
              </div>
            </div>
          </div>

          <div v-if="recentSessions.length" class="panel-card recent-card" data-testid="recent-sessions">
            <div class="board-head">
              <h4>最近结果</h4>
              <span class="path-hint">重启应用自动恢复最近一次；点击直接打开历史输出目录，无需重跑</span>
            </div>
            <ul class="recent-list">
              <li v-for="(entry, index) in recentSessions" :key="entry.outputDir">
                <button
                  class="recent-item"
                  :class="{ 'is-current': isCurrentOutputSession(entry.outputDir) }"
                  type="button"
                  :disabled="!entry.exists || !entry.isOutput || isCurrentOutputSession(entry.outputDir)"
                  :title="entry.outputDir"
                  :data-testid="`recent-open-${index}`"
                  @click="openRecentSession(entry)"
                >
                  <History :size="15" aria-hidden="true" />
                  <span class="recent-label">{{ entry.label }}</span>
                  <span class="recent-path">{{ tailPath(entry.outputDir) }}</span>
                  <span class="recent-time">{{ formatRecentTime(entry.openedAt) }}</span>
                  <span v-if="isCurrentOutputSession(entry.outputDir)" class="recent-current">当前会话</span>
                  <span v-else-if="entry.classification?.kind === 'package_v1'" class="recent-current">{{ entry.classification.analysisStatus === "completed" ? "分析已完成" : entry.classification.analysisStatus === "running" ? "上次运行中断" : "分析未完成" }}</span>
                  <span v-else-if="entry.classification?.kind === 'legacy'" class="recent-current">旧版结果</span>
                  <span v-else-if="!entry.exists || !entry.isOutput" class="recent-missing">目录已移动或删除</span>
                </button>
              </li>
            </ul>
          </div>
        </section>

        <template v-if="activeNav === 'review'">
        <section class="stat-strip" data-testid="phase1-stats">
          <button
            v-for="card in phaseStats"
            :key="card.label"
            class="stat-card"
            :class="{ active: card.active }"
            type="button"
            @click="applyStatFilter(card.filter)"
          >
            <span>
              <span class="stat-label">{{ card.label }}</span>
              <strong class="stat-value">{{ card.value.toLocaleString("zh-CN") }}</strong>
            </span>
            <span class="stat-hint">{{ card.hint }}</span>
          </button>
        </section>

        <section class="filter-bar">
          <select v-model="moduleFilter" class="filter-select" aria-label="模块">
            <option v-for="item in moduleOptions" :key="item" :value="item">模块：{{ item }}</option>
          </select>
          <select v-model="categoryFilter" class="filter-select" aria-label="细分类">
            <option v-for="item in categoryOptions" :key="item" :value="item">细分类：{{ item }}</option>
          </select>
          <select v-model="typeFilter" class="filter-select" aria-label="类型">
            <option v-for="item in typeOptions" :key="item" :value="item">大类：{{ item }}</option>
          </select>
          <select v-model="statusFilter" class="filter-select" aria-label="状态">
            <option v-for="item in statusOptions" :key="item" :value="item">状态：{{ statusOptionLabel(item) }}</option>
          </select>
          <select v-model.number="confidenceFilter" class="filter-select" aria-label="置信度">
            <option :value="0">置信度：全部</option>
            <option :value="0.7">置信度 ≥ 0.70</option>
            <option :value="0.8">置信度 ≥ 0.80</option>
            <option :value="0.9">置信度 ≥ 0.90</option>
          </select>
          <label class="switch-label">
            <input v-model="ambiguousOnly" type="checkbox" />
            <span>仅歧义</span>
          </label>
          <input v-model="searchText" class="search-input" type="search" placeholder="搜索需求、对象或编号" />
          <button
            class="button batch-accept-button"
            type="button"
            :disabled="isBatchAccepting || batchAcceptCandidates.length === 0 || !apiClient"
            data-testid="batch-accept-high-confidence"
            @click="batchAcceptHighConfidence"
          >
            <CheckCheck :size="15" aria-hidden="true" />
            {{ isBatchAccepting ? '接受中' : `批量接受 ${batchAcceptCandidates.length}` }}
          </button>
        </section>

        <section
          v-if="visibleTableReviews.length"
          class="table-review-band"
          data-testid="table-review-band"
          aria-label="表格结构复核"
        >
          <header class="table-review-band-head">
            <span class="table-review-band-title">
              <AlertTriangle :size="16" aria-hidden="true" />
              表格结构复核
            </span>
            <span>{{ pendingTableReviewCount }} 张待确认</span>
          </header>
          <div
            v-for="table in visibleTableReviews"
            :key="table.table_id"
            class="table-review-row"
            :data-testid="`table-review-${table.table_id}`"
          >
            <div class="table-review-summary">
              <strong>{{ table.title || table.table_id }}</strong>
              <span>{{ table.table_id }} · {{ table.cell_count }} 格</span>
              <span v-if="table.review_mode === 'llm_assisted'" class="table-review-audit">LLM 辅助，审计只读</span>
              <span v-else>{{ table.review_count }} 格待定</span>
            </div>
            <div v-if="table.structure_review_status === 'pending'" class="table-review-decisions">
              <label
                v-for="cell in table.cells.filter((item) => item.disposition === 'review')"
                :key="cell.cell_id"
                class="table-review-cell"
              >
                <span class="table-review-cell-source">
                  R{{ cell.row_index || 0 }}C{{ cell.column_index || 0 }}
                  <b>{{ cell.text || '空白单元格' }}</b>
                </span>
                <select
                  v-model="tableReviewDrafts[table.table_id][cell.cell_id].disposition"
                  :aria-label="`${cell.cell_id} Claim 裁决`"
                >
                  <option v-for="option in tableDispositionOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                </select>
              </label>
            </div>
            <button
              v-if="table.structure_review_status === 'pending'"
              class="button table-review-confirm"
              type="button"
              :disabled="submittingTableReviewId === table.table_id"
              :data-testid="`confirm-table-${table.table_id}`"
              @click="confirmTableReview(table)"
            >
              <Check :size="15" aria-hidden="true" />
              {{ submittingTableReviewId === table.table_id ? '保存中' : '确认整表结构' }}
            </button>
          </div>
        </section>

        <section class="workspace right-detail-workspace" data-testid="workspace">
          <section class="table-panel">
            <div class="panel-head">
              <div>
                <div class="panel-title">需求表格</div>
                <div class="panel-subtitle">中文界面显示，底层状态与类型仍按后端原值处理</div>
              </div>
              <div class="panel-subtitle">{{ tableFooterText }}</div>
            </div>

            <div
              ref="requirementTableScroll"
              class="table-wrap independent-table-scroll"
              data-testid="requirement-table"
              @scroll="handleRequirementTableScroll"
            >
              <table>
                <thead>
                  <tr>
                    <th class="col-id">编号</th>
                    <th class="col-module">模块</th>
                    <th class="col-category">细分类</th>
                    <th class="col-type">大类</th>
                    <th class="col-object">对象</th>
                    <th>需求</th>
                    <th class="col-confidence">置信度</th>
                    <th class="col-status">状态</th>
                    <th class="col-amb">歧义</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="filteredRequirements.length === 0" data-testid="empty-requirements">
                    <td class="empty-cell" colspan="9">当前输出目录暂无需求</td>
                  </tr>
                  <tr v-if="virtualTopHeight > 0" class="virtual-spacer" aria-hidden="true">
                    <td colspan="9" :style="{ height: `${virtualTopHeight}px` }"></td>
                  </tr>
                  <tr
                    v-for="row in visibleRequirementRows"
                    :key="row.id"
                    :class="{ selected: row.id === selectedRequirementId }"
                    :data-testid="`row-${row.id}`"
                    @click="selectRequirement(row.id)"
                  >
                    <td class="id-cell">{{ row.id }}</td>
                    <td><span class="module-chip">{{ row.module || "未分模块" }}</span></td>
                    <td><span class="category-chip" :title="row.categoryCode">{{ row.category || row.categoryCode || "未分类" }}</span></td>
                    <td><span class="type-tag" :class="typeToneClass(row.type)">{{ row.type }}</span></td>
                    <td>{{ row.object }}</td>
                    <td><div class="requirement-cell">{{ row.chineseText }}</div></td>
                    <td><div class="confidence-cell">{{ row.confidence.toFixed(2) }}</div></td>
                    <td>
                      <span class="status-tag" :class="statusToneClass(row.status)" :data-testid="`row-status-${row.id}`">{{ statusDisplay(row.status) }}</span>
                    </td>
                    <td><span class="ambiguity-tag" :class="riskToneClass(row.ambiguity.level)">{{ row.ambiguity.level }}</span></td>
                  </tr>
                  <tr v-if="virtualBottomHeight > 0" class="virtual-spacer" aria-hidden="true">
                    <td colspan="9" :style="{ height: `${virtualBottomHeight}px` }"></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <aside class="detail-panel" data-testid="detail-panel">
            <div class="panel-head">
              <div>
                <div class="panel-title" data-testid="detail-title">{{ selectedRequirement.id }}</div>
                <div class="panel-subtitle">{{ selectedRequirement.object }} · {{ selectedRequirement.sourceDocument }}</div>
              </div>
              <span class="status-tag" :class="statusToneClass(selectedRequirement.status)" data-testid="detail-status">{{ statusDisplay(selectedRequirement.status) }}</span>
            </div>

            <div class="detail-content independent-detail-scroll" data-testid="detail-scroll">
              <section class="readonly-card">
                <div class="readonly-head">① 原始需求</div>
                <div class="readonly-body">{{ selectedRequirement.originalText }}</div>
              </section>

              <section class="readonly-card">
                <div class="readonly-head">
                  <span>② 中文翻译</span>
                  <button
                    class="mini-button"
                    type="button"
                    data-testid="action-translate"
                    :disabled="isTranslating || !hasSelectedRequirement"
                    @click="handleTranslate"
                  >
                    {{ isTranslating ? "翻译中" : "翻译" }}
                  </button>
                </div>
                <div class="readonly-body muted" data-testid="translation-text">{{ translationText }}</div>
              </section>

              <section class="readonly-card">
                <div class="readonly-head">③ 原子化需求</div>
                <div class="readonly-body">{{ atomizedRequirementText }}</div>
              </section>

              <section class="metadata">
                <div v-for="item in metadataRows" :key="item.key" class="metadata-item">
                  <span class="metadata-key">{{ item.key }}</span>
                  <strong class="metadata-value">{{ item.value }}</strong>
                </div>
              </section>

              <section class="mini-row">
                <div class="mini-head">溯源原文</div>
                <div class="mini-body">{{ selectedRequirement.sourceDocument }} · {{ selectedRequirement.sourceLocation }}</div>
              </section>

              <section class="mini-row">
                <div class="mini-head">知识库匹配</div>
                <div class="mini-body">{{ knowledgeMatches }}</div>
              </section>

              <section class="mini-row">
                <div class="mini-head">领域标签</div>
                <div class="mini-body">{{ domainTagText }}</div>
              </section>

              <section class="mini-row">
                <div class="mini-head">来源章节</div>
                <div class="mini-body">{{ sectionPathText }}</div>
              </section>

              <section class="review-box">
                <div class="mini-head">评审</div>
                <div class="review-body">
                  <p>裁决：{{ statusDisplay(selectedRequirement.status) }}</p>
                  <p>风险：{{ selectedRequirement.ambiguity.level }} 风险</p>
                  <p>{{ reviewNote }}</p>
                  <ul v-if="selectedRequirement.ambiguity.reasons.length > 0" class="bullet-list">
                    <li v-for="reason in selectedRequirement.ambiguity.reasons" :key="reason">{{ reason }}</li>
                  </ul>
                </div>
              </section>

              <div class="detail-actions">
                <button class="button decision-accept" type="button" :disabled="isSubmitting || !apiClient" data-testid="decision-accepted" @click="updateStatus('accepted')"><Check :size="15" aria-hidden="true" />接受</button>
                <button class="button decision-reject" type="button" :disabled="isSubmitting || !apiClient" data-testid="decision-rejected" @click="updateStatus('rejected')"><Ban :size="15" aria-hidden="true" />拒绝</button>
                <button class="button" type="button" :disabled="isSubmitting || !apiClient" @click="updateStatus('needs_discussion')"><MessagesSquare :size="15" aria-hidden="true" />讨论</button>
                <button class="button" type="button" :disabled="isSubmitting || !apiClient" @click="updateStatus('expert_pending')"><UserRound :size="15" aria-hidden="true" />专家</button>
              </div>
              <textarea v-model="reviewComment" class="comment-box" placeholder="请输入审查意见" />
              <div v-if="apiMessage" class="api-message" data-testid="api-message">{{ apiMessage }}</div>
            </div>
          </aside>
        </section>
        </template>
        <DocumentReview v-else-if="activeNav === 'document'" :client="apiClient" :session-key="reviewSessionKey"
                        :active="activeNav === 'document'" :refresh-token="documentRefreshToken"
                        :focus-block-id="documentFocusBlockId" />
        <ClaimLedger v-else-if="activeNav === 'claim'" :client="apiClient" :session-key="reviewSessionKey"
                     :active="activeNav === 'claim'" :refresh-token="documentRefreshToken" />
        <FunctionalReview v-else-if="activeNav === 'functional'" :client="apiClient" :session-key="reviewSessionKey"
                          :active="activeNav === 'functional'" :refresh-token="documentRefreshToken"
                          :output-dir="currentOutputDir" @focus-block="focusBlockFromFunctional" />
        <DocumentRenderer v-else-if="activeNav === 'renderer'" :file-path="currentInputPath || ''"
                          :client="apiClient ? {} : null" :active="activeNav === 'renderer'"
                          :is-scanned="rendererScanned" :scanned-source="rendererScannedSource"
                          :annotations="rendererAnnotations" :load-bytes="loadBytesForRenderer"
                          @fallback="onRendererFallback" />

        <footer class="status-bar">
          <span :title="currentOutputDir || undefined">输出目录：{{ currentOutputDir ? tailPath(currentOutputDir) : "尚未选择输出目录" }}</span>
          <span class="kbd-hints"><ShieldCheck :size="13" aria-hidden="true" />本地审查会话</span>
        </footer>
      </main>

      <Transition name="sheet">
      <div
        v-if="showSettingsPanel"
        class="settings-overlay"
        data-testid="settings-panel"
        role="dialog"
        aria-modal="true"
        aria-label="设置"
        @click.self="closeSettingsPanel"
      >
        <section class="settings-dialog">
          <header class="settings-head">
            <div>
              <div class="settings-title">设置</div>
              <div class="settings-subtitle">本地运行、LLM 富化和 ABNT 预设</div>
            </div>
            <button class="icon-button" type="button" data-testid="settings-close" aria-label="关闭设置" title="关闭设置" @click="closeSettingsPanel"><X :size="18" aria-hidden="true" /></button>
          </header>

          <div class="settings-body">
            <section class="settings-section">
              <div class="settings-section-title">交付物（业务目标）</div>
              <div class="settings-form-grid">
                <label class="settings-field">
                  <span>翻译交付模式</span>
                  <select v-model="translationMode" data-testid="settings-translation-mode">
                    <option value="full">全文双语交付（默认）</option>
                    <option value="markers">仅批注标记翻译</option>
                    <option value="off">关闭翻译（零翻译调用）</option>
                  </select>
                </label>
              </div>
              <p class="settings-hint">选择要交付什么：需求列表 / COSEM 规格按下方「交付阶段」自动决定；技术路径（A/B 轨）由系统自动路由，无需手动选择。</p>
            </section>
            <section class="settings-section">
              <div class="settings-section-title">交付阶段</div>
              <label class="settings-toggle">
                <input v-model="runStages.analyze" type="checkbox" data-testid="stage-analyze" />
                <span><strong>软件需求分析</strong><small>软/硬/协同归属 + software_requirements.xlsx。<em>依赖 AI 抽取</em>。</small></span>
              </label>
              <label class="settings-toggle">
                <input v-model="runStages.compose" type="checkbox" data-testid="stage-compose" />
                <span><strong>组装工程需求</strong><small>装配实现规格（对象表事实 / DLMS 对象），不是把碎原子拼成需求。</small></span>
              </label>
              <label class="settings-toggle">
                <input v-model="runStages.annotationHtml" type="checkbox" data-testid="stage-annotation-html" />
                <span><strong>导出批注 HTML</strong><small>生成 document_annotation.html，用于专家离线阅读、批注和导出裁决 JSON。</small></span>
              </label>
              <div class="template-row">
                <span class="field-label">需求列表模板（xlsx，选填）</span>
                <input :value="templatePath" readonly placeholder="未设置——设置后分析结果按公司模板格式成文" data-testid="template-path" />
                <button class="button" type="button" data-testid="template-pick" @click="handleSelectTemplate"><FolderOpen :size="15" aria-hidden="true" />选择</button>
                <button class="button" type="button" :disabled="!templatePath" @click="templatePath = ''"><Trash2 :size="15" aria-hidden="true" />清除</button>
              </div>
              <p class="settings-hint">LLM 富化跟随下方「LLM 富化」开关：开→AI 抽取/装配/分析走 openai_compatible，关→纯确定性。</p>
            </section>
            <details class="settings-section settings-advanced" data-testid="settings-advanced">
              <summary>高级：执行阶段（诊断 / 轨道对照用，普通交付无需调整）</summary>
              <div class="settings-section-title">轨道阶段（A/B 技术选择）</div>
              <label class="settings-toggle">
                <input v-model="runStages.llmReview" type="checkbox" data-testid="stage-llm-review" />
                <span><strong>LLM 审查（规则候选复核）</strong><small>默认关闭。逐条复核规则切出的碎原子——不再是需求产品。仅在对照旧 DLMS 规则候选时打开。</small></span>
              </label>
              <label class="settings-toggle">
                <input v-model="runStages.aiExtract" type="checkbox" data-testid="stage-ai-extract" />
                <span><strong>AI 抽取（双引擎）</strong><small>LLM 行为需求 + 确定性结构合并，产 merged_spec 与一致性报表。</small></span>
              </label>
              <label class="settings-toggle">
                <input v-model="runStages.assemble" type="checkbox" data-testid="stage-assemble" />
                <span><strong>装配实现规格</strong><small>P1-P3 装配《DLMS/COSEM 实现规格》JSON + Word/MD/Excel。</small></span>
              </label>
              <label class="settings-toggle">
                <input v-model="showAtomDiagnostics" type="checkbox" data-testid="settings-show-atom-diagnostics" />
                <span><strong>显示原子诊断</strong><small>侧栏出现「原子诊断」（旧审查工作台）。碎原子不是需求产品，仅对照旧结果时打开。</small></span>
              </label>
            </details>
            <section class="settings-section">
              <div class="settings-section-title">运行模式与模型 API</div>
              <label class="settings-toggle">
                <input v-model="llmMode" type="checkbox" data-testid="settings-llm-mode" />
                <span>
                  <strong>LLM 富化</strong>
                  <small>开启后，翻译、装配规格富化和后续 LLM 审查都使用 openai_compatible 配置。</small>
                </span>
              </label>
              <div class="settings-form-grid">
                <label class="settings-field wide">
                  <span>Base URL</span>
                  <input v-model="llmSettings.baseUrl" data-testid="settings-base-url" type="url" placeholder="http://127.0.0.1:11434/v1" />
                </label>
                <label class="settings-field">
                  <span>模型名</span>
                  <input v-model="llmSettings.model" data-testid="settings-model" type="text" placeholder="qwen2.5:14b" />
                </label>
                <label class="settings-field">
                  <span>API Key 环境变量</span>
                  <input v-model="llmSettings.apiKeyEnv" data-testid="settings-api-key-env" type="text" placeholder="RATOMIZER_LLM_API_KEY" />
                </label>
                <label class="settings-field wide">
                  <span>API Key</span>
                  <input v-model="llmApiKey" data-testid="settings-api-key" type="password" placeholder="加密保存到本机配置文件" />
                </label>
                <label class="settings-field">
                  <span>Temperature</span>
                  <input v-model.number="llmSettings.temperature" data-testid="settings-temperature" type="number" min="0" max="2" step="0.1" />
                </label>
                <label class="settings-field">
                  <span>Max Tokens</span>
                  <input v-model.number="llmSettings.maxTokens" data-testid="settings-max-tokens" type="number" min="1" step="1" />
                </label>
                <label class="settings-field">
                  <span>超时（秒）</span>
                  <input v-model.number="llmSettings.timeoutS" data-testid="settings-timeout" type="number" min="1" step="1" />
                </label>
                <label class="settings-field">
                  <span>重试次数</span>
                  <input v-model.number="llmSettings.maxRetries" data-testid="settings-max-retries" type="number" min="0" step="1" />
                </label>
                <label class="settings-field">
                  <span>AI 抽取并发</span>
                  <input v-model.number="llmSettings.concurrency" data-testid="settings-concurrency" type="number" min="1" max="16" step="1" title="AI 抽取同时调用 LLM 的章节数；端点限流(429)时调低到 1-2" />
                </label>
              </div>
              <label class="settings-toggle">
                <input v-model="llmSettings.selfCheck" type="checkbox" data-testid="settings-self-check" />
                <span>
                  <strong>完整性自检</strong>
                  <small>AI 抽取每章节后再查漏补缺一次，直击"不遗漏"；约 2× 调用成本，关闭可省。</small>
                </span>
              </label>
              <div class="settings-actions">
                <button class="button primary" type="button" data-testid="settings-save" :disabled="isSavingSettings" @click="handleSaveLlmSettings">
                  <RefreshCw v-if="isSavingSettings" class="spin" :size="15" aria-hidden="true" /><Save v-else :size="15" aria-hidden="true" />{{ isSavingSettings ? "保存中" : "保存配置" }}
                </button>
                <button class="button" type="button" data-testid="settings-test" :disabled="isTestingSettings" @click="handleTestLlmConnection">
                  <RefreshCw v-if="isTestingSettings" class="spin" :size="15" aria-hidden="true" /><PlugZap v-else :size="15" aria-hidden="true" />{{ isTestingSettings ? "测试中" : "测试连接" }}
                </button>
                <button class="button" type="button" data-testid="settings-open-logs" @click="handleOpenLogs"><FolderOpen :size="15" aria-hidden="true" />打开日志目录</button>
                <span class="settings-status" data-testid="settings-status">{{ settingsStatus }}</span>
              </div>
            </section>

            <section class="settings-section">
              <div class="settings-section-title">当前会话</div>
              <div class="settings-row">
                <span>API 连接</span>
                <strong>{{ apiClient ? "已连接" : "未连接" }}</strong>
              </div>
              <div class="settings-row">
                <span>导入文档</span>
                <strong>{{ currentInputPath || "尚未选择" }}</strong>
              </div>
              <div class="settings-row">
                <span>输出目录</span>
                <strong>{{ currentOutputDir || "尚未选择" }}</strong>
              </div>
            </section>

            <section class="settings-section">
              <div class="settings-section-title">ABNT 默认预设</div>
              <div class="settings-row">
                <span>切片长度</span>
                <strong>{{ abntPreset.chunkChars.toLocaleString("zh-CN") }} 字符</strong>
              </div>
              <div class="settings-row">
                <span>领域包</span>
                <strong>{{ abntPreset.domainPackDir }}</strong>
              </div>
              <div class="settings-kb-list">
                <span>知识库</span>
                <ul>
                  <li v-for="path in abntPreset.kbPaths" :key="path">{{ path }}</li>
                </ul>
              </div>
            </section>
          </div>
        </section>
      </div>
      </Transition>
    </div>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch, type Component } from "vue"
import { NConfigProvider } from "naive-ui"
import {
  Ban,
  AlertTriangle,
  Braces,
  Check,
  CheckCheck,
  ChevronRight,
  CircleHelp,
  ClipboardCheck,
  Download,
  ExternalLink,
  FileSpreadsheet,
  FileText,
  FlaskConical,
  FolderOpen,
  FolderOutput,
  History,
  Image,
  Layers,
  MessageSquareReply,
  MessagesSquare,
  ListChecks,
  Play,
  PlugZap,
  RefreshCw,
  Save,
  ScanSearch,
  Settings,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  UserRound,
  X,
} from "@lucide/vue"
import { isNeedsReconfirmationError, RequirementApiClient, RequirementApiError } from "./api-client"
import type {
  TableCellDisposition,
  TableCellRole,
  TableReviewRoleMapping,
  TableReviewTable,
} from "./api-client"
import ClaimLedger from "./ClaimLedger.vue"
import DocumentRenderer from "./DocumentRenderer.vue"
import DocumentReview from "./DocumentReview.vue"
import FunctionalReview from "./FunctionalReview.vue"
import { requirements as mockRequirements } from "./mock-data"
import { applyReviewState, mapBackendRequirement, statusDisplay as displayStatus } from "./requirement-mapper"
import type { Requirement, ReviewStatus } from "./types"

type PhaseNavId = "run" | "review" | "document" | "claim" | "functional" | "renderer" | "settings"
type StatFilter = "all" | "accepted" | "expert_pending" | "ambiguous"
type LlmSettings = {
  enabled: boolean
  visionCapable: boolean
  baseUrl: string
  model: string
  apiKeyEnv: string
  temperature: number
  maxTokens: number
  timeoutS: number
  maxRetries: number
  concurrency: number
  selfCheck: boolean
}

type PhaseNavItem = { id: PhaseNavId; label: string; icon: Component; group: string; navTestId: string }
const phaseNavItems: PhaseNavItem[] = [
  { id: "run", label: "运行", icon: Play, group: "运行", navTestId: "运行" },
  { id: "functional", label: "功能需求", icon: Layers, group: "评审", navTestId: "功能需求" },
  { id: "review", label: "原子诊断", icon: ClipboardCheck, group: "评审", navTestId: "审查工作台" },
  { id: "document", label: "文档批注", icon: FileText, group: "原文与审计", navTestId: "文档批注" },
  { id: "claim", label: "覆盖审计", icon: ListChecks, group: "原文与审计", navTestId: "覆盖审计" },
  { id: "renderer", label: "文档渲染", icon: Image, group: "原文与审计", navTestId: "文档渲染" },
  { id: "settings", label: "设置", icon: Settings, group: "设置", navTestId: "设置" },
]

const SHOW_ATOM_DIAGNOSTICS_KEY = "ratomizer.showAtomDiagnostics.v1"
function loadShowAtomDiagnostics(): boolean {
  try {
    return (typeof localStorage !== "undefined" ? localStorage.getItem(SHOW_ATOM_DIAGNOSTICS_KEY) : null) === "1"
  } catch {
    return false
  }
}
const showAtomDiagnostics = ref(loadShowAtomDiagnostics())
watch(showAtomDiagnostics, (value) => {
  try {
    localStorage?.setItem(SHOW_ATOM_DIAGNOSTICS_KEY, value ? "1" : "0")
  } catch {
    /* 持久化失败忽略 */
  }
  if (!value && activeNav.value === "review") activeNav.value = "functional"
})

// 日常侧栏：评审正门只有「功能需求」。原子诊断（旧审查工作台）默认隐藏，
// 路由 review 与 testid nav-审查工作台保留，打开「显示原子诊断」后才出现。
const navGroups = computed(() => {
  const order = ["运行", "评审", "原文与审计"]
  const map = new Map<string, PhaseNavItem[]>()
  for (const item of phaseNavItems) {
    if (item.id === "settings") continue
    if (item.id === "review" && !showAtomDiagnostics.value) continue
    const list = map.get(item.group) ?? []
    list.push(item)
    map.set(item.group, list)
  }
  return order.filter((g) => map.has(g)).map((g) => ({ title: g, items: map.get(g)! }))
})

// 落地页默认「功能需求」评审视图（G9-4）：运行入口保留在 nav，用户点「运行」即进入。
// 此前落地为「运行」，但功能需求评审是高频评审面；FunctionalReview 自带 functional 模式，
// 默认落它不破运行入口（nav 仍可达，且 demoProgress URL 演示显式切回 run）。
const activeNav = ref<PhaseNavId>("functional")
// 运行页总览（样机 2026-07-09）：跑完链后填充,未知显示 —
const runOverview = ref<{
  functionalReqs: number | null
  selfCheck: number | null
  coverage: number | null
  chapters: string
  questions: number | null
  verdict: string
  deliverableHint: string
}>({
  functionalReqs: null, selfCheck: null, coverage: null, chapters: "",
  questions: null, verdict: "", deliverableHint: "",
})
const lastStageNotes = ref<string[]>([])
// 裁决复盘建议（E5）：专家改判模式 ≥3 次提炼的规则改进建议——此前产物零消费者
const reviewInsights = ref<string[]>([])
const tableReviews = ref<TableReviewTable[]>([])
const tableReviewDrafts = ref<Record<string, TableReviewRoleMapping>>({})
const submittingTableReviewId = ref("")
const visibleTableReviews = computed(() => tableReviews.value.filter((table) =>
  table.structure_review_status === "pending" || table.review_mode === "llm_assisted",
))
const pendingTableReviewCount = computed(() => tableReviews.value.filter(
  (table) => table.structure_review_status === "pending",
).length)
const tableRoleOptions: Array<{ value: TableCellRole; label: string }> = [
  { value: "title", label: "标题" },
  { value: "header", label: "表头" },
  { value: "row_header", label: "行头" },
  { value: "group_header", label: "分组标题" },
  { value: "data", label: "数据" },
  { value: "note", label: "备注" },
  { value: "unknown", label: "未知" },
]
const tableDispositionOptions: Array<{ value: TableCellDisposition; label: string }> = [
  { value: "target", label: "提升为需求" },
  { value: "excluded", label: "确认排除" },
]
const DELIVERABLE_FILES = [
  { key: "software", icon: FileSpreadsheet, tone: "xls", name: "软件需求列表-成文.xlsx", hint: "V2.3.x 模板成文（B 轨主交付物）" },
  { key: "annotation", icon: FileText, tone: "htm", name: "document_annotation.html", hint: "批注视图 · 分享给专家离线裁决" },
  { key: "clarification", icon: CircleHelp, tone: "xls", name: "clarification_questions.xlsx", hint: "必答澄清 · 问客户/内部核对" },
  { key: "manifest", icon: Braces, tone: "jsn", name: "run_manifest.json", hint: "阶段台账 · 路由与续跑依据" },
] as const
async function openDeliverable(name: string) {
  if (!currentOutputDir.value) {
    apiMessage.value = "尚未选择输出目录——先运行或打开一个输出目录"
    return
  }
  if (name === "document_annotation.html") {
    void handleExportAnnotationHtml()   // 幂等重渲染,保证打开最新
    return
  }
  try {
    await window.ratomizerDesktop?.openPath?.(currentOutputDir.value + "\\" + name)
  } catch (error) {
    apiMessage.value = error instanceof Error ? error.message : `打开 ${name} 失败（可能尚未生成）`
  }
}

const activeNavLabel = computed(
  () => phaseNavItems.find((i) => i.id === activeNav.value)?.label || "审查")
const llmMode = ref(false)
const apiClient = ref<RequirementApiClient | null>(null)
const reviewSessionKey = ref("")
const recentSessions = ref<RequirementAtomizerRecentSession[]>([])
type ResultPackageStatus = "unknown" | "legacy" | "running" | "incomplete" | "completed"
const resultPackageStatus = ref<ResultPackageStatus>("unknown")
const resultPackageStatusLabel = computed(() => ({
  unknown: "自动分析：尚未运行",
  legacy: "自动分析：旧版结果",
  running: "自动分析：运行中",
  incomplete: "自动分析：未完成",
  completed: "自动分析：已完成",
})[resultPackageStatus.value])
const documentRefreshToken = ref(0)
// F4：functional 评审来源块跳转传入的块 id——DocumentReview 据此滚动+高亮（空串=无定位）
const documentFocusBlockId = ref("")
// G 展示层：渲染器叠加层数据 + 扫描件徽标。渲染视图激活时从既有 /document/pdf 通道加载，
// 让标注叠加层与扫描件徽标在真实使用路径可见（旧版 App.vue 从不传 isScanned/annotations，仅单测可达）。
const rendererAnnotations = ref<Record<string, number>>({})
const rendererScanned = ref(false)
const rendererScannedSource = ref("")
let rendererMetaGeneration = 0
let apiSessionLoadGeneration = 0
// loadInitialApiSession 轮询的取消标志：onUnmounted 置 true 取消遗留轮询，onMounted
// 复位 false 放行新挂载实例；跨挂载的陈旧轮询由 generation guard 兜底（见 loadInitialApiSession）。
let apiSessionPollingCancelled = false
let stopApiSessionReady: (() => void) | undefined
const apiMessage = ref("")
const apiMessageExpanded = ref(false)
watch(apiMessage, () => { apiMessageExpanded.value = false })
const currentInputPath = ref("")
const currentOutputDir = ref("")
const isRunning = ref(false)
const isTranslating = ref(false)
const isSubmitting = ref(false)
const reviewComment = ref("")
const showSettingsPanel = ref(false)
const isSavingSettings = ref(false)
const isTestingSettings = ref(false)
const translationError = ref("")
const settingsStatus = ref("")
const llmApiKey = ref("")
const llmSettings = ref<LlmSettings>({
  enabled: false,
  visionCapable: false,
  baseUrl: "http://127.0.0.1:11434/v1",
  model: "qwen2.5:14b",
  apiKeyEnv: "RATOMIZER_LLM_API_KEY",
  temperature: 0,
  maxTokens: 4096,
  timeoutS: 60,
  maxRetries: 3,
  concurrency: 8,
  selfCheck: true,
})
// 「运行」时依次执行的阶段（基础解析+审查后追加）。可选配置、localStorage 持久化。
type RunStages = {
  llmReview: boolean
  aiExtract: boolean
  assemble: boolean
  analyze: boolean
  compose: boolean
  annotationHtml: boolean
}
// v3（2026-08-19）：碎原子不再是需求产品——llmReview 默认关。换键让旧 v2（llmReview:true）
// 一次性拿到新默认；用户仍可在高级区打开原子审查。代价是自定义阶段重置一次。
const RUN_STAGES_KEY = "ratomizer.runStages.v3"
function loadRunStages(): RunStages {
  const fallback: RunStages = {
    llmReview: false,
    aiExtract: true,
    assemble: true,
    analyze: true,
    compose: true,
    annotationHtml: true,
  }
  try {
    const raw = typeof localStorage !== "undefined" ? localStorage.getItem(RUN_STAGES_KEY) : null
    if (raw) return { ...fallback, ...JSON.parse(raw) }
  } catch {
    /* 读取失败回落默认 */
  }
  return fallback
}
const runStages = ref<RunStages>(loadRunStages())
watch(runStages, (value) => {
  try {
    localStorage?.setItem(RUN_STAGES_KEY, JSON.stringify(value))
  } catch {
    /* 持久化失败忽略，不影响本次运行 */
  }
}, { deep: true })

// §20.1 业务交付设置：翻译交付模式（off=零翻译调用 / markers=只翻批注 / full=全文双语）。
// 默认 full=既有行为；off/markers 由后端链强制（M6：全文翻译阶段拿掉 + export 零 marker 调用）。
type TranslationMode = "off" | "markers" | "full"
const TRANSLATION_MODE_KEY = "ratomizer.translationMode.v1"
function loadTranslationMode(): TranslationMode {
  try {
    const raw = typeof localStorage !== "undefined" ? localStorage.getItem(TRANSLATION_MODE_KEY) : null
    if (raw === "off" || raw === "markers" || raw === "full") return raw
  } catch {
    /* 读取失败回落默认 */
  }
  return "full"
}
const translationMode = ref<TranslationMode>(loadTranslationMode())
watch(translationMode, (value) => {
  try {
    localStorage?.setItem(TRANSLATION_MODE_KEY, value)
  } catch {
    /* 持久化失败忽略 */
  }
})

// §20.3 单元路由进度（shadow 只读）：运行后从 /unit-routing 拉取计数摘要
const unitRoutingSummary = ref("")
async function refreshUnitRouting(): Promise<void> {
  const client = apiClient.value
  if (!client) return
  try {
    const payload = await client.loadUnitRouting()
    if (!payload.available || !payload.routing) {
      unitRoutingSummary.value = ""
      return
    }
    const counts = payload.routing.counts_by_route || {}
    unitRoutingSummary.value =
      `单元路由（自动解析，待审不阻塞交付）：共 ${payload.routing.unit_count} 单元 —` +
      ` 结构化 ${counts.a_track ?? 0} / 行为 ${counts.b_track ?? 0} / 混合 ${counts.mixed ?? 0} /` +
      ` 上下文 ${counts.context ?? 0} / 待专家 ${counts.review ?? 0}`
  } catch {
    unitRoutingSummary.value = ""
  }
}

// 公司标准化需求列表模板（V2.3.x）：设置后 analyze 用其词表，且分析结果按模板格式成文
const TEMPLATE_PATH_KEY = "ratomizer.templatePath"
const templatePath = ref<string>((() => {
  try { return localStorage?.getItem(TEMPLATE_PATH_KEY) || "" } catch { return "" }
})())
watch(templatePath, (value) => {
  try { localStorage?.setItem(TEMPLATE_PATH_KEY, value || "") } catch { /* 忽略 */ }
})
async function handleSelectTemplate() {
  const bridge = window.ratomizerDesktop
  if (!bridge?.selectTemplate) return
  const picked = await bridge.selectTemplate()
  if (picked) templatePath.value = picked
}

const runProgress = ref(0)
const runStage = ref("待运行")
const runProgressDetail = ref("等待开始")
const latestTaskSummary = ref<Record<string, unknown> | null>(null)

type RunStageStatus = "pending" | "running" | "ok" | "skipped" | "failed" | "disabled"
type RunStageState = { status: RunStageStatus; percent: number; detail: string }
type RelayConnectorStatus = "idle" | "ready" | "handoff" | "complete" | "bypass" | "blocked"
const RUN_STAGE_DEFS = [
  { key: "atomize", label: "原子化" },
  { key: "llm-review", label: "LLM审核" },
  { key: "ai-extract", label: "AI抽取" },
  { key: "functional-synthesis", label: "功能重组" },
  { key: "assemble", label: "组装功能" },
  { key: "requirements-analysis", label: "需求分析" },
  { key: "template-write", label: "格式成文" },
  { key: "clarification-report", label: "澄清清单" },
  { key: "full-translation", label: "全文翻译" },
  { key: "compose", label: "工程组装" },
  { key: "export-annotation-html", label: "HTML导出" },
] as const
type RunStageKey = typeof RUN_STAGE_DEFS[number]["key"]

function defaultStageStates(): Record<RunStageKey, RunStageState> {
  return Object.fromEntries(RUN_STAGE_DEFS.map((item) => [
    item.key,
    { status: "pending" as RunStageStatus, percent: 0, detail: "待完成" },
  ])) as Record<RunStageKey, RunStageState>
}

// 单章 LLM 调用可能长达数分钟且无中间进度事件——用"距上次事件时长"区分"慢"与"死"
const STALL_THRESHOLD_S = 60
const nowTick = ref(Date.now())
const lastProgressEventAt = ref(0)
const stageStartedAt = ref<Record<string, number>>({})
let heartbeatTimer: ReturnType<typeof setInterval> | undefined

function formatDuration(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes <= 0) return `${seconds} 秒`
  return `${minutes} 分 ${String(seconds).padStart(2, "0")} 秒`
}

function tailPath(p: string, segments = 2) {
  const parts = p.split(/[\\/]+/).filter(Boolean)
  return parts.length <= segments ? p : `…\\${parts.slice(-segments).join("\\")}`
}

const runStageStates = ref<Record<RunStageKey, RunStageState>>(defaultStageStates())
const isCompletedStage = (status: RunStageStatus) => status === "ok" || status === "skipped"

function relayConnectorStatus(current: RunStageState, next: RunStageState): RelayConnectorStatus {
  if (current.status === "failed") return "blocked"
  if (next.status === "running" && (isCompletedStage(current.status) || current.status === "disabled")) return "handoff"
  if (current.status === "disabled" || next.status === "disabled") return "bypass"
  if (isCompletedStage(current.status) && isCompletedStage(next.status)) return "complete"
  if (current.status === "running" || isCompletedStage(current.status)) return "ready"
  return "idle"
}

const runStageCards = computed(() => RUN_STAGE_DEFS.map((item, index) => {
  const state = runStageStates.value[item.key]
  const nextDefinition = RUN_STAGE_DEFS[index + 1]
  const nextState = nextDefinition ? runStageStates.value[nextDefinition.key] : null
  const startedAt = stageStartedAt.value[item.key] || 0
  const elapsedS = state.status === "running" && startedAt
    ? Math.max(0, Math.floor((nowTick.value - startedAt) / 1000)) : 0
  const idleS = state.status === "running" && lastProgressEventAt.value
    ? Math.max(0, Math.floor((nowTick.value - lastProgressEventAt.value) / 1000)) : 0
  return {
    ...item,
    ...state,
    statusText: stageStatusText(state),
    relayStatus: nextState ? relayConnectorStatus(state, nextState) : null,
    elapsedS,
    idleS,
    stalled: idleS >= STALL_THRESHOLD_S,
  }
}))

function stageStatusText(state: RunStageState) {
  if (state.status === "ok") return "已完成"
  if (state.status === "skipped") return "已完成，已跳过"
  if (state.status === "running") return `运行中 ${Math.round(state.percent)}%`
  if (state.status === "failed") return "失败"
  if (state.status === "disabled") return "未启用"
  return "待完成"
}

const runStallHint = computed(() => {
  const stalledCard = runStageCards.value.find((card) => card.stalled)
  if (!stalledCard) return ""
  return `「${stalledCard.label}」已 ${formatDuration(stalledCard.idleS)} 无新进度——单章 LLM 调用可能较慢，仍在等待响应`
})

function setRunStageState(key: string | undefined, patch: Partial<RunStageState>) {
  if (!key || !(key in runStageStates.value)) return
  const stageKey = key as RunStageKey
  if (patch.status === "running") {
    lastProgressEventAt.value = Date.now()
    if (runStageStates.value[stageKey].status !== "running") {
      stageStartedAt.value = { ...stageStartedAt.value, [stageKey]: Date.now() }
    }
  }
  runStageStates.value = {
    ...runStageStates.value,
    [stageKey]: {
      ...runStageStates.value[stageKey],
      ...patch,
    },
  }
}

function failRunningStages(detail: string) {
  let changed = false
  const next = { ...runStageStates.value }
  for (const item of RUN_STAGE_DEFS) {
    const state = next[item.key]
    if (state.status !== "running") continue
    next[item.key] = { ...state, status: "failed", detail }
    changed = true
  }
  if (changed) runStageStates.value = next
}

let lastChainStep = ""   // 链步跟踪:步名变化 → 上一阶段卡片翻绿(后端完成事件不带 status)
let lastAiExtractCompleted = -1

function resetRunStageBoard() {
  lastChainStep = ""
  lastAiExtractCompleted = -1
  const next = defaultStageStates()
  if (!runStages.value.llmReview) next["llm-review"] = { status: "disabled", percent: 0, detail: "未启用" }
  if (!runStages.value.aiExtract) {
    next["ai-extract"] = { status: "disabled", percent: 0, detail: "未启用" }
    next["functional-synthesis"] = { status: "disabled", percent: 0, detail: "依赖 AI 抽取" }
  } else if (!llmMode.value) {
    next["functional-synthesis"] = { status: "disabled", percent: 0, detail: "LLM 关闭，未运行" }
  }
  if (!runStages.value.assemble) next.assemble = { status: "disabled", percent: 0, detail: "未启用" }
  if (!runStages.value.analyze) {
    next["requirements-analysis"] = { status: "disabled", percent: 0, detail: "未启用" }
    next["template-write"] = { status: "disabled", percent: 0, detail: "未启用" }
    next["clarification-report"] = { status: "disabled", percent: 0, detail: "未启用" }
  }
  if (!llmMode.value) next["full-translation"] = { status: "disabled", percent: 0, detail: "LLM 关闭，未运行" }
  if (!templatePath.value) next["template-write"] = { status: "disabled", percent: 0, detail: "未配置模板" }
  if (!runStages.value.compose) next.compose = { status: "disabled", percent: 0, detail: "未启用" }
  if (!runStages.value.annotationHtml) next["export-annotation-html"] = { status: "disabled", percent: 0, detail: "未启用" }
  runStageStates.value = next
}

const DEMO_PROGRESS_TICK_MS = 100
const DEMO_PROGRESS_STEP = 8
let progressDemoTimer: number | undefined

function stopProgressDemo() {
  if (progressDemoTimer === undefined) return
  window.clearInterval(progressDemoTimer)
  progressDemoTimer = undefined
}

function startProgressDemo() {
  stopProgressDemo()
  // demoProgress URL 的意图是预览「运行」面板的进度动效；落地页已默认 functional，
  // 故演示显式切回 run，否则演示数据在 run 面板而用户停在 functional 看不到。
  activeNav.value = "run"
  lastChainStep = ""
  runStageStates.value = defaultStageStates()
  stageStartedAt.value = {}
  lastProgressEventAt.value = Date.now()
  runProgress.value = 0
  runProgressDetail.value = "仅预览界面动效，不调用后端"
  isRunning.value = true

  let stageIndex = 0
  let stagePercent = 0
  const firstStage = RUN_STAGE_DEFS[stageIndex]
  setRunStageState(firstStage.key, { status: "running", percent: 0, detail: "演示进度" })
  runStage.value = `动效演示 1/${RUN_STAGE_DEFS.length}：${firstStage.label}`

  const reducedMotion = typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  const tickMs = reducedMotion ? 600 : DEMO_PROGRESS_TICK_MS
  const step = reducedMotion ? 100 : DEMO_PROGRESS_STEP

  progressDemoTimer = window.setInterval(() => {
    const current = RUN_STAGE_DEFS[stageIndex]
    stagePercent = Math.min(100, stagePercent + step)
    setRunStageState(current.key, {
      status: stagePercent >= 100 ? "ok" : "running",
      percent: stagePercent,
      detail: stagePercent >= 100 ? "演示完成" : "演示进度",
    })
    runProgress.value = Math.round(((stageIndex + stagePercent / 100) / RUN_STAGE_DEFS.length) * 100)

    if (stagePercent < 100) return
    stageIndex += 1
    if (stageIndex >= RUN_STAGE_DEFS.length) {
      stopProgressDemo()
      isRunning.value = false
      runStage.value = "动效演示完成"
      runProgressDetail.value = "全部阶段已完成接力"
      return
    }

    stagePercent = 0
    const next = RUN_STAGE_DEFS[stageIndex]
    setRunStageState(next.key, { status: "running", percent: 0, detail: "演示进度" })
    runStage.value = `动效演示 ${stageIndex + 1}/${RUN_STAGE_DEFS.length}：${next.label}`
  }, tickMs)
}

function shortConservationError(raw: string, limit = 180): string {
  const marker = "功能需求守恒核对未闭合"
  const idx = raw.indexOf(marker)
  const focused = idx >= 0 ? raw.slice(idx) : raw
  return focused.length > limit ? `${focused.slice(0, limit)}…` : focused
}

function applyRunManifestSummary(summary: Record<string, unknown> | null) {
  const manifest = objectValue(summary?.run_manifest)
  const stages = objectValue(manifest?.stages)
  if (!stages) return
  for (const item of RUN_STAGE_DEFS) {
    const entry = objectValue(stages[item.key])
    if (!entry) continue
    const status = String(entry.status || "")
    const lastAction = String(entry.last_action || "")
    if (status === "ok") {
      setRunStageState(item.key, {
        status: lastAction === "skipped" ? "skipped" : "ok",
        percent: 100,
        detail: lastAction === "skipped" ? "复用已有产物" : "产物已生成",
      })
    } else if (status === "partial") {
      setRunStageState(item.key, {
        status: "ok",
        percent: 100,
        detail: "产物已生成（部分条款降级，待核对）",
      })
    } else if (status === "running") {
      setRunStageState(item.key, { status: "running", percent: 0, detail: "上次中断在此阶段" })
    } else if (status === "failed") {
      const raw = String(entry.error || "上次执行失败")
      setRunStageState(item.key, {
        status: "failed",
        percent: 0,
        detail: raw.includes("功能需求守恒核对未闭合") ? shortConservationError(raw) : raw,
      })
    }
  }
}

const abntPreset = {
  chunkChars: 3500,
  // 单编译库：三个种子库的富化超集（86 条目 id 100% 继承，实证 2026-07-07），
  // 四库并载会重复命中（同一探针 10 hits 含 5 重复）——污染 kb_matches 并膨胀 prompt
  kbPaths: [
    "knowledge_bases/compiled_from_obsidian.json",
  ],
  domainPackDir: "domain_packs/dlms_cosem",
}
const TEST_LLM_REVIEW_LIMIT = 50
const TEST_AI_EXTRACT_SAMPLE_RATIO = 0.2  // 测试运行：均匀抽样全文 1/5 章节（随文档规模自适应，不写死条数）

// 空状态 UI 占位（G9-10：曾是 magic-string 哨兵，现仅用于无需求时展示文案；
// 判定改用 hasSelectedRequirement，不再读其 id 作标志）
const emptyRequirement: Requirement = {
  id: "未选择需求",
  backendId: "",
  type: "功能",
  module: "未分模块",
  moduleCode: "",
  category: "未分类",
  categoryCode: "",
  object: "-",
  chineseText: "当前输出目录暂无需求。",
  originalText: "请选择文档运行抽取，或打开包含 atomic_requirements.jsonl 的输出目录。",
  translation: "",
  sourceDocument: "-",
  sourceLocation: "-",
  domainTags: [],
  sectionPath: [],
  confidence: 0,
  risk: "低",
  status: "candidate",
  keyPoints: [],
  ambiguity: { level: "低", reasons: [] },
}

const requirementRows = ref<Requirement[]>(
  mockRequirements.map((item) => ({
    ...item,
    keyPoints: [...item.keyPoints],
    ambiguity: { ...item.ambiguity, reasons: [...item.ambiguity.reasons] },
    specMapping: item.specMapping ? { ...item.specMapping } : undefined,
  })),
)
const selectedRequirementId = ref(requirementRows.value[1].id)

const typeFilter = ref("全部")
const moduleFilter = ref("全部")
const categoryFilter = ref("全部")
const statusFilter = ref("全部")
const confidenceFilter = ref(0)
const ambiguousOnly = ref(false)
const searchText = ref("")
const requirementTableScroll = ref<HTMLElement | null>(null)
const requirementScrollTop = ref(0)
const requirementViewportHeight = ref(620)
const REQUIREMENT_ROW_HEIGHT = 79
const REQUIREMENT_OVERSCAN = 8
const isBatchAccepting = ref(false)

const typeOptions = computed(() => ["全部", ...Array.from(new Set(requirementRows.value.map((item) => item.type)))])
const moduleOptions = computed(() => ["全部", ...Array.from(new Set(requirementRows.value.map((item) => item.module || "未分模块"))).sort()])
const categoryOptions = computed(() => ["全部", ...Array.from(new Set(requirementRows.value.map((item) => item.category || item.categoryCode || "未分类"))).sort()])
const statusOptions: Array<ReviewStatus | "全部"> = ["全部", "candidate", "llm_reviewed", "accepted", "rejected", "expert_pending", "needs_discussion", "needs_rework", "flagged", "frozen"]

const filteredRequirements = computed(() => requirementRows.value.filter((item) => {
  if (moduleFilter.value !== "全部" && (item.module || "未分模块") !== moduleFilter.value) return false
  if (categoryFilter.value !== "全部" && (item.category || item.categoryCode || "未分类") !== categoryFilter.value) return false
  if (typeFilter.value !== "全部" && item.type !== typeFilter.value) return false
  if (statusFilter.value !== "全部" && item.status !== statusFilter.value) return false
  if (item.confidence < confidenceFilter.value) return false
  if (ambiguousOnly.value && item.ambiguity.level === "低") return false
  if (searchText.value) {
    const haystack = [
      item.id,
      item.type,
      item.module,
      item.moduleCode,
      item.category,
      item.categoryCode,
      item.object,
      item.chineseText,
      item.originalText,
      ...(item.domainTags || []),
      ...(item.sectionPath || []),
    ].join(" ").toLowerCase()
    if (!haystack.includes(searchText.value.toLowerCase())) return false
  }
  return true
}))

const requirementWindowStart = computed(() => Math.max(
  0,
  Math.floor(requirementScrollTop.value / REQUIREMENT_ROW_HEIGHT) - REQUIREMENT_OVERSCAN,
))
const requirementWindowSize = computed(() => (
  Math.ceil(requirementViewportHeight.value / REQUIREMENT_ROW_HEIGHT) + REQUIREMENT_OVERSCAN * 2
))
const visibleRequirementRows = computed(() => filteredRequirements.value.slice(
  requirementWindowStart.value,
  requirementWindowStart.value + requirementWindowSize.value,
))
const virtualTopHeight = computed(() => requirementWindowStart.value * REQUIREMENT_ROW_HEIGHT)
const virtualBottomHeight = computed(() => Math.max(
  0,
  (filteredRequirements.value.length - requirementWindowStart.value - visibleRequirementRows.value.length)
    * REQUIREMENT_ROW_HEIGHT,
))
const batchAcceptCandidates = computed(() => filteredRequirements.value.filter((item) => (
  item.confidence >= 0.9
  && item.ambiguity.level === "低"
  && (item.status === "candidate" || item.status === "llm_reviewed")
)))

function handleRequirementTableScroll(event: Event) {
  const target = event.currentTarget as HTMLElement
  requirementScrollTop.value = target.scrollTop
  requirementViewportHeight.value = target.clientHeight || requirementViewportHeight.value
}

watch(
  [moduleFilter, categoryFilter, typeFilter, statusFilter, confidenceFilter, ambiguousOnly, searchText],
  () => {
    requirementScrollTop.value = 0
    if (requirementTableScroll.value) requirementTableScroll.value.scrollTop = 0
  },
)

const selectedRequirement = computed(() => requirementRows.value.find((item) => item.id === selectedRequirementId.value) ?? requirementRows.value[0] ?? emptyRequirement)
// 是否有真实可选需求（G9-10 哨兵清理）：替代此前 `selectedRequirement.id === emptyRequirement.id`
// 的 magic-string 哨兵比较——emptyRequirement 现仅作空状态 UI 占位（「暂无需求」文案），
// 不再作为判定标志；模板对 selectedRequirement 的非 null 访问由该占位保证不变。
const hasSelectedRequirement = computed(() => requirementRows.value.length > 0)
const documentDisplayName = computed(() => {
  if (currentInputPath.value) return `当前文档：${fileName(currentInputPath.value)}`
  if (currentOutputDir.value) return `当前输出：${currentOutputDir.value}`
  if (selectedRequirement.value.sourceDocument && selectedRequirement.value.sourceDocument !== "-") {
    return `当前文档：${selectedRequirement.value.sourceDocument}`
  }
  return "当前文档：尚未导入"
})
const tableFooterText = computed(() => {
  const total = filteredRequirements.value.length
  if (total === 0) return "显示第 0 条，共 0 条"
  const first = requirementWindowStart.value + 1
  const last = Math.min(total, requirementWindowStart.value + visibleRequirementRows.value.length)
  return `显示第 ${first}-${last} 条，共 ${total} 条`
})
const reviewNote = computed(() => {
  if (selectedRequirement.value.status === "rejected") return "当前条目被拒绝，建议补充重写。"
  if (selectedRequirement.value.status === "expert_pending") return "建议交给专家进一步确认。"
  if (selectedRequirement.value.status === "needs_discussion") return "当前条目正在讨论中。"
  return "系统理解已抽取，可继续审查。"
})
const phaseStats = computed(() => {
  const total = requirementRows.value.length
  const accepted = countStatus("accepted")
  const expert = countStatus("expert_pending")
  const ambiguous = requirementRows.value.filter((item) => item.ambiguity.level !== "低").length
  return [
    { label: "总数", value: total, hint: "全部", filter: "all" as StatFilter, active: statusFilter.value === "全部" && !ambiguousOnly.value },
    { label: "已接受", value: accepted, hint: "筛选", filter: "accepted" as StatFilter, active: statusFilter.value === "accepted" },
    { label: "待专家", value: expert, hint: "筛选", filter: "expert_pending" as StatFilter, active: statusFilter.value === "expert_pending" },
    { label: "歧义", value: ambiguous, hint: "筛选", filter: "ambiguous" as StatFilter, active: ambiguousOnly.value },
  ]
})
const translationText = computed(() => {
  if (translationError.value) return translationError.value
  if (selectedRequirement.value.translation) return selectedRequirement.value.translation
  return "（尚未翻译，点击右上角“翻译”生成中文译文）"
})
const atomizedRequirementText = computed(() => selectedRequirement.value.chineseText || "（尚未生成原子化需求）")
const metadataRows = computed(() => [
  { key: "编号", value: selectedRequirement.value.id },
  { key: "模块", value: selectedRequirement.value.module || "未分模块" },
  { key: "细分类", value: selectedRequirement.value.category || selectedRequirement.value.categoryCode || "未分类" },
  { key: "原始分类", value: selectedRequirement.value.categoryCode || "-" },
  { key: "大类", value: selectedRequirement.value.type },
  { key: "对象", value: selectedRequirement.value.object },
  { key: "置信度", value: selectedRequirement.value.confidence.toFixed(2) },
  { key: "歧义", value: selectedRequirement.value.ambiguity.level },
  { key: "状态", value: statusDisplay(selectedRequirement.value.status) },
])
const domainTagText = computed(() => {
  const tags = selectedRequirement.value.domainTags || []
  return tags.length > 0 ? tags.join(" · ") : "暂无领域标签"
})
const sectionPathText = computed(() => {
  const path = selectedRequirement.value.sectionPath || []
  return path.length > 0 ? path.join(" > ") : "暂无章节路径"
})
const knowledgeMatches = computed(() => {
  const points = selectedRequirement.value.keyPoints
  return points.length > 0 ? points.join(" · ") : "暂无知识库匹配"
})

onMounted(() => {
  // 新挂载实例放行轮询：上一实例 unmount 时置的取消标志在此复位
  apiSessionPollingCancelled = false
  heartbeatTimer = setInterval(() => {
    nowTick.value = Date.now()
  }, 5000)
  if (new URLSearchParams(window.location.search).get("demoProgress") === "1") {
    startProgressDemo()
    return
  }
  stopApiSessionReady = window.ratomizerDesktop?.onApiSessionReady?.((session) => {
    void loadFromSession(session, { restoreContext: true }).catch(() => undefined)
  })
  loadInitialApiSession()
  void loadRecentSessions()
  void loadDefaultOutputRoot()
  // 恢复已保存的 LLM 开关/端点：此前只在打开设置面板时才加载——重启后 llmMode 恒 false，
  // 整条 AI 交付物轨静默降级 stub（2026-07-08 审计 A2）
  void loadLlmSettings()
})

onUnmounted(() => {
  // 取消 loadInitialApiSession 轮询：置取消标志 + 推进 generation。遗留轮询在下次 await
  // 后检测到取消标志或代际过期即放弃，避免 unmount 后读新会话的 window.ratomizerDesktop
  // 并多发加载请求（既有潜伏缺陷，F2/F4 时序变化把它暴露为测试 flake）。
  apiSessionPollingCancelled = true
  apiSessionLoadGeneration += 1
  stopProgressDemo()
  stopApiSessionReady?.()
  stopApiSessionReady = undefined
  if (heartbeatTimer) clearInterval(heartbeatTimer)
})

function handleNavAction(item: PhaseNavId) {
  if (item === "settings") {
    // 设置是弹层不切页——切页会让背景空白（运行/审查内容都被 v-if 收走）
    showSettingsPanel.value = true
    void loadLlmSettings()
    return
  }
  activeNav.value = item
}

function closeSettingsPanel() {
  showSettingsPanel.value = false
  if (activeNav.value === "settings") {
    activeNav.value = "functional"
  }
}

// WS-F：功能需求评审的来源块跳转——切到文档批注视图并刷新，把来源块 id 传入 DocumentReview
// 让其滚动到对应块并高亮（F4：此前 DocumentReview 不接受 focusBlockId，只做视图切换+刷新）。
function focusBlockFromFunctional(blockId: string) {
  if (!currentOutputDir.value) {
    apiMessage.value = "尚未选择输出目录，无法对照原文"
    return
  }
  // 若已在文档视图，先清空再赋值以触发 watch（同一 id 二次跳转也能重新高亮）
  if (documentFocusBlockId.value === blockId) documentFocusBlockId.value = ""
  documentFocusBlockId.value = blockId
  activeNav.value = "document"
  documentRefreshToken.value += 1
  apiMessage.value = blockId ? `已跳转对照原文（来源块 ${blockId}）` : ""
}

// 渲染器字节源：委托 Electron readFileBytes 桥（主进程校验绝对路径 + 体量上限后返回字节）。
// 非 Electron 环境无桥——抛错交由 DocumentRenderer 诚实降级，绝不伪造空字节。
async function loadBytesForRenderer(filePath: string): Promise<ArrayBuffer | Uint8Array> {
  const bridge = window.ratomizerDesktop?.readFileBytes
  if (!bridge) throw new Error("Electron readFileBytes 桥不可用")
  const resp = await bridge({ path: filePath })
  if (!resp || !resp.ok || !resp.bytes) {
    throw new Error(`读取文件字节失败：${resp?.reason || "unknown"}`)
  }
  return resp.bytes
}

// 渲染失败诚实降级：仅当用户仍停留在渲染视图时回到文档批注视图。
// 渲染是异步的——用户可能已手动切走，陈旧的失败回放不应把他从当前视图拉回。
function onRendererFallback() {
  if (activeNav.value === "renderer") activeNav.value = "document"
}

// 渲染视图激活时从既有 /document/pdf 通道装配叠加层数据 + 扫描件徽标来源。
// 扫描件判定保守：仅当后端影印数据给出明确扫描/图像类原因时置 true 并标注来源，否则默认 false。
async function loadRendererMeta() {
  const generation = ++rendererMetaGeneration
  const client = apiClient.value
  if (!client) {
    rendererAnnotations.value = {}
    rendererScanned.value = false
    rendererScannedSource.value = ""
    return
  }
  try {
    const payload = await client.loadPdfAnnotation()
    if (generation !== rendererMetaGeneration) return
    rendererAnnotations.value = {
      pages: payload.pages?.length ?? 0,
      requirementMarkers: payload.requirement_markers?.length ?? 0,
      blockZones: payload.block_zones?.length ?? 0,
      claimZones: payload.claim_zones?.length ?? 0,
    }
    const reason = (payload.reason || "").toLowerCase()
    const looksScanned = !payload.available && /scan|image|无文字层|no_text|图片|光栅/.test(reason)
    rendererScanned.value = looksScanned
    rendererScannedSource.value = looksScanned
      ? `影印通道：${payload.reason}`
      : (payload.available ? "影印通道：文字层可用" : "保守默认（未判定扫描件）")
  } catch {
    if (generation !== rendererMetaGeneration) return
    rendererAnnotations.value = {}
    rendererScanned.value = false
    rendererScannedSource.value = "保守默认（影印通道未就绪）"
  }
}

watch([() => activeNav.value === "renderer", apiClient, currentInputPath], ([active]) => {
  if (active) void loadRendererMeta()
})

async function loadLlmSettings() {
  const saved = await window.ratomizerDesktop?.getLlmSettings?.()
  if (saved) {
    applyLlmSettings(saved)
    settingsStatus.value = "已加载本机 API 设置"
  }
}

async function handleSaveLlmSettings() {
  isSavingSettings.value = true
  settingsStatus.value = ""
  try {
    const saved = await window.ratomizerDesktop?.saveLlmSettings?.(buildLlmSettingsPayload(true))
    if (saved) {
      applyLlmSettings(saved)
    }
    llmApiKey.value = ""
    settingsStatus.value = "配置已保存，API Key 已加密写入本机配置文件"
  } catch (error) {
    settingsStatus.value = error instanceof Error ? error.message : "保存配置失败"
  } finally {
    isSavingSettings.value = false
  }
}

async function handleOpenLogs() {
  // 后端 stderr（LLM 调用时长/降级/被拒原因）按日落在这里；每次运行还有 <输出目录>/run.log
  const result = await window.ratomizerDesktop?.openLogsDir?.()
  settingsStatus.value = result?.dir ? `日志目录已打开：${result.dir}` : "当前环境不支持（仅桌面应用可用）"
}

async function handleTestLlmConnection() {
  isTestingSettings.value = true
  settingsStatus.value = ""
  try {
    const payload = await window.ratomizerDesktop?.testLlmConnection?.(buildLlmSettingsPayload(true))
    settingsStatus.value = payload?.message || "测试完成"
  } catch (error) {
    settingsStatus.value = error instanceof Error ? error.message : "测试连接失败"
  } finally {
    isTestingSettings.value = false
  }
}

function buildLlmSettingsPayload(includeApiKey: boolean): LlmSettings & { apiKey: string } {
  const payload = normalizeUiLlmSettings({
    ...llmSettings.value,
    enabled: llmMode.value,
  })
  return {
    ...payload,
    apiKey: includeApiKey ? llmApiKey.value.trim() : "",
  }
}

function applyLlmSettings(payload: Partial<LlmSettings>) {
  const normalized = normalizeUiLlmSettings(payload)
  llmSettings.value = normalized
  llmMode.value = normalized.enabled
}

function normalizeUiLlmSettings(payload: Partial<LlmSettings>): LlmSettings {
  return {
    enabled: Boolean(payload.enabled),
    visionCapable: payload.visionCapable == null ? false : Boolean(payload.visionCapable),
    baseUrl: stringOr(payload.baseUrl, "http://127.0.0.1:11434/v1"),
    model: stringOr(payload.model, "qwen2.5:14b"),
    apiKeyEnv: stringOr(payload.apiKeyEnv, "RATOMIZER_LLM_API_KEY"),
    temperature: numberOr(payload.temperature, 0),
    maxTokens: integerOr(payload.maxTokens, 4096),
    timeoutS: numberOr(payload.timeoutS, 60),
    maxRetries: integerOr(payload.maxRetries, 3),
    concurrency: Math.max(1, Math.min(16, integerOr(payload.concurrency, 4))),
    selfCheck: payload.selfCheck == null ? true : Boolean(payload.selfCheck),
  }
}

function stringOr(value: unknown, fallback: string) {
  const text = typeof value === "string" ? value.trim() : ""
  return text || fallback
}

function numberOr(value: unknown, fallback: number) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function integerOr(value: unknown, fallback: number) {
  const parsed = Number.parseInt(String(value), 10)
  return Number.isFinite(parsed) ? parsed : fallback
}

function selectRequirement(id: string) {
  selectedRequirementId.value = id
  translationError.value = ""
}

function applyStatFilter(filter: StatFilter) {
  if (filter === "all") {
    statusFilter.value = "全部"
    ambiguousOnly.value = false
  } else if (filter === "ambiguous") {
    statusFilter.value = "全部"
    ambiguousOnly.value = true
  } else {
    statusFilter.value = filter
    ambiguousOnly.value = false
  }
}

function normalizeTableCellRole(value: unknown): TableCellRole {
  const role = String(value || "") as TableCellRole
  return tableRoleOptions.some((option) => option.value === role) ? role : "unknown"
}

function defaultTableDisposition(role: TableCellRole): TableCellDisposition {
  void role
  return "excluded"
}

function installTableReviews(tables: TableReviewTable[]) {
  tableReviews.value = tables
  const drafts: Record<string, TableReviewRoleMapping> = {}
  for (const table of tables) {
    const mapping: TableReviewRoleMapping = {}
    for (const cell of table.cells || []) {
      if (cell.disposition !== "review") continue
      const role = normalizeTableCellRole(cell.role)
      mapping[cell.cell_id] = {
        role,
        disposition: defaultTableDisposition(role),
      }
    }
    drafts[table.table_id] = mapping
  }
  tableReviewDrafts.value = drafts
}

async function confirmTableReview(table: TableReviewTable) {
  const client = apiClient.value
  if (!client || submittingTableReviewId.value) return
  submittingTableReviewId.value = table.table_id
  apiMessage.value = ""
  try {
    const result = await client.applyTableReviewAction({
      tableId: table.table_id,
      expectedEvidenceFingerprint: table.evidence_fingerprint,
      roleMapping: tableReviewDrafts.value[table.table_id] || {},
      actor: "vue3-ui",
      reason: "Confirmed table structure in Vue3 UI",
    })
    if (result.partial) {
      const refreshed = await client.loadTableReviews()
      if (client !== apiClient.value) return
      installTableReviews(refreshed.tables || [])
      const completed = result.completed_cell_ids?.length || 0
      const remaining = result.remaining_cell_ids?.length || 0
      apiMessage.value = `已完成 ${completed} 个 Claim 裁决，仍有 ${remaining} 个待确认`
      return
    }
    tableReviews.value = tableReviews.value.map((item) =>
      item.table_id === table.table_id
        ? { ...item, structure_review_status: result.structure_review_status, review_mode: "human" }
        : item,
    )
    apiMessage.value = result.structure_review_status === "ready"
      ? (result.recompute_error
        ? `表格 ${table.table_id} 结构已确认，但需求重算未完成（${result.recompute_error}）；已自动记录，刷新或重启 API 时会重试`
        : `表格 ${table.table_id} 的结构已确认`)
      : `表格 ${table.table_id} 仍有待确认单元格`
  } catch (error) {
    if (isNeedsReconfirmationError(error) && client === apiClient.value) {
      try {
        const refreshed = await client.loadTableReviews()
        if (client !== apiClient.value) return
        installTableReviews(refreshed.tables || [])
        apiMessage.value = "表格证据已变化，已刷新，请核对后重新确认"
      } catch (refreshError) {
        apiMessage.value = refreshError instanceof Error
          ? `表格复核冲突且刷新失败：${refreshError.message}`
          : "表格复核冲突且刷新失败"
      }
    } else {
      apiMessage.value = error instanceof Error ? error.message : "表格结构复核写入失败"
    }
  } finally {
    submittingTableReviewId.value = ""
  }
}

async function updateStatus(status: ReviewStatus) {
  if (isSubmitting.value) return
  const row = requirementRows.value.find((item) => item.id === selectedRequirementId.value)
  if (!row) return
  apiMessage.value = ""
  const client = apiClient.value
  if (!client) {
    apiMessage.value = "未连接当前输出目录的审查会话，裁决未保存"
    return
  }
  isSubmitting.value = true
  try {
    const state = await client.applyReviewAction({
      requirementId: row.backendId,
      status,
      actor: "vue3-ui",
      reason: reviewComment.value.trim() || `set ${status} from Vue3 UI`,
      expectedTargetFingerprint: row.targetFingerprint,
      expectedTargetPublicationRevision: row.targetPublicationRevision,
      expectedTargetAuthorityWriteRevision: row.targetAuthorityWriteRevision,
    })
    const index = requirementRows.value.findIndex((item) => item.id === row.id)
    if (index >= 0) {
      requirementRows.value[index] = applyReviewState(row, state)
    }
    reviewComment.value = ""
  } catch (error) {
    if (isNeedsReconfirmationError(error) && client === apiClient.value) {
      try {
        const latestRows = (await client.loadRequirements()).map(mapBackendRequirement)
        if (client !== apiClient.value) return
        requirementRows.value = latestRows
        if (!latestRows.some((item) => item.id === selectedRequirementId.value)) {
          selectedRequirementId.value = latestRows[0]?.id ?? ""
        }
        apiMessage.value = "需求证据或解析内容已变化，已刷新，请核对后重新裁决"
      } catch (refreshError) {
        if (client === apiClient.value) {
          apiMessage.value = refreshError instanceof Error
            ? `裁决冲突且刷新失败：${refreshError.message}`
            : "裁决冲突且刷新失败"
        }
      }
    } else {
      apiMessage.value = error instanceof Error ? error.message : "审查状态写入失败"
    }
  } finally {
    isSubmitting.value = false
  }
}

async function batchAcceptHighConfidence() {
  const client = apiClient.value
  if (!client || isBatchAccepting.value || batchAcceptCandidates.value.length === 0) return
  const candidates = [...batchAcceptCandidates.value]
  isBatchAccepting.value = true
  apiMessage.value = `正在批量接受 0/${candidates.length} 条高置信无歧义需求`
  let completed = 0
  try {
    for (const row of candidates) {
      const state = await client.applyReviewAction({
        requirementId: row.backendId,
        status: "accepted",
        actor: "vue3-ui-batch",
        reason: "batch accept high-confidence unambiguous requirement",
        expectedTargetFingerprint: row.targetFingerprint,
        expectedTargetPublicationRevision: row.targetPublicationRevision,
        expectedTargetAuthorityWriteRevision: row.targetAuthorityWriteRevision,
      })
      const index = requirementRows.value.findIndex((item) => item.id === row.id)
      if (index >= 0) requirementRows.value[index] = applyReviewState(requirementRows.value[index], state)
      completed += 1
      apiMessage.value = `正在批量接受 ${completed}/${candidates.length} 条高置信无歧义需求`
    }
    apiMessage.value = `已批量接受 ${completed} 条高置信无歧义需求`
  } catch (error) {
    if (isNeedsReconfirmationError(error) && client === apiClient.value) {
      const latestRows = (await client.loadRequirements()).map(mapBackendRequirement)
      if (client === apiClient.value) requirementRows.value = latestRows
      apiMessage.value = `已接受 ${completed} 条；其余条目证据已变化，已刷新并停止批量操作`
    } else {
      const reason = error instanceof Error ? error.message : "批量接受失败"
      apiMessage.value = `已接受 ${completed} 条；${reason}`
    }
  } finally {
    isBatchAccepting.value = false
  }
}

async function handleTranslate() {
  const row = selectedRequirement.value
  if (!apiClient.value) {
    translationError.value = "请先连接输出目录后再翻译。"
    return
  }
  const sourceText = row.chineseText && row.chineseText !== "-" ? row.chineseText : row.originalText
  if (!sourceText || sourceText === "-") {
    translationError.value = "当前条目没有可翻译文本。"
    return
  }
  isTranslating.value = true
  translationError.value = ""
  apiMessage.value = ""
  try {
    const payload = await apiClient.value.translateRequirement({
      requirementId: row.backendId || row.id,
      text: sourceText,
      context: row.object,
    })
    const index = requirementRows.value.findIndex((item) => item.id === row.id)
    if (index >= 0) {
      requirementRows.value[index] = {
        ...requirementRows.value[index],
        translation: payload.translation,
      }
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "翻译失败"
    translationError.value = message
    apiMessage.value = message
  } finally {
    isTranslating.value = false
  }
}

function statusDisplay(status: ReviewStatus) {
  return displayStatus(status)
}

function statusOptionLabel(status: ReviewStatus | "全部") {
  return status === "全部" ? status : statusDisplay(status)
}

function statusToneClass(status: ReviewStatus) {
  return {
    accept: status === "accepted" || status === "frozen",
    reject: status === "rejected" || status === "needs_rework",
    warning: status === "expert_pending" || status === "flagged",
    review: status === "candidate" || status === "llm_reviewed",
    discuss: status === "needs_discussion",
  }
}

function riskToneClass(level: string) {
  return {
    low: level === "低",
    middle: level === "中",
    high: level === "高",
  }
}

function typeToneClass(type: string) {
  return {
    functional: type === "功能",
    performance: type === "性能",
    security: type === "安全",
    interface: type === "接口",
    data: type === "数据",
    environment: type === "环境",
    constraint: type === "约束",
  }
}

async function handleOpenDocument() {
  const path = await window.ratomizerDesktop?.openDocument()
  if (path) {
    currentInputPath.value = path
    activeNav.value = "renderer"
    apiMessage.value = `已选择文档：${path}`
    runStage.value = "待运行"
    runProgress.value = 0
  }
}

async function handleOpenOutput() {
  if (window.ratomizerDesktop?.selectOutputDir) {
    const path = await window.ratomizerDesktop.selectOutputDir()
    if (path) {
      if (!isCurrentOutputSession(path)) disconnectReviewSession()
      currentOutputDir.value = path
      apiMessage.value = `已选择输出目录：${tailPath(path)}`
      runStage.value = "待运行"
      try {
        const payload = await window.ratomizerDesktop.getOutputSummary?.({ outDir: path })
        if (payload) {
          latestTaskSummary.value = objectValue(payload.summary)
          applyRunManifestSummary(latestTaskSummary.value)
        }
      } catch (error) {
        apiMessage.value = error instanceof Error ? error.message : "输出目录摘要加载失败"
      }

      if (!window.ratomizerDesktop.startApiSession) {
        disconnectReviewSession()
        apiMessage.value = `已选择输出目录：${tailPath(path)}；审查会话未连接，裁决已禁用`
        return
      }
      try {
        const session = await window.ratomizerDesktop.startApiSession(path)
        if (!session) {
          disconnectReviewSession()
          apiMessage.value = `已选择输出目录：${tailPath(path)}；审查会话未连接，裁决已禁用`
          return
        }
        await loadFromSession(session)
      } catch (error) {
        disconnectReviewSession()
        const reason = error instanceof Error ? error.message : "本地 API 启动失败"
        apiMessage.value = `无法连接输出目录的审查会话：${reason}；裁决已禁用`
      }
    }
    return
  }
  const session = await window.ratomizerDesktop?.openOutput?.()
  if (session && typeof session === "object" && "baseUrl" in session) {
    await loadFromSession(session)
  }
}

async function handleOpenExistingOutput() {
  if (!window.ratomizerDesktop?.openOutput) {
    apiMessage.value = "当前环境不支持打开已有结果"
    return
  }
  try {
    const session = await window.ratomizerDesktop.openOutput()
    if (!session) return
    await loadFromSession(session, { restoreContext: true })
  } catch (error) {
    // S8：打开失败保留当前审查会话——只有新 API 成功接管（loadFromSession 走完）
    // 才允许断开旧会话，选错目录/分类失败不应清空用户正在审的内容
    const reason = error instanceof Error ? error.message : "本地 API 启动失败"
    apiMessage.value = `无法打开已有结果：${reason}`
  }
}

function plannedAutomaticStages(options: { llmReviewLimit?: number }): string[] {
  const stages = ["atomize"]
  if (runStages.value.llmReview) stages.push("llm-review")
  if (options.llmReviewLimit) return stages
  const useLlm = llmMode.value
  if (runStages.value.aiExtract) {
    stages.push("ai-extract")
    if (useLlm) stages.push("functional-synthesis")
  }
  if (runStages.value.assemble) stages.push("assemble")
  if (runStages.value.analyze && useLlm) {
    stages.push("requirements-analysis")
    if (templatePath.value) stages.push("template-write")
    stages.push("clarification-report")
  }
  if (useLlm && translationMode.value === "full") stages.push("full-translation")
  if (runStages.value.compose) stages.push("compose")
  if (runStages.value.annotationHtml) stages.push("export-annotation-html")
  return [...new Set(stages)]
}

function applyResultPackageState(payload: unknown) {
  const record = objectValue(payload)
  const packageState = objectValue(record?.package)
  const activeAttempt = objectValue(packageState?.active_attempt)
  if (activeAttempt?.status === "running") {
    resultPackageStatus.value = "running"
    return
  }
  const status = stringOr(packageState?.analysis_status, "")
  if (["running", "incomplete", "completed"].includes(status)) {
    resultPackageStatus.value = status as ResultPackageStatus
    return
  }
  const layout = stringOr(record?.layout, "")
  if (layout === "legacy" || layout === "legacy_flat") resultPackageStatus.value = "legacy"
}

async function handleRunPipeline(options: { llmReviewLimit?: number } = {}) {
  if (progressDemoTimer !== undefined) {
    stopProgressDemo()
    isRunning.value = false
  }
  if (isRunning.value) return
  let stopProgress: (() => void) | undefined
  let packageRunId = ""
  let packageOutDir = ""
  let requestedPackageStages: string[] = []
  try {
    if (!currentInputPath.value) {
      apiMessage.value = "请先导入文档"
      runStage.value = "等待导入文档"
      runProgress.value = 0
      runProgressDetail.value = "尚未选择导入文档"
      return
    }
    if (!currentInputPath.value || !window.ratomizerDesktop?.runPipeline) return
    stopProgress = window.ratomizerDesktop.onTaskProgress?.(handleTaskProgress)
    const outDir = currentOutputDir.value || defaultOutputDir(currentInputPath.value)
    currentOutputDir.value = outDir
    isRunning.value = true
    packageOutDir = outDir
    requestedPackageStages = plannedAutomaticStages(options)
    if (window.ratomizerDesktop.startResultPackage) {
      const started = await window.ratomizerDesktop.startResultPackage({
        outDir,
        inputPath: currentInputPath.value,
        stages: requestedPackageStages,
      })
      applyResultPackageState(started)
      // I5：legacy 目录由主进程分类后直接按旧管线运行（不创建 marker/.ratomizer），
      // 不返回 run_id，也不需要 complete/fail 跟踪
      const startedLayout = stringOr(objectValue(started)?.layout, "")
      if (startedLayout !== "legacy") {
        const packageState = objectValue(started.package)
        const activeAttempt = objectValue(packageState?.active_attempt)
        packageRunId = stringOr(activeAttempt?.run_id, "")
        if (!packageRunId) throw new Error("结果包启动未返回运行标识")
      }
    }
    resetRunStageBoard()
    runProgress.value = 8
    runStage.value = "准备运行"
    runProgressDetail.value = options.llmReviewLimit ? `测试运行：最多 AI 审查 ${options.llmReviewLimit} 条` : "准备启动本地任务"
    apiMessage.value = options.llmReviewLimit ? `正在测试运行，最多 AI 审查 ${options.llmReviewLimit} 条...` : "正在运行抽取与审查..."
    await nextUiTick()
    runProgress.value = 18
    runStage.value = "运行后端解析"
    runProgressDetail.value = "正在解析文档"
    // 「LLM 审查（规则候选复核）」可选：散文类标准的交付物主要来自 AI 抽取轨，
    // 关掉可省大量审查调用（DLMS profile 建议开）。测试运行同样尊重该开关。
    const reviewEnabled = runStages.value.llmReview
    const useLlmReview = reviewEnabled && (llmMode.value || Boolean(options.llmReviewLimit))
    const payload = await window.ratomizerDesktop.runPipeline({
      inputPath: currentInputPath.value,
      outDir,
      skipReview: !reviewEnabled,
      llmRoute: useLlmReview ? "openai_compatible" : undefined,
      reviewScope: useLlmReview ? "targeted" : undefined,
      ...(options.llmReviewLimit && reviewEnabled ? { llmReviewLimit: options.llmReviewLimit } : {}),
      ...abntPreset,
    })
    runProgress.value = 82
    runStage.value = "加载解析结果"
    runProgressDetail.value = "正在加载结果文件"
    latestTaskSummary.value = objectValue(payload.summary)
    applyRunManifestSummary(latestTaskSummary.value)
    const summaryCounts = objectValue((latestTaskSummary.value as Record<string, unknown> | null)?.counts) as Record<string, unknown> | null
    if (summaryCounts?.functional_requirements != null) {
      runOverview.value = { ...runOverview.value, functionalReqs: Number(summaryCounts.functional_requirements) }
    }
    const finalOutDir = String(payload.out_dir || payload.outDir || outDir)
    currentOutputDir.value = finalOutDir
    let apiReconnectWarning = formatApiReconnectWarning(finalOutDir, stringOr(payload.api_warning, ""))
    apiReconnectWarning ||= await refreshAfterDesktopTask(finalOutDir)
    void refreshUnitRouting()

    // 追加交付物链：按「运行阶段」配置依次执行（测试运行只跑基础解析+限量审查，不追加）
    type ConsistencySummary = { duplicate_groups?: number; obis_values_differ?: number; uncovered_requirement_like?: number }
    const ranStages: string[] = []
    let consistency: ConsistencySummary | null = null
    let readinessNote = ""
    const bridge = window.ratomizerDesktop
    if (!options.llmReviewLimit && bridge) {
      const useLlm = llmMode.value
      const llmRoute = useLlm ? "openai_compatible" : "stub"
      // 编排在后端（desktop_tasks chain）：UI 只发一条命令 + 渲染进度。阶段名与后端子命令一致。
      const stages: string[] = []
      if (runStages.value.aiExtract) {
        stages.push("ai-extract")
        if (useLlm) stages.push("functional-synthesis")
      }
      if (runStages.value.assemble) stages.push("assemble")
      // 分析/成文/澄清硬依赖真 LLM 抽取产物（ai_requirements.jsonl，stub 路由不产）——
      // LLM 关时带上它们必然断链，且把排在后面的 compose/批注 HTML 一起掐死（2026-07-08 审计 A3）
      const skippedForLlm: string[] = []
      if (runStages.value.analyze) {
        if (useLlm) {
          stages.push("requirements-analysis")
          if (templatePath.value) stages.push("template-write")
          stages.push("clarification-report")
        } else {
          skippedForLlm.push("功能重组", "需求分析", "按模板成文", "澄清清单")
          // 阶段卡同步:不然 LLM 关时这些卡永远停在"待完成"(0710 评审 R2)
          for (const key of ["functional-synthesis", "requirements-analysis", "template-write", "clarification-report"]) {
            setRunStageState(key, { status: "disabled", percent: 0, detail: "LLM 关闭，未运行" })
          }
        }
      }
      if (useLlm && translationMode.value === "full") {
        stages.push("full-translation")
      } else if (useLlm) {
        // 翻译交付模式 off/markers：全文翻译不进链（后端同样拿掉并落账），阶段卡如实降级
        setRunStageState("full-translation", {
          status: "disabled", percent: 0,
          detail: translationMode.value === "off" ? "翻译模式=关闭，未运行" : "翻译模式=仅批注，未运行",
        })
      }
      if (runStages.value.compose) stages.push("compose")
      if (runStages.value.annotationHtml) stages.push("export-annotation-html")
      if (stages.length && bridge.runChain) {
        runStage.value = "交付物链"
        runProgress.value = 86
        runProgressDetail.value = `正在执行：${stages.join(" → ")}…`
        await nextUiTick()
        let chainPayload: RequirementAtomizerTaskPayload
        try {
          chainPayload = await bridge.runChain({
            outDir: finalOutDir, stages, llmRoute,
            templatePath: templatePath.value || undefined,
            ...(stages.includes("export-annotation-html")
              ? { annotationLayoutMode: "pdf_original" }
              : {}),
            ...(translationMode.value !== "full"
              ? { translationMode: translationMode.value }
              : {}),
          })
        } catch (chainError) {
          throw new Error(`交付物链失败：${chainError instanceof Error ? chainError.message : chainError}`)
        }
        const chainConsistency = objectValue(chainPayload?.consistency)
        if (chainConsistency) consistency = chainConsistency as ConsistencySummary
        latestTaskSummary.value = objectValue(chainPayload.summary) || latestTaskSummary.value
        applyRunManifestSummary(latestTaskSummary.value)
        const chainReadiness = objectValue(chainPayload?.readiness) as { verdict?: string; reasons?: string[] } | null
        if (chainReadiness?.verdict) {
          readinessNote = `；就绪判定：${chainReadiness.verdict}` +
            ((chainReadiness.reasons || []).length ? `（${(chainReadiness.reasons || []).join("、")}）` : "") +
            `，必答澄清 ${Number(chainPayload?.questions ?? 0)} 条 → clarification_questions.xlsx`
        }
        // 阶段降级/告警必须可见（stub 路由、部分章节失败等此前 GUI 全绿沉默）
        const chainNotes = Array.isArray(chainPayload?.stage_notes)
          ? (chainPayload.stage_notes as unknown[]).map((n) => String(n)) : []
        if (chainNotes.length) {
          readinessNote += `；注意：${chainNotes.join("；")}`
        }
        if (chainPayload?.conservation_blocked) {
          const block = String(chainPayload.conservation_block_error || "功能需求守恒核对未闭合")
          readinessNote += `；成文已阻断：${shortConservationError(block)}`
        }
        lastStageNotes.value = chainNotes
        // 运行页总览瓦片（样机）：从链载荷提取,缺项保持 —
        const q = objectValue(chainPayload?.quality) as Record<string, unknown> | null
        const verdict = chainReadiness?.verdict || runOverview.value.verdict
        runOverview.value = {
          functionalReqs: chainPayload?.count != null ? Number(chainPayload.count) : runOverview.value.functionalReqs,
          selfCheck: q?.self_check_added != null ? Number(q.self_check_added) : runOverview.value.selfCheck,
          coverage: q?.coverage_pct != null ? Number(q.coverage_pct) : runOverview.value.coverage,
          chapters: q?.sections_total != null ? `${q.sections_total} 章 · 失败 ${q.failed_sections ?? 0}` : runOverview.value.chapters,
          questions: chainPayload?.questions != null ? Number(chainPayload.questions) : runOverview.value.questions,
          verdict,
          deliverableHint: verdict === "READY"
            ? "可以写成文"
            : (verdict ? "尚不能交货，先处理缺口" : runOverview.value.deliverableHint),
        }
        ranStages.push(...stages.map((s) => CHAIN_STEP_LABELS[s] || s))
        apiReconnectWarning ||= await refreshAfterDesktopTask(finalOutDir)
      }
      if (skippedForLlm.length) {
        readinessNote += `；LLM 已关闭，跳过：${skippedForLlm.join("、")}（顶栏开启 LLM 后重跑可得完整交付物）`
      }
    }

    // 测试运行追加：样本交付物链（1/5 试抽 → 分析 → 成文 → 澄清），同一条后端 chain 命令
    let sampleNote = ""
    if (options.llmReviewLimit && bridge?.runChain) {
      runStage.value = "样本交付物链"
      runProgress.value = 90
      runProgressDetail.value = `均匀抽样全文 ${Math.round(TEST_AI_EXTRACT_SAMPLE_RATIO * 100)}% 章节试抽 + 分析…`
      await nextUiTick()
      try {
        const stages = ["ai-extract", "functional-synthesis", "requirements-analysis",
                        ...(templatePath.value ? ["template-write"] : []), "clarification-report"]
        const sample = await bridge.runChain({
          outDir: finalOutDir, stages, llmRoute: "openai_compatible",
          templatePath: templatePath.value || undefined,
          sampleRatio: TEST_AI_EXTRACT_SAMPLE_RATIO,
        })
        const info = objectValue(sample.sampled) as { sections?: number; total_sections?: number } | null
        const quality = objectValue(sample.quality) as { coverage_pct?: number } | null
        sampleNote = `；试抽样本 ${info?.sections ?? "?"}/${info?.total_sections ?? "?"} 章：` +
          `${Number(sample.count ?? 0)} 条` +
          (quality?.coverage_pct != null ? `、样本覆盖率 ${quality.coverage_pct}%` : "")
        const a = objectValue(sample.analysis) as { analysis_count?: number; enriched?: number; enrich_degraded?: number } | null
        if (a) {
          const degraded = Number(a.enrich_degraded ?? 0)
          sampleNote += `；软件需求 ${Number(a.analysis_count ?? 0)} 条（富化 ${Number(a.enriched ?? 0)}${degraded > 0 ? `、降级 ${degraded}` : ""}）→ software_requirements.xlsx`
        }
        const w = objectValue(sample.template) as { appended_total?: number } | null
        if (w) sampleNote += `；成文 ${Number(w.appended_total ?? 0)} 行 → 软件需求列表-成文.xlsx`
        const r = objectValue(sample.readiness) as { verdict?: string } | null
        if (r?.verdict) sampleNote += `；就绪判定 ${r.verdict}，必答澄清 ${Number(sample.questions ?? 0)} 条`
        apiReconnectWarning ||= await refreshAfterDesktopTask(finalOutDir)
      } catch (sampleError) {
        const detail = sampleError instanceof Error ? sampleError.message : String(sampleError)
        failRunningStages(detail)
        sampleNote = `；样本链失败：${detail}`
      }
    }

    let packageNote = ""
    if (packageRunId && window.ratomizerDesktop.completeResultPackage) {
      const completedPackage = await window.ratomizerDesktop.completeResultPackage({
        outDir: packageOutDir,
        runId: packageRunId,
        completedStages: requestedPackageStages,
      })
      applyResultPackageState(completedPackage)
      // I6：请求阶段未全部成功（降级/缺失）时后端拒绝完成提交并返回稳定错误码——
      // 如实显示「分析未完成（部分阶段降级）」，不把运行记为失败，也不走 failResultPackage
      const completionRecord = objectValue(completedPackage)
      if (completionRecord?.ok === false && stringOr(completionRecord.code, "") === "requested_stage_partial") {
        resultPackageStatus.value = "incomplete"
        const partialDetail = stringOr(completionRecord.message, "")
        packageNote = `；分析未完成（部分阶段降级）${partialDetail ? `：${partialDetail}` : ""}`
      }
    }
    runProgress.value = 100
    runStage.value = "运行完成"
    if (options.llmReviewLimit) {
      runProgressDetail.value = `测试运行完成：最多 AI 审查 ${options.llmReviewLimit} 条${sampleNote}`
      apiMessage.value = `测试运行完成${sampleNote}${packageNote}`
    } else {
      const tail = ranStages.length ? `，随后 ${ranStages.join(" → ")}` : ""
      // 一致性闭环：跨章重复/OBIS 待核/覆盖缺口直接进跑完消息（详情看批注视图标记）
      const dup = Number(consistency?.duplicate_groups || 0)
      const differ = Number(consistency?.obis_values_differ || 0)
      const uncovered = Number(consistency?.uncovered_requirement_like || 0)
      const warn = dup || differ || uncovered
        ? `；一致性：疑似跨章重复 ${dup} 组、OBIS 数值待核 ${differ}、覆盖缺口 ${uncovered}（批注视图已标记，遗漏候选已列入澄清清单）`
        : ""
      const apiWarn = apiReconnectWarning
        ? `；${apiReconnectWarning}`
        : ""
      runProgressDetail.value = `全部阶段完成：抽取与审查${tail}`
      apiMessage.value = `运行完成：抽取与审查${tail}${warn}${readinessNote}${apiWarn}${packageNote}` +
        (unitRoutingSummary.value ? `；${unitRoutingSummary.value}` : "")
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : "抽取与审查失败"
    if (packageRunId && packageOutDir && window.ratomizerDesktop?.failResultPackage) {
      try {
        const failedPackage = await window.ratomizerDesktop.failResultPackage({
          outDir: packageOutDir,
          runId: packageRunId,
          error: detail,
        })
        applyResultPackageState(failedPackage)
      } catch {
        // Preserve the original failure; a running marker remains fail-closed.
      }
    }
    failRunningStages(detail)
    runStage.value = "运行失败"
    runProgressDetail.value = "请查看错误信息"
    apiMessage.value = detail
  } finally {
    stopProgress?.()
    isRunning.value = false
  }
}

const CHAIN_STEP_LABELS: Record<string, string> = {
  "functional-synthesis": "功能重组",
  "functional-extract": "功能需求直抽（条款级，无原子化）",
  "ai-extract": "AI 抽取（双引擎）", assemble: "装配实现规格", "requirements-analysis": "软件需求分析",
  "template-write": "成文需求列表", "clarification-report": "澄清问题清单", compose: "组装工程需求",
  "full-translation": "生成全文双语交付物",
  "export-annotation-html": "导出批注视图",
}

function handleTaskProgress(event: { stage: string; step?: string; status?: string; completed?: number; total?: number; percent?: number; model?: string }) {
  const completed = Math.max(0, Number(event.completed || 0))
  const total = Math.max(0, Number(event.total || 0))
  const percent = Number.isFinite(Number(event.percent)) ? Math.max(0, Math.min(100, Number(event.percent))) : 0
  if (event.stage === "pipeline_stage") {
    const status: RunStageStatus = event.status === "skipped" ? "skipped"
      : event.status === "ok" ? "ok"
        : event.status === "failed" ? "failed" : "running"
    const detail = status === "skipped" ? "复用已有产物"
      : status === "failed" ? "阶段执行失败" : "基础解析产物"
    setRunStageState(event.step, { status, percent, detail })
    return
  }
  if (event.stage === "chain") {
    const step = String(event.step || "")
    const label = CHAIN_STEP_LABELS[step] || step || "交付物链"
    // WS2 功能直抽（RATOMIZER_FUNCTIONAL_EXTRACT=1）：后端把 ai-extract+functional-synthesis
    // 整体替换为 functional-extract——进度驱动「AI抽取」卡片，「功能重组」卡片如实标记被替换
    const cardKey = step === "functional-extract" ? "ai-extract" : step
    if (step === "functional-extract") {
      setRunStageState("functional-synthesis", { status: "skipped", percent: 100, detail: "由功能需求直抽替代" })
    }
    // 真实反馈 2026-07-14：链步进入新阶段 → 上一阶段卡片翻绿。后端的完成事件与开始事件
    // 同 step 名(只有 skipped 带 status),此前完成的阶段没人翻绿、卡在最后一次内部进度。
    if (lastChainStep && lastChainStep !== step) {
      setRunStageState(lastChainStep, { status: "ok", percent: 100, detail: "已完成" })
    }
    lastChainStep = step
    const status = event.status === "skipped" ? "skipped" : completed >= total && total > 0 ? "ok" : "running"
    if (status === "running") {
      // 链级百分比是"第 N/共 M 步"(2/7≈14%),不是阶段内部进度——不写进卡片,
      // 卡片百分比由链内细粒度事件(ai_extract/analyze)驱动(setRunStageState 是合并语义)
      setRunStageState(cardKey, { status, detail: label })
    } else {
      setRunStageState(cardKey, { status, percent: 100, detail: status === "skipped" ? "复用已有产物" : "已完成" })
    }
    runStage.value = total ? `交付物链 ${Math.min(completed + 1, total)}/${total}：${label}` : label
    runProgress.value = percent   // 顶栏切到链视角(此前保留基础管线的 100%,出现"100% 但还在跑")
    runProgressDetail.value = `正在执行：${label}…`
    return
  }
  if (event.stage === "functional_extract") {
    setRunStageState("ai-extract", {
      status: percent >= 100 ? "ok" : "running",
      percent,
      detail: total ? `${completed}/${total} 条款` : "准备条款包",
    })
    runStage.value = total ? `功能需求直抽 ${completed}/${total} 条款` : "功能需求直抽"
    runProgress.value = percent
    runProgressDetail.value = event.model
      ? `模型：${event.model} · 逐条款调用 LLM`
      : "逐条款调用 LLM（条款级，无原子化）"
    return
  }
  if (event.stage === "ai_extract") {
    if (completed !== lastAiExtractCompleted) {
      lastAiExtractCompleted = completed
      documentRefreshToken.value += 1
    }
    setRunStageState("ai-extract", { status: percent >= 100 ? "ok" : "running", percent, detail: total ? `${completed}/${total} 章节` : "逐章节调用 LLM" })
    runStage.value = total ? `AI 抽取 ${completed}/${total} 章节` : "AI 抽取"
    runProgress.value = percent
    runProgressDetail.value = event.model ? `模型：${event.model} · 逐章节调用 LLM` : "逐章节调用 LLM 抽取行为需求"
    return
  }
  if (event.stage === "analyze") {
    setRunStageState("requirements-analysis", { status: percent >= 100 ? "ok" : "running", percent, detail: total ? `${completed}/${total} 条` : "需求富化" })
    runStage.value = total ? `软件需求分析 富化 ${completed}/${total}` : "软件需求分析"
    runProgress.value = percent
    runProgressDetail.value = event.model
      ? `模型：${event.model} · 并发推导可研发软件需求（增量缓存，中断可续跑）`
      : "并发推导可研发软件需求"
    return
  }
  if (event.stage !== "llm_review") return
  setRunStageState("llm-review", { status: percent >= 100 ? "ok" : "running", percent, detail: total ? `${completed}/${total} 条` : "逐条审查" })
  runStage.value = total ? `AI 审查 ${completed}/${total}` : "AI 审查"
  runProgress.value = percent
  runProgressDetail.value = event.model ? `模型：${event.model}` : "模型正在逐条审查需求"
}

function openAnnotationHtml() {
  // 交付物入口:导出是幂等重渲染(毫秒级),直接复用——保证打开的永远是最新数据
  void handleExportAnnotationHtml()
}

async function handleExportAnnotationHtml() {
  if (!currentOutputDir.value || !window.ratomizerDesktop?.exportAnnotationHtml) {
    apiMessage.value = "请先运行管线 + AI 抽取生成需求，再导出文档批注 HTML"
    return
  }
  try {
    // LLM 开时顺带补齐块级"说明"标记的中文翻译（内容哈希缓存,重导出零调用）
    const payload = await window.ratomizerDesktop.exportAnnotationHtml({
      outDir: currentOutputDir.value,
      route: llmMode.value ? "openai_compatible" : undefined,
      layoutMode: "pdf_original",
    })
    if (payload.path) {
      await window.ratomizerDesktop.openPath?.(payload.path)
      apiMessage.value = `已生成并打开文档批注 HTML：${payload.path}`
    } else {
      apiMessage.value = "文档批注 HTML 已生成"
    }
  } catch (error) {
    apiMessage.value = error instanceof Error ? error.message : "导出文档批注 HTML 失败"
  }
}

async function handleImportAnswers() {
  if (!currentOutputDir.value || !window.ratomizerDesktop?.importClarificationAnswers) {
    apiMessage.value = "请先选择输出目录"
    return
  }
  try {
    const payload = await window.ratomizerDesktop.importClarificationAnswers({ outDir: currentOutputDir.value })
    if (payload.canceled) return
    const readiness = objectValue(payload.readiness) as { verdict?: string } | null
    apiMessage.value = `已导入客户答复 ${Number(payload.imported ?? 0)} 条、内部核对 ${Number(payload.internal_imported ?? 0)} 条` +
      (readiness?.verdict ? `；当前就绪判定：${readiness.verdict}` : "") +
      "——客户答复将在下次软件需求分析时作为权威输入生效"
  } catch (error) {
    apiMessage.value = error instanceof Error ? error.message : "导入澄清答复失败"
  }
}

async function handleImportDecisions() {
  if (!currentOutputDir.value || !window.ratomizerDesktop?.importAiDecisions) {
    apiMessage.value = "请先选择输出目录"
    return
  }
  try {
    const payload = await window.ratomizerDesktop.importAiDecisions({ outDir: currentOutputDir.value })
    if (payload.canceled) return
    const rebuiltNote = payload.rebuilt ? "，交付物 merged_spec 已重建" : ""
    apiMessage.value = `已导入裁决：应用 ${payload.applied ?? 0} 条（跳过 ${payload.skipped ?? 0}）${rebuiltNote}`
  } catch (error) {
    apiMessage.value = error instanceof Error ? error.message : "导入裁决失败"
  }
}

async function loadInitialApiSession() {
  // 后端（PyInstaller exe）启动需要数秒——轮询等它就绪，而不是首查 null 就放弃。
  // 绑定本次轮询的 generation，并在每次 await 后复查「取消标志」与「当前 session 一致性
  // （generation guard）」：onUnmounted（置取消标志 + 推进 generation）、disconnectReviewSession
  // 或更新的 loadFromSession 任一发生即放弃。否则组件 unmount 后遗留的轮询会读下一个测试/会话
  // 的 window.ratomizerDesktop 并多发加载请求（loadFromSession 自身在其入口 ++generation，
  // 故守卫必须在调用前于此拦截）。
  const generation = apiSessionLoadGeneration
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (apiSessionPollingCancelled || generation !== apiSessionLoadGeneration) return
    const session = await window.ratomizerDesktop?.getApiSession?.()
    if (apiSessionPollingCancelled || generation !== apiSessionLoadGeneration) return
    if (session) {
      try {
        await loadFromSession(session, { restoreContext: true })
      } catch {
        // loadFromSession 已把原因写进 apiMessage
      }
      return
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
}

async function loadFromSession(
  session: { baseUrl: string; token: string; outputDir?: string },
  options: { restoreContext?: boolean } = {},
) {
  const nextSessionKey = reviewSessionIdentity(session)
  const sameSession = Boolean(nextSessionKey && nextSessionKey === reviewSessionKey.value)
  const generation = ++apiSessionLoadGeneration
  if (!sameSession) clearReviewSessionState()
  apiMessage.value = session.outputDir ? `正在连接输出目录：${tailPath(session.outputDir)}` : "正在连接审查会话"
  currentOutputDir.value = session.outputDir || currentOutputDir.value
  const client = new RequirementApiClient({ baseUrl: session.baseUrl, token: session.token })
  try {
    const rows = (await client.loadRequirements()).map(mapBackendRequirement)
    if (generation !== apiSessionLoadGeneration) return
    reviewSessionKey.value = nextSessionKey
    apiClient.value = client
    requirementRows.value = rows
    if (!sameSession || !rows.some((row) => row.id === selectedRequirementId.value)) {
      selectedRequirementId.value = rows[0]?.id ?? ""
    }
    apiMessage.value = session.outputDir ? `已连接输出目录：${tailPath(session.outputDir)}` : "已连接审查会话"
    void loadRecentSessions()
    if (options.restoreContext && session.outputDir) {
      await restoreOutputContext(client, session.outputDir, generation)
    }
  } catch (error) {
    if (generation === apiSessionLoadGeneration) {
      clearReviewSessionState()
      apiMessage.value = `${error instanceof Error ? error.message : "需求加载失败"}；裁决已禁用`
    }
    throw error
  }
  try {
    const tableReviewPayload = await client.loadTableReviews()
    if (generation !== apiSessionLoadGeneration) return
    installTableReviews(tableReviewPayload.tables || [])
  } catch {
    if (generation === apiSessionLoadGeneration) installTableReviews([])
  }
  try {
    // 复盘建议为附属信息：加载失败/老目录缺文件不影响连接流程
    const insights = await client.loadReviewInsights()
    if (generation !== apiSessionLoadGeneration) return
    reviewInsights.value = Array.isArray(insights?.suggestions)
      ? insights.suggestions.map((s) => String(s)) : []
  } catch {
    if (generation === apiSessionLoadGeneration) reviewInsights.value = []
  }
  try {
    const packageState = await client.loadResultPackage({
      // S5：显式打开/恢复会话时做完整校验（哈希重算）；轮询式刷新保持纯存在性检查
      verify: options.restoreContext === true,
    })
    if (generation === apiSessionLoadGeneration) applyResultPackageState(packageState)
  } catch (error) {
    // S5：完整校验发现交付物/完成证据哈希不一致——如实显示「结果文件已被修改」，
    // 不静默吞掉；其余失败（老 API 无端点等）保持既有宽容
    if (
      generation === apiSessionLoadGeneration
      && error instanceof RequirementApiError
      && error.details?.error === "result_package_modified"
    ) {
      apiMessage.value = String(error.details.detail || "结果文件已被修改")
    }
  }
}

async function restoreOutputContext(client: RequirementApiClient, outDir: string, generation: number) {
  const summaryLoader = window.ratomizerDesktop?.getOutputSummary
  const summaryPromise = summaryLoader ? summaryLoader({ outDir }) : Promise.resolve(null)
  const [summaryResult, manifestResult] = await Promise.allSettled([
    summaryPromise,
    summaryLoader ? client.loadManifest() : Promise.resolve(null),
  ])
  if (generation !== apiSessionLoadGeneration) return
  if (summaryResult.status === "fulfilled" && summaryResult.value) {
    latestTaskSummary.value = objectValue(summaryResult.value.summary)
    applyRunManifestSummary(latestTaskSummary.value)
  }
  if (manifestResult.status === "fulfilled" && manifestResult.value) {
    const input = String(manifestResult.value.input || "").trim()
    if (input) currentInputPath.value = input
  }
  if (summaryLoader) activeNav.value = "functional"
}

function disconnectReviewSession() {
  apiSessionLoadGeneration += 1
  clearReviewSessionState()
}

function clearReviewSessionState() {
  apiClient.value = null
  reviewSessionKey.value = ""
  requirementRows.value = []
  selectedRequirementId.value = ""
  reviewInsights.value = []
  installTableReviews([])
  submittingTableReviewId.value = ""
}

// 最近结果列表（主进程持久化于 userData/recent-sessions.json）：重启自动恢复最近一次，
// 历史目录在此一键打开——查看旧结果不必重跑管线
async function loadRecentSessions() {
  try {
    recentSessions.value = (await window.ratomizerDesktop?.getRecentSessions?.()) || []
  } catch {
    recentSessions.value = []
  }
}

async function openRecentSession(entry: RequirementAtomizerRecentSession) {
  if (!entry.exists || !entry.isOutput || isCurrentOutputSession(entry.outputDir)) return
  try {
    const session = await window.ratomizerDesktop?.startApiSession?.(entry.outputDir)
    if (session) {
      await loadFromSession(session, { restoreContext: true })
    } else {
      apiMessage.value = `无法连接输出目录：${tailPath(entry.outputDir)}`
    }
  } catch (error) {
    apiMessage.value = `无法连接输出目录：${error instanceof Error ? error.message : "本地 API 启动失败"}`
  }
}

function formatRecentTime(value: string) {
  const time = Date.parse(value)
  if (!Number.isFinite(time)) return ""
  return new Date(time).toLocaleString("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  })
}

async function refreshAfterDesktopTask(outDir: string): Promise<string> {
  try {
    const session = await window.ratomizerDesktop?.startApiSession?.(outDir)
    if (session) {
      await loadFromSession(session)
    } else {
      disconnectReviewSession()
      return formatApiReconnectWarning(outDir, "本地 API 未返回审查会话，裁决已禁用")
    }
    return ""
  } catch (error) {
    disconnectReviewSession()
    const message = error instanceof Error ? error.message : String(error)
    return formatApiReconnectWarning(outDir, message)
  }
}

function reviewSessionIdentity(session: { baseUrl: string; outputDir?: string }) {
  const output = String(session.outputDir || "").trim()
  if (output) return `output:${normalizeOutputIdentity(output)}`
  return `api:${String(session.baseUrl || "").trim().replace(/\/+$/, "").toLowerCase()}`
}

function normalizeOutputIdentity(path: string) {
  return path.trim().replace(/[\\/]+$/, "").replace(/\\/g, "/").toLowerCase()
}

function isCurrentOutputSession(path: string) {
  return reviewSessionKey.value === `output:${normalizeOutputIdentity(path)}`
}

function formatApiReconnectWarning(outDir: string, reason: string) {
  const text = reason.trim()
  if (!text) return ""
  if (text.includes("输出目录") || text.includes("成果已保留")) {
    return text
  }
  return `结果已生成在输出目录：${outDir}；但本地 API 暂时未连接（${text}）。无需重跑 AI，稍后重新选择该输出目录即可继续查看/批注`
}

// S16：默认输出根经 Electron 派生（app:get-default-output-root，documents/失败退回
// userData），禁止硬编码开发机路径；bridge 不可用（浏览器调试）时退回输入文件同级目录。
const defaultOutputRoot = ref("")

async function loadDefaultOutputRoot() {
  if (!window.ratomizerDesktop?.getDefaultOutputRoot) return
  try {
    defaultOutputRoot.value = await window.ratomizerDesktop.getDefaultOutputRoot()
  } catch {
    defaultOutputRoot.value = ""
  }
}

function defaultOutputDir(inputPath: string) {
  const stem = inputPath.split(/[\\/]/).pop()?.replace(/\.[^.]+$/, "") || "run"
  if (defaultOutputRoot.value) {
    return `${defaultOutputRoot.value.replace(/[\\/]+$/, "")}\\${stem}`
  }
  const parent = inputPath.replace(/[\\/][^\\/]*$/, "")
  return parent && parent !== inputPath ? `${parent}\\${stem}-run` : stem
}

function countStatus(status: ReviewStatus) {
  return requirementRows.value.filter((item) => item.status === status).length
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function nextUiTick() {
  return new Promise<void>((resolve) => window.setTimeout(resolve, 0))
}

function fileName(path: string) {
  return path.split(/[\\/]/).pop() || path
}
</script>
<style scoped>
.shell {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  min-height: 100vh;
  background: #f6f7fa;
  color: #1a2233;
}

.sidebar {
  background: #ffffff;
  border-right: 1px solid #e6e9f0;
  color: #1a2233;
  padding: 18px 14px;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 54px;
}

.brand-mark {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: #2b56f5;
  color: #ffffff;
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 20px;
}

.brand-title {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.25;
}

.brand-subtitle {
  margin-top: 4px;
  color: #98a1b3;
  font-size: 12px;
}

.nav-groups {
  display: flex;
  flex-direction: column;
  gap: 18px;
  flex: 1;
}

.nav-group-title {
  margin: 0 0 8px;
  color: #a9b1c2;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
}

.nav-item {
  display: block;
  width: 100%;
  margin: 3px 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #5c6675;
  padding: 11px 12px;
  text-align: left;
  cursor: pointer;
}

.nav-item.active,
.nav-item:hover {
  background: #eef2ff;
  color: #2b56f5;
  font-weight: 600;
}

.sidebar-footer {
  border-top: 1px solid #e6e9f0;
  padding-top: 14px;
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-avatar {
  width: 36px;
  height: 36px;
  border-radius: 999px;
  background: #eef2ff;
  color: #2b56f5;
  display: grid;
  place-items: center;
  font-weight: 700;
}

.user-name {
  font-weight: 600;
}

.user-role {
  color: #98a1b3;
  font-size: 12px;
}

.main-panel {
  min-width: 0;
  padding: 18px 18px 20px;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
}

.title-area {
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-title {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0;
}

.page-badge {
  border: 1px solid #c7d3fc;
  border-radius: 6px;
  color: #1e41c9;
  background: #eef2ff;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 600;
}

.top-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.action,
.toolbar-button,
.decision-button {
  border: 1px solid #e6e9f0;
  border-radius: 8px;
  background: #ffffff;
  color: #242c3d;
  min-height: 34px;
  padding: 0 12px;
  cursor: pointer;
  font-weight: 600;
}

.action.primary,
.toolbar-button.primary {
  background: #2b56f5;
  border-color: #2b56f5;
  color: #ffffff;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.08);
}

.llm-toggle,
.switch-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #5c6675;
  font-weight: 550;
  font-size: 13px;
  cursor: pointer;
}

.llm-toggle input {
  position: absolute;
  opacity: 0;
  width: 34px;
  height: 20px;
  margin: 0;
  cursor: pointer;
}

.llm-track {
  width: 34px;
  height: 20px;
  border-radius: 999px;
  background: #d5dae4;
  position: relative;
  flex: none;
  transition: background 0.15s;
}

.llm-track::after {
  content: "";
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.15);
  transition: left 0.15s;
}

.llm-toggle input:checked + .llm-track {
  background: #2b56f5;
}

.llm-toggle input:checked + .llm-track::after {
  left: 16px;
}

.llm-toggle input:focus-visible + .llm-track {
  outline: 2px solid #2b56f5;
  outline-offset: 2px;
}

.workflow-card {
  background: #ffffff;
  border: 1px solid #eceff5;
  border-radius: 14px;
  padding: 14px;
  box-shadow: 0 1px 3px rgba(16, 24, 40, 0.04);
  margin-bottom: 16px;
}

.workflow-stepper {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  border-bottom: 1px solid #f1f3f8;
  padding-bottom: 14px;
}

.workflow-step {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  position: relative;
}

.workflow-step:not(:last-child)::after {
  content: "";
  height: 1px;
  background: #cdd9e8;
  position: absolute;
  right: 8px;
  left: 112px;
  top: 15px;
}

.workflow-circle {
  width: 30px;
  height: 30px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  background: #e8eef7;
  color: #7a8496;
  font-weight: 700;
  z-index: 1;
}

.workflow-step.done .workflow-circle {
  background: #2b56f5;
  color: #ffffff;
}

.workflow-step.active .workflow-circle {
  background: #1d8a5c;
  color: #ffffff;
}

.workflow-title {
  font-size: 14px;
  font-weight: 700;
}

.workflow-subtitle {
  margin-top: 2px;
  color: #7a8496;
  font-size: 12px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.summary-card {
  background: #ffffff;
  border: 1px solid #eceff5;
  border-radius: 12px;
  min-height: 112px;
  padding: 16px 18px;
}

.summary-label {
  color: #5c6675;
  font-size: 13px;
  font-weight: 700;
}

.summary-value {
  margin-top: 8px;
  font-size: 30px;
  font-weight: 700;
}

.summary-delta {
  margin-top: 4px;
  color: #7a8496;
  font-size: 12px;
}

.summary-card.tone-blue .summary-value { color: #1e41c9; }
.summary-card.tone-green .summary-value { color: #1d8a5c; }
.summary-card.tone-orange .summary-value { color: #cc8925; }
.summary-card.tone-purple .summary-value { color: #7c5cff; }
.summary-card.tone-red .summary-value { color: #d63a40; }

.distribution-card {
  grid-column: span 1;
}

.distribution-list {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.distribution-track {
  height: 8px;
  border-radius: 999px;
  background: #eceff5;
  overflow: hidden;
}

.distribution-fill {
  height: 100%;
  border-radius: inherit;
}

.distribution-fill.tone-green { background: #1d8a5c; }
.distribution-fill.tone-blue { background: #2b56f5; }
.distribution-fill.tone-red { background: #d63a40; }

.distribution-caption {
  font-size: 11px;
  color: #7a8496;
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 430px;
  gap: 16px;
}

.table-card,
.detail-card {
  min-width: 0;
  background: #ffffff;
  border: 1px solid #eceff5;
  border-radius: 14px;
  box-shadow: 0 1px 3px rgba(16, 24, 40, 0.04);
}

.table-card {
  overflow: hidden;
}

.filters-panel {
  border-bottom: 1px solid #f1f3f8;
  padding: 14px;
  display: grid;
  gap: 12px;
}

.filter-row,
.toolbar-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.filter-select,
.search-input {
  height: 34px;
  border: 1px solid #e6e9f0;
  border-radius: 8px;
  background: #ffffff;
  color: #242c3d;
  padding: 0 10px;
  font-weight: 700;
}

.search-input {
  width: 260px;
}

.toolbar-note {
  margin-left: auto;
  color: #7a8496;
  font-size: 12px;
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 1060px;
  border-collapse: collapse;
  table-layout: fixed;
}

th,
td {
  border-bottom: 1px solid #f1f3f8;
  padding: 12px 10px;
  text-align: left;
  vertical-align: middle;
  font-size: 13px;
}

th {
  background: #fafbfd;
  color: #5c6675;
  font-size: 12px;
  font-weight: 700;
}

tbody tr {
  cursor: pointer;
}

tbody tr:hover,
tbody tr.selected {
  background: #f1f3f8;
}

.check-col {
  width: 44px;
  text-align: center;
}

.id-cell {
  color: #1e41c9;
  font-weight: 700;
}

.type-tag,
.status-tag,
.ambiguity-tag,
.risk-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.type-tag.functional { color: #1e41c9; background: #eef2ff; }
.type-tag.performance { color: #1d8a5c; background: #e6f6ef; }
.type-tag.security { color: #d63a40; background: #fdecec; }
.type-tag.interface { color: #a855f7; background: #f1edff; }
.type-tag.data { color: #2b56f5; background: #eef2ff; }
.type-tag.environment { color: #c2410c; background: #fdf3e3; }
.type-tag.constraint { color: #b45309; background: #fdf3e3; }

.status-tag.accept { color: #1d8a5c; background: #e6f6ef; border: 1px solid #bfe6d2; }
.status-tag.reject { color: #d63a40; background: #fdecec; border: 1px solid #f6c8ca; }
.status-tag.warning { color: #b06f12; background: #fdf3e3; border: 1px solid #f3d9a0; }
.status-tag.review { color: #1e41c9; background: #eef2ff; border: 1px solid #c7d3fc; }
.status-tag.discuss { color: #7c5cff; background: #f1edff; border: 1px solid #ddd6fe; }

.ambiguity-tag.low,
.risk-badge.low { color: #1d8a5c; background: #e6f6ef; }
.ambiguity-tag.middle,
.risk-badge.middle { color: #b06f12; background: #fdf3e3; }
.ambiguity-tag.high,
.risk-badge.high { color: #d63a40; background: #fdecec; }

.confidence-cell {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.empty-cell {
  height: 96px;
  text-align: center;
  color: #7a8496;
  font-weight: 600;
  cursor: default;
}

.row-action {
  color: #2b56f5;
  font-weight: 700;
}

.table-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #7a8496;
  padding: 12px 16px;
  font-size: 13px;
}

.pagination {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page {
  min-width: 28px;
  height: 28px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  color: #3f4a61;
}

.page.active {
  background: #2b56f5;
  color: #ffffff;
}

.detail-card {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.detail-id {
  font-size: 20px;
  font-weight: 700;
}

.detail-subtitle {
  margin-top: 4px;
  color: #7a8496;
  font-size: 12px;
}

.detail-tabs {
  display: flex;
  gap: 16px;
  border-bottom: 1px solid #f1f3f8;
}

.detail-tab {
  border: 0;
  background: transparent;
  color: #3f4a61;
  padding: 10px 0;
  cursor: pointer;
  font-weight: 700;
}

.detail-tab.active {
  color: #2b56f5;
  box-shadow: inset 0 -2px #2b56f5;
}

.detail-stack {
  display: grid;
  gap: 10px;
}

.detail-section {
  border: 1px solid #eceff5;
  border-radius: 12px;
  padding: 12px;
  background: #ffffff;
}

.section-title {
  margin-bottom: 8px;
  color: #1a2233;
  font-size: 14px;
  font-weight: 700;
}

.detail-body p {
  margin: 8px 0;
  line-height: 1.7;
}

.meta-line {
  color: #7a8496;
  font-size: 12px;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.metrics-grid div {
  background: #fafbfd;
  border-radius: 10px;
  padding: 9px;
}

.metrics-grid span {
  display: block;
  color: #7a8496;
  font-size: 12px;
}

.metrics-grid strong {
  display: block;
  margin-top: 4px;
}

.progress-wrap {
  margin-top: 10px;
}

.progress-label {
  color: #7a8496;
  font-size: 12px;
  margin-bottom: 6px;
}

.progress-track {
  height: 8px;
  border-radius: 999px;
  background: #e8edf5;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  background: #1d8a5c;
}

.bullet-list {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 6px;
  line-height: 1.6;
}

.risk-list {
  margin-top: 8px;
  color: #b45309;
}

.note-box {
  margin-top: 10px;
  border: 1px solid #c7d3fc;
  border-radius: 10px;
  background: #eef2ff;
  color: #1e41c9;
  padding: 10px;
  font-size: 13px;
  line-height: 1.6;
}

.decision-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}

.decision-button {
  min-height: 38px;
}

.decision-button.accept { color: #1d8a5c; border-color: #8fd4b4; background: #e6f6ef; }
.decision-button.reject { color: #d63a40; border-color: #f6c8ca; background: #fdecec; }
.decision-button.discuss { color: #b06f12; border-color: #f3d9a0; background: #fdf3e3; }
.decision-button.expert { color: #1e41c9; border-color: #c7d3fc; background: #eef2ff; }

.comment-box {
  width: 100%;
  min-height: 88px;
  resize: vertical;
  border: 1px solid #e6e9f0;
  border-radius: 10px;
  padding: 10px;
  color: #242c3d;
}

.module-page {
  min-height: 520px;
  background: #ffffff;
  border: 1px solid #eceff5;
  border-radius: 14px;
  box-shadow: 0 1px 3px rgba(16, 24, 40, 0.04);
  padding: 24px;
}

.module-hero {
  border-bottom: 1px solid #f1f3f8;
  padding-bottom: 22px;
  margin-bottom: 22px;
}

.module-kicker {
  color: #2b56f5;
  font-size: 12px;
  font-weight: 700;
}

.module-hero h2 {
  margin: 8px 0 8px;
  font-size: 26px;
  letter-spacing: 0;
}

.module-hero p {
  margin: 0;
  max-width: 680px;
  color: #5c6675;
  line-height: 1.7;
}

.module-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.module-card {
  min-height: 136px;
  border: 1px solid #eceff5;
  border-radius: 12px;
  background: #fafbfd;
  padding: 18px;
}

.module-card-title {
  color: #1a2233;
  font-size: 15px;
  font-weight: 700;
}

.module-card-body {
  margin-top: 10px;
  color: #7a8496;
  line-height: 1.7;
  font-size: 13px;
}
@media (max-width: 1120px) {
  .shell {
    grid-template-columns: 64px minmax(0, 1fr);
  }

  .brand-text,
  .nav-title,
  .side-user div:not(.side-avatar),
  .nav-button span:not(.nav-icon) {
    display: none;
  }

  .side-brand {
    justify-content: center;
    padding: 2px 0;
  }

  .nav-button {
    justify-content: center;
    padding: 10px 6px;
  }

  .side-user {
    justify-content: center;
  }

  .summary-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .distribution-card {
    grid-column: span 3;
  }

  .workspace-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .module-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 980px) {
  .shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    display: none;
  }

  .workflow-stepper,
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .module-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

/* Phase 1 Chinese dashboard shell */
.shell {
  display: grid;
  grid-template-columns: 224px minmax(0, 1fr);
  height: 100vh;
  overflow: hidden;
  background: #fafbfd;
  color: #242c3d;
  font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif;
  letter-spacing: 0;
}

.side-nav {
  min-height: 0;
  overflow: auto;
  background: #ffffff;
  border-right: 1px solid #e6e9f0;
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.side-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 2px 6px;
}

.brand-mark {
  width: 34px;
  height: 34px;
  flex: none;
  display: grid;
  place-items: center;
  color: #ffffff;
  font-size: 15px;
  font-weight: 700;
  background: #2b56f5;
  border-radius: 9px;
}

.brand-text {
  min-width: 0;
}

.brand-name {
  font-size: 13px;
  font-weight: 650;
  line-height: 1.3;
  color: #1a2233;
}

.brand-sub {
  font-size: 10.5px;
  color: #98a1b3;
}

.nav-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-title {
  margin: 0 0 6px;
  padding: 0 10px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.1em;
  color: #98a1b3;
}

.nav-spacer {
  flex: 1;
}

.nav-button {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  border: 0;
  border-radius: 8px;
  color: #5c6675;
  padding: 9px 10px;
  text-align: left;
  font-size: 13px;
  font-weight: 500;
  background: transparent;
  cursor: pointer;
}

.nav-button:hover {
  background: #fafbfd;
  color: #1a2233;
}

.nav-button.active {
  background: #eef2ff;
  color: #2b56f5;
  font-weight: 600;
}

.nav-icon {
  width: 18px;
  display: grid;
  place-items: center;
  color: currentColor;
  font-size: 14px;
  line-height: 1;
  opacity: 0.8;
}

.side-user {
  display: flex;
  align-items: center;
  gap: 10px;
  border-top: 1px solid #e6e9f0;
  padding: 12px 6px 2px;
}

.side-avatar {
  width: 30px;
  height: 30px;
  flex: none;
  border-radius: 50%;
  background: #eef2ff;
  color: #2b56f5;
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 700;
}

.side-user b {
  display: block;
  font-size: 12.5px;
  font-weight: 600;
  color: #1a2233;
}

.side-user span {
  font-size: 11px;
  color: #98a1b3;
}

.main {
  height: 100vh;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.main > .app-bar {
  flex: none;
}

.main > .workspace,
.main > .run-home,
.main > .doc-review {
  flex: 1;
  min-height: 0;
}

.main > .status-bar {
  flex: none;
}

.app-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 16px 26px;
  background: #ffffff;
  border-bottom: 1px solid #e6e9f0;
}

.page-title-area {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-title {
  margin: 0;
  color: #1a2233;
  font-size: 19px;
  font-weight: 700;
  letter-spacing: 0;
  white-space: nowrap;
}

.doc-chip {
  font-size: 12px;
  color: #5c6675;
  background: #fafbfd;
  border: 1px solid #e6e9f0;
  border-radius: 999px;
  padding: 4px 12px;
  max-width: 340px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

/* 顶栏三组动作的分隔：文件操作 | 模式开关 | 运行 */
.action-divider {
  width: 1px;
  height: 20px;
  background: #e6e9f0;
  margin: 0 2px;
  flex: none;
}

.run-dashboard {
  display: grid;
  grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  grid-template-rows: auto minmax(0, 1fr);
  gap: 10px 14px;
  padding: 12px 26px;
  background: #ffffff;
  border-bottom: 1px solid #e6e9f0;
}

/* 左右对齐（真实反馈 2026-07-09）：dashboard 双行网格,面板 display:contents 让
   左边两卡与右边"进度行/流水线行"各占同一行——同高同比例,不再左短右长 */
.run-paths-panel,
.run-stage-panel {
  display: contents;
}

.run-paths-panel .selection-item:first-child { grid-column: 1; grid-row: 1; }
.run-paths-panel .selection-item:last-child { grid-column: 1; grid-row: 2; }
.run-stage-panel .run-meter { grid-column: 2; grid-row: 1; }
.run-stage-panel /* ===== 运行页(样机 1:1,2026-07-09) ===== */
.run-home {
  min-height: 0;
  overflow-y: auto;
  padding: 18px 26px 24px;
  display: grid;
  gap: 14px;
  align-content: start;
  background: #f6f7fa;
}

.ov-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.ov-stat {
  background: #ffffff;
  border: 1px solid #e6e9f0;
  border-radius: 12px;
  padding: 14px 16px 12px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
}

.ov-stat .k {
  font-size: 12px;
  color: #5c6675;
}

.ov-stat .v {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 0;
  font-variant-numeric: tabular-nums;
  margin-top: 2px;
  color: #1a2233;
}

.ov-stat .d {
  font-size: 11.5px;
  margin-top: 1px;
}

.ov-stat .d.up { color: #1d8a5c; }
.ov-stat .d.flat { color: #98a1b3; }
.ov-stat .d.warn { color: #cc8925; }

/* 空态：未运行时数值降级为浅灰小字，不再用整排大"—"抢占首屏 */
.ov-stat.is-empty .v {
  font-size: 15px;
  font-weight: 500;
  color: #c3c9d6;
  padding: 6px 0 5px;
}

.flow-card,
.panel-card {
  background: #ffffff;
  border: 1px solid #e6e9f0;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
  padding: 16px 18px;
  min-width: 0;
}

.path-hint {
  font-style: normal;
  color: #b6bdcb;
  margin-left: 10px;
  font-size: 11.5px;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  vertical-align: bottom;
}

.run-grid {
  display: grid;
  grid-template-columns: 1.55fr 1fr;
  gap: 12px;
  align-items: stretch;
}

.run-grid .panel-card {
  display: flex;
  flex-direction: column;
}

.run-grid .panel-card .dl-files {
  flex: 1;
}

.link-button {
  border: 0;
  background: none;
  color: #2b56f5;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 6px;
}

.link-button:hover { background: #eef2ff; }

.preview-wrap { overflow-x: auto; }

.preview-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 44px 16px;
  color: #b6bdcb;
  text-align: center;
}

.preview-empty p {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: #5c6675;
}

.preview-empty span { font-size: 12px; }

.preview-table {
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
}

.preview-table th {
  text-align: left;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: #98a1b3;
  padding: 7px 10px;
  border-bottom: 1px solid #e6e9f0;
  white-space: nowrap;
}

.preview-table td {
  padding: 10px;
  border-bottom: 1px solid #eef0f5;
  vertical-align: middle;
}

.preview-table tbody tr { cursor: pointer; }
.preview-table tbody tr:hover td { background: #fafbfd; }
.preview-table tr:last-child td { border-bottom: 0; }
.preview-table .rid { font-family: Consolas, monospace; font-size: 12px; color: #5c6675; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.preview-table .req-cell { max-width: 360px; }
.preview-table .num { font-variant-numeric: tabular-nums; }

.pchip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 550;
  border-radius: 999px;
  padding: 2px 10px;
  white-space: nowrap;
}

.pchip::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.pchip.plain { background: #f1f3f8; color: #5c6675; border: 1px solid #e6e9f0; }
.pchip.plain::before { display: none; }
.pchip.st-accepted { background: #e6f6ef; color: #1d8a5c; }
.pchip.st-rejected { background: #fdecec; color: #d63a40; }
.pchip.st-needs_discussion, .pchip.st-expert_pending { background: #fdf3e3; color: #cc8925; }
.pchip.st-candidate, .pchip.st-ai_generated, .pchip.st-frozen { background: #f1edff; color: #7c5cff; }

.dl-files { display: flex; flex-direction: column; }

.dl-file {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 2px;
  border-bottom: 1px solid #eef0f5;
}

.dl-file:last-child { border-bottom: 0; }

.dl-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  font-size: 10px;
  font-weight: 700;
  flex: none;
}

.dl-icon.xls { background: #e6f6ef; color: #1d8a5c; }
.dl-icon.htm { background: #fdf3e3; color: #cc8925; }
.dl-icon.jsn { background: #eef2ff; color: #2b56f5; }

.dl-name { flex: 1; min-width: 0; }
.dl-name strong { display: block; font-size: 13px; font-weight: 600; color: #1a2233;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dl-name small { font-size: 11.5px; color: #98a1b3; }

.note-warn {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 12.5px;
  margin-top: 12px;
  background: #fdf3e3;
  color: #cc8925;
}

.note-warn b { font-weight: 650; flex: none; }

.note-insight {
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 12.5px;
  margin-top: 12px;
  background: #eef2ff;
  color: #1e41c9;
}

.note-insight b { font-weight: 650; }
.insight-list { margin: 6px 0 0; padding-left: 18px; display: grid; gap: 4px; }

/* 最近结果:重启自动恢复 + 一键打开历史输出目录 */
.recent-card { margin-top: 14px; }

.recent-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}

.recent-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #e6e9f0;
  border-radius: 10px;
  background: #fff;
  color: #1a2233;
  font-size: 12.5px;
  text-align: left;
  cursor: pointer;
}

.recent-item:hover:not(:disabled) { border-color: #b9c6f2; background: #f7f9ff; }
.recent-item:disabled { cursor: default; opacity: 0.65; }
.recent-item.is-current { border-color: #c8d6ff; background: #f2f6ff; }
.recent-label { font-weight: 650; flex: none; max-width: 40%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.recent-path { color: #6b7487; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.recent-time { color: #98a0b3; flex: none; font-size: 12px; }
.recent-missing { color: #b4562a; flex: none; font-size: 12px; }
.recent-current { color: #1e41c9; flex: none; font-size: 12px; font-weight: 650; }

/* 流水线格子:样机形态(左色条 + 底部细进度条) */
.run-stage-board .run-stage-card { position: relative; }

.stage-bar {
  display: block;
  height: 4px;
  border-radius: 2px;
  background: #eef0f5;
  margin-top: 6px;
  overflow: hidden;
}

.stage-bar i {
  display: block;
  height: 100%;
  border-radius: 2px;
  background: #2b56f5;
  transition: width 0.3s;
}

.run-stage-card.stage-ok .stage-bar i { background: #22a06b; }
.run-stage-card.stage-skipped .stage-bar i { background: #98a1b3; }
.run-stage-card.stage-failed .stage-bar i { background: #e5484d; }

.stage-flow-card { grid-column: 2; grid-row: 2; }

.stage-flow-card {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 8px;
  border: 1px solid #e6e9f0;
  border-radius: 10px;
  background: #ffffff;
  padding: 12px 14px;
}

.selection-item {
  min-width: 0;
  display: grid;
  align-content: center;
  gap: 5px;
  border: 1px solid #e6e9f0;
  border-radius: 10px;
  background: #fafbfd;
  padding: 8px 12px;
}

.selection-item span,
.run-meter-head span {
  color: #98a1b3;
  font-size: 12px;
  font-weight: 600;
}

.selection-item strong {
  min-width: 0;
  color: #242c3d;
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.run-meter {
  min-width: 0;
  min-height: 52px;
  display: grid;
  align-content: center;
  gap: 5px;
  border: 1px solid #c7d3fc;
  border-radius: 8px;
  background: #eef2ff;
  padding: 8px 12px;
}

.run-meter-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.run-meter-head strong {
  color: #1e41c9;
  font-size: 13px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.run-meter-detail {
  min-width: 0;
  color: #5c6675;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.run-meter-track {
  height: 8px;
  border-radius: 999px;
  background: #d8e5ff;
  overflow: hidden;
}

.run-meter-fill {
  height: 100%;
  border-radius: inherit;
  background: #2b56f5;
  transition: width 180ms ease;
}

.run-stage-board {
  min-width: 0;
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(0, 1fr);
  gap: 8px;
  padding-bottom: 2px;
}

/* 窄窗口两行排布（每行 5 张），仍不横向滚动 */
@media (max-width: 1240px) {
  .run-stage-board {
    grid-auto-flow: row;
    grid-template-columns: repeat(5, minmax(0, 1fr));
  }
}

.board-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 8px;
}

.board-head h4 {
  margin: 0;
  font-size: 13.5px;
  font-weight: 650;
  color: #1a2233;
}

.board-head span {
  font-size: 11.5px;
  color: #98a1b3;
}

/* 流水线形态（设计提案 2026-07-09）：左侧色条编码状态——绿=完成/蓝=进行/灰=等待或复用/红=失败 */
.run-stage-card {
  min-width: 0;
  min-height: 92px;
  height: auto;
  display: grid;
  align-content: center;
  gap: 4px;
  border: 1px solid #e6e9f0;
  border-left: 3px solid #d5dae4;
  border-radius: 8px;
  background: #ffffff;
  padding: 9px 10px 9px 12px;
}

.stage-name {
  color: #242c3d;
  font-size: 12.5px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stage-status {
  color: #98a1b3;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stage-detail {
  color: #98a1b3;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stage-elapsed {
  color: #7f8aa0;
  font-size: 10.5px;
  font-weight: 500;
}

/* 停滞提示：距上次进度事件超过阈值——单章 LLM 调用慢≠死，给用户可判读的依据 */
.stage-stall {
  color: #cc8925;
  font-size: 10.5px;
  font-weight: 600;
  animation: stall-pulse 1.6s ease-in-out infinite;
}

@keyframes stall-pulse {
  50% { opacity: 0.55; }
}

.run-meter-stall {
  margin-top: 2px;
  font-size: 11.5px;
  font-weight: 600;
  color: #cc8925;
}

.run-stage-card.stage-running {
  border-left-color: #2b56f5;
  background: #ffffff;
}

.run-stage-card.stage-running .stage-status {
  color: #1e41c9;
}

.run-stage-card.stage-ok {
  border-left-color: #22a06b;
  background: #ffffff;
}

.run-stage-card.stage-skipped {
  border-left-color: #98a1b3;
  background: #ffffff;
}

.run-stage-card.stage-ok .stage-status {
  color: #1d8a5c;
}

.run-stage-card.stage-skipped .stage-status {
  color: #5c6675;
}

.run-stage-card.stage-failed {
  border-left-color: #e5484d;
  background: #fdecec;
}

.run-stage-card.stage-failed .stage-status {
  color: #d63a40;
}

.run-stage-card.stage-disabled {
  opacity: 0.58;
}

/* 交付物入口行（设计提案:file-row 形态） */
.deliverable-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  border: 1px solid #e6e9f0;
  border-radius: 8px;
  background: #ffffff;
  padding: 8px 12px;
}

.deliverable-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  font-size: 10px;
  font-weight: 700;
  background: #fdf3e3;
  color: #cc8925;
  flex: none;
}

.deliverable-name {
  flex: 1;
  min-width: 0;
}

.deliverable-name strong {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #1a2233;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.deliverable-name small {
  font-size: 11.5px;
  color: #98a1b3;
}

.deliverable-open {
  border: 0;
  background: none;
  color: #2b56f5;
  font-size: 13px;
  font-weight: 600;
  padding: 5px 10px;
  border-radius: 6px;
  cursor: pointer;
}

.deliverable-open:hover {
  background: #eef2ff;
}

.button {
  min-height: 36px;
  padding: 0 14px;
  border: 1px solid #d5dae4;
  border-radius: 8px;
  color: #333d52;
  background: #ffffff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
}

.button.primary {
  color: #ffffff;
  border-color: #1e41c9;
  background: #2b56f5;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.08);
}

.button:disabled,
.mini-button:disabled {
  color: #98a1b3;
  background: #f1f3f8;
  border-color: #e0e5eb;
  box-shadow: none;
  cursor: default;
}

.llm-toggle,
.switch-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #4a5568;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}

.stat-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  padding: 18px 26px;
  background: #fafbfd;
  border-bottom: 1px solid #e6e9f0;
}

.stat-card {
  min-width: 0;
  height: 82px;
  padding: 13px 16px;
  border: 1px solid #e6e9f0;
  border-radius: 12px;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: 12px;
  text-align: left;
  cursor: pointer;
}

.stat-card.active {
  border-color: #c7d3fc;
  background: linear-gradient(180deg, #ffffff 0%, #fafbfd 100%);
}

.stat-label {
  color: #98a1b3;
  font-size: 13px;
  font-weight: 600;
}

.stat-value {
  display: block;
  margin-top: 5px;
  color: #1a2233;
  font-size: 24px;
  letter-spacing: 0;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  font-weight: 700;
}

.stat-hint {
  align-self: start;
  height: 24px;
  padding: 0 8px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  color: #6f83d8;
  background: #eef2ff;
  font-size: 12px;
  font-weight: 600;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 26px;
  background: #ffffff;
  border-bottom: 1px solid #e6e9f0;
}

.filter-select,
.search-input {
  height: 38px;
  border: 1px solid #d5dae4;
  border-radius: 8px;
  background: #ffffff;
  color: #333d52;
  padding: 0 11px;
  font-size: 13px;
  font-weight: 700;
}

.filter-select {
  min-width: 152px;
}

.search-input {
  flex: 1 1 auto;
  min-width: 280px;
}

.table-review-band {
  flex: none;
  max-height: 220px;
  overflow: auto;
  background: #fffaf0;
  border-bottom: 1px solid #ead7ad;
}

.table-review-band-head,
.table-review-row {
  min-height: 42px;
  padding: 8px 26px;
  display: flex;
  align-items: center;
  gap: 14px;
}

.table-review-band-head {
  justify-content: space-between;
  color: #72510d;
  font-size: 12px;
  font-weight: 700;
}

.table-review-band-title {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
}

.table-review-row {
  border-top: 1px solid #f0dfba;
  background: #ffffff;
}

.table-review-summary {
  width: 230px;
  min-width: 0;
  display: grid;
  gap: 2px;
  color: #6e5a31;
  font-size: 11px;
}

.table-review-summary strong {
  overflow: hidden;
  color: #2f3542;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-review-audit {
  color: #1e41c9;
  font-weight: 700;
}

.table-review-decisions {
  min-width: 0;
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  overflow-x: auto;
}

.table-review-cell {
  min-width: 310px;
  display: grid;
  grid-template-columns: minmax(110px, 1fr) 88px 96px;
  gap: 6px;
  align-items: center;
}

.table-review-cell-source {
  min-width: 0;
  color: #7a8496;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-review-cell-source b {
  margin-left: 5px;
  color: #333d52;
  font-size: 12px;
}

.table-review-cell select {
  width: 100%;
  height: 30px;
  border: 1px solid #d5dae4;
  border-radius: 6px;
  background: #ffffff;
  color: #333d52;
  font-size: 12px;
}

.table-review-confirm {
  flex: none;
  min-width: 118px;
  justify-content: center;
}

.workspace {
  min-height: 0;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 400px;
  background: #fafbfd;
}

.table-panel,
.detail-panel {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  background: #ffffff;
}

.table-panel {
  border-right: 1px solid #e6e9f0;
}

.panel-head {
  min-height: 52px;
  padding: 10px 20px;
  border-bottom: 1px solid #e6e9f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.panel-title {
  color: #242c3d;
  font-size: 15px;
  font-weight: 700;
}

.panel-subtitle {
  color: #98a1b3;
  font-size: 12px;
  font-weight: 700;
}

.table-wrap {
  min-height: 0;
  overflow-x: auto;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable both-edges;
}

table {
  width: 100%;
  min-width: 1260px;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 13px;
}

thead th {
  height: 42px;
  padding: 0 12px;
  color: #5c6675;
  background: #fafbfd;
  border-bottom: 1px solid #e6e9f0;
  text-align: left;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

tbody td {
  height: 62px;
  padding: 8px 12px;
  border-bottom: 1px solid #eceff5;
  color: #333d52;
  vertical-align: middle;
  overflow: hidden;
  text-overflow: ellipsis;
}

tbody tr {
  cursor: pointer;
}

tbody tr.selected td,
tbody tr:hover td {
  background: #f1f3f8;
}

tbody tr.virtual-spacer,
tbody tr.virtual-spacer:hover {
  cursor: default;
}

tbody tr.virtual-spacer td,
tbody tr.virtual-spacer:hover td {
  padding: 0;
  border: 0;
  background: transparent;
}

.batch-accept-button {
  min-height: 36px;
  white-space: nowrap;
}

.col-id {
  width: 116px;
}

.col-module {
  width: 108px;
}

.col-category {
  width: 132px;
}

.col-type {
  width: 76px;
}

.col-object {
  width: 150px;
}

.col-confidence {
  width: 86px;
}

.col-status {
  width: 96px;
}

.col-amb {
  width: 72px;
}

.requirement-cell {
  line-height: 1.35;
  white-space: normal;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.type-tag,
.module-chip,
.category-chip,
.status-tag,
.ambiguity-tag,
.risk-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  max-width: 100%;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.module-chip,
.category-chip {
  color: #1e41c9;
  background: #eaf4f8;
}

.category-chip {
  color: #7c5cff;
  background: #f1edff;
}

.type-tag.functional,
.type-tag.interface,
.type-tag.data,
.type-tag.environment,
.type-tag.constraint {
  color: #1e41c9;
  background: #e7efff;
}

.type-tag.security,
.type-tag.performance {
  color: #7c5cff;
  background: #f1edff;
}

.status-tag.accept {
  color: #1d8a5c;
  background: #e6f6ef;
  border: 1px solid #bfe6d2;
}

.status-tag.reject {
  color: #b42318;
  background: #fdecec;
  border: 1px solid #f6c8ca;
}

.status-tag.warning {
  color: #b06f12;
  background: #fdf3e3;
  border: 1px solid #f3d9a0;
}

.status-tag.review {
  color: #1e41c9;
  background: #e7efff;
  border: 1px solid #c7d3fc;
}

.status-tag.discuss {
  color: #7c5cff;
  background: #f1edff;
  border: 1px solid #ddd6fe;
}

.ambiguity-tag.low,
.risk-badge.low {
  color: #1d8a5c;
  background: #e6f6ef;
}

.ambiguity-tag.middle,
.risk-badge.middle {
  color: #b06f12;
  background: #fdf3e3;
}

.ambiguity-tag.high,
.risk-badge.high {
  color: #b42318;
  background: #fdecec;
}

.id-cell,
.confidence-cell {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.id-cell {
  color: #2b56f5;
}

.empty-cell {
  height: 96px;
  text-align: center;
  color: #7a8496;
  font-weight: 600;
  cursor: default;
}

.detail-panel {
  grid-template-rows: auto minmax(0, 1fr);
  min-height: 0;
}

.detail-content {
  min-height: 0;
  padding: 16px 18px 18px;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  display: grid;
  grid-auto-rows: max-content;
  gap: 12px;
  background: #fafbfd;
}

.readonly-card,
.mini-row,
.review-box {
  border: 1px solid #e6e9f0;
  border-radius: 10px;
  background: #ffffff;
  overflow: hidden;
}

.readonly-head,
.mini-head {
  min-height: 34px;
  padding: 8px 12px 7px;
  color: #333d52;
  background: #fafbfd;
  border-bottom: 1px solid #e7ecf2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
  font-weight: 700;
}

.readonly-body,
.mini-body,
.review-body {
  padding: 11px 12px 12px;
  color: #333d52;
  font-size: 13px;
  line-height: 1.55;
}

.readonly-body.muted {
  color: #98a1b3;
}

.mini-button {
  height: 26px;
  padding: 0 10px;
  border: 1px solid #d5dae4;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 600;
}

.metadata {
  border: 1px solid #e6e9f0;
  border-radius: 10px;
  background: #ffffff;
  padding: 12px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 10px;
}

.metadata-item {
  min-width: 0;
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  font-size: 12px;
}

.metadata-key {
  color: #98a1b3;
  font-weight: 600;
}

.metadata-value {
  min-width: 0;
  color: #333d52;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-body p {
  margin: 0 0 6px;
}

.bullet-list {
  margin: 8px 0 0;
  padding-left: 18px;
  display: grid;
  gap: 6px;
  line-height: 1.6;
}

.detail-actions {
  min-height: 42px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.comment-box {
  width: 100%;
  min-height: 72px;
  resize: vertical;
  border: 1px solid #d5dae4;
  border-radius: 10px;
  padding: 10px;
  color: #242c3d;
  font-family: inherit;
}

.api-message {
  color: #1e41c9;
  background: #eef2ff;
  border: 1px solid #c7d3fc;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 12px;
  font-weight: 600;
}

.settings-overlay {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: 28px;
  background: rgba(16, 24, 40, 0.36);
}

.settings-dialog {
  width: min(720px, 100%);
  max-height: min(760px, calc(100vh - 56px));
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 18px 50px rgba(16, 24, 40, 0.14);
}

.settings-head {
  min-height: 70px;
  padding: 16px 18px;
  border-bottom: 1px solid #e6e9f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.settings-title {
  color: #242c3d;
  font-size: 20px;
  line-height: 1.2;
  font-weight: 700;
}

.settings-subtitle {
  margin-top: 4px;
  color: #98a1b3;
  font-size: 13px;
  font-weight: 700;
}

.icon-button {
  width: 34px;
  height: 34px;
  border: 1px solid #d5dae4;
  border-radius: 8px;
  background: #ffffff;
  color: #3f4a61;
  display: grid;
  place-items: center;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
}

.icon-button:hover {
  color: #1e41c9;
  border-color: #c7d3fc;
  background: #fafbfd;
}

.settings-body {
  min-height: 0;
  overflow: auto;
  padding: 18px;
  display: grid;
  gap: 14px;
  background: #fafbfd;
}

.settings-section {
  border: 1px solid #e6e9f0;
  border-radius: 10px;
  background: #ffffff;
  padding: 14px;
  display: grid;
  gap: 10px;
}

.settings-section-title {
  color: #242c3d;
  font-size: 14px;
  font-weight: 700;
}

.global-message { display: flex; align-items: center; gap: 8px; margin: 8px 16px 0; padding: 8px 12px;
  background: #eef2ff; border: 1px solid #c7d3fc; border-radius: 8px; font-size: 13px; color: #1e41c9; }
.global-message-icon { flex: none; }
.global-message-text { flex: 1; min-width: 0; white-space: pre-wrap; word-break: break-word; }
/* 长摘要（运行完成链路+一致性统计）默认一行折叠，「详情」展开全文 */
.global-message-text.clamped { display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
.global-message-toggle { border: 0; background: none; color: #1e41c9; font-size: 12px; font-weight: 600;
  cursor: pointer; flex: none; padding: 2px 4px; }
.global-message-toggle:hover { text-decoration: underline; }
.global-message-close { margin-left: auto; border: 0; background: none; color: #aebdfb; cursor: pointer;
  display: grid; place-items: center; padding: 2px; flex: none; }
.global-message-close:hover { color: #1e41c9; }

.template-row { display: flex; align-items: center; gap: 8px; margin: 10px 0 4px; }
.template-row .field-label { font-size: 12px; color: #7a8496; white-space: nowrap; }
.template-row input { flex: 1; font-size: 12px; padding: 6px 8px; border: 1px solid #e6e9f0; border-radius: 6px; background: #fafbfd; color: #3f4a61; }

.settings-toggle {
  min-height: 58px;
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid #e7ecf2;
  border-radius: 8px;
  background: #fafbfd;
  padding: 10px 12px;
  color: #333d52;
}

.settings-toggle input {
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
}

.settings-toggle span {
  display: grid;
  gap: 3px;
}

.settings-toggle strong,
.settings-row strong,
.settings-kb-list li {
  color: #333d52;
  font-size: 13px;
  font-weight: 700;
}

.settings-toggle small {
  color: #98a1b3;
  font-size: 12px;
  line-height: 1.45;
}

.settings-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 12px;
}

.settings-field {
  min-width: 0;
  display: grid;
  gap: 6px;
}

.settings-field.wide {
  grid-column: 1 / -1;
}

.settings-field span {
  color: #98a1b3;
  font-size: 12px;
  font-weight: 600;
}

.settings-field input {
  width: 100%;
  height: 36px;
  border: 1px solid #d5dae4;
  border-radius: 8px;
  background: #ffffff;
  color: #333d52;
  padding: 0 10px;
  font: inherit;
  font-size: 13px;
  font-weight: 700;
}

.settings-field input:focus {
  outline: none;
  border-color: #9db1fa;
  box-shadow: 0 0 0 3px rgba(43, 86, 245, 0.12);
}

.settings-actions {
  min-height: 38px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.settings-status {
  min-width: 0;
  color: #1e41c9;
  font-size: 12px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.settings-row,
.settings-kb-list {
  min-width: 0;
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.settings-row span,
.settings-kb-list > span {
  color: #98a1b3;
  font-size: 12px;
  font-weight: 600;
}

.settings-row strong {
  min-width: 0;
  overflow-wrap: anywhere;
}

.settings-kb-list ul {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 5px;
}

.status-bar {
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  color: #5c6675;
  background: #ffffff;
  border-top: 1px solid #e6e9f0;
  font-size: 12px;
  font-weight: 700;
}

.kbd-hints {
  color: #98a1b3;
}

@media (max-width: 1180px) {
  .main {
    grid-template-rows: auto auto auto auto minmax(0, 1fr) 32px;
  }

  .app-bar,
  .filter-bar {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .run-dashboard {
    grid-template-columns: minmax(0, 1fr);
  }

  .stat-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .workspace {
    grid-template-columns: minmax(0, 1fr);
  }
}

/* iOS / iPadOS inspired visual system: quiet, translucent, and work-focused. */
.shell {
  --ios-blue: #0a84ff;
  --ios-blue-strong: #0071e3;
  --ios-green: #30a46c;
  --ios-red: #e5484d;
  --ios-amber: #d58a18;
  --ios-ink: #1d1d1f;
  --ios-secondary: #6e6e73;
  --ios-tertiary: #98989d;
  --ios-border: rgba(60, 60, 67, 0.14);
  --ios-border-strong: rgba(60, 60, 67, 0.2);
  --ios-glass: rgba(255, 255, 255, 0.76);
  --ios-glass-strong: rgba(255, 255, 255, 0.9);
  --ios-fill: rgba(118, 118, 128, 0.1);
  --ios-shadow: 0 12px 34px rgba(31, 35, 48, 0.08), 0 2px 8px rgba(31, 35, 48, 0.04);
  --ios-motion: cubic-bezier(0.22, 1, 0.36, 1);
  grid-template-columns: 236px minmax(0, 1fr);
  background: #f1f3f7;
  color: var(--ios-ink);
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI Variable", "Microsoft YaHei UI", sans-serif;
}

.side-nav {
  position: relative;
  z-index: 20;
  background: rgba(248, 249, 252, 0.76);
  border-right: 1px solid var(--ios-border);
  box-shadow: inset -1px 0 rgba(255, 255, 255, 0.58);
  backdrop-filter: blur(28px) saturate(175%);
  -webkit-backdrop-filter: blur(28px) saturate(175%);
  padding: 14px 12px 12px;
  gap: 14px;
}

.side-brand {
  gap: 11px;
  padding: 4px 8px 10px;
}

.brand-mark {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--ios-blue);
  box-shadow: 0 7px 16px rgba(10, 132, 255, 0.24), inset 0 1px rgba(255, 255, 255, 0.28);
}

.brand-name {
  color: var(--ios-ink);
  font-size: 13px;
  font-weight: 680;
}

.brand-sub,
.nav-title,
.side-user span {
  color: var(--ios-tertiary);
}

.nav-title {
  margin-bottom: 5px;
  font-size: 10.5px;
  font-weight: 650;
  letter-spacing: 0;
}

.nav-button {
  min-height: 40px;
  gap: 10px;
  border-radius: 8px;
  color: #5b6070;
  padding: 9px 10px;
  font-size: 13px;
  font-weight: 560;
  transition: color 180ms ease, background 180ms ease, box-shadow 180ms ease, transform 240ms var(--ios-motion);
}

.nav-button:hover {
  color: var(--ios-ink);
  background: rgba(255, 255, 255, 0.72);
  transform: translateX(2px);
}

.nav-button:active {
  transform: scale(0.975);
}

.nav-button.active {
  color: var(--ios-blue-strong);
  background: rgba(10, 132, 255, 0.11);
  box-shadow: inset 0 0 0 1px rgba(10, 132, 255, 0.08);
  font-weight: 650;
}

.nav-icon {
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  opacity: 0.92;
}

.side-user {
  gap: 9px;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.54);
  padding: 9px;
  box-shadow: inset 0 0 0 1px rgba(60, 60, 67, 0.04);
}

.side-avatar {
  width: 32px;
  height: 32px;
  color: var(--ios-blue-strong);
  background: rgba(10, 132, 255, 0.11);
}

.main {
  background: #f1f3f7;
}

.app-bar {
  position: relative;
  z-index: 12;
  min-height: 66px;
  padding: 12px 20px;
  gap: 18px;
  background: rgba(255, 255, 255, 0.8);
  border-bottom: 1px solid var(--ios-border);
  box-shadow: 0 1px rgba(255, 255, 255, 0.7), 0 8px 24px rgba(31, 35, 48, 0.035);
  backdrop-filter: blur(26px) saturate(180%);
  -webkit-backdrop-filter: blur(26px) saturate(180%);
}

.page-title {
  color: var(--ios-ink);
  font-size: 20px;
  font-weight: 720;
  letter-spacing: 0;
}

.doc-chip {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ios-secondary);
  background: rgba(118, 118, 128, 0.08);
  border: 1px solid rgba(60, 60, 67, 0.08);
  border-radius: 8px;
  padding: 5px 9px;
}

.app-actions {
  gap: 8px;
}

.button,
.mini-button {
  min-height: 35px;
  border: 1px solid var(--ios-border);
  border-radius: 8px;
  color: #30313a;
  background: rgba(255, 255, 255, 0.72);
  box-shadow: 0 1px 2px rgba(31, 35, 48, 0.045), inset 0 1px rgba(255, 255, 255, 0.74);
  backdrop-filter: blur(14px) saturate(150%);
  -webkit-backdrop-filter: blur(14px) saturate(150%);
  transition: color 160ms ease, border-color 160ms ease, background 160ms ease, box-shadow 180ms ease, transform 220ms var(--ios-motion);
}

.button:hover:not(:disabled),
.mini-button:hover:not(:disabled) {
  color: var(--ios-ink);
  border-color: var(--ios-border-strong);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 5px 14px rgba(31, 35, 48, 0.08), inset 0 1px rgba(255, 255, 255, 0.88);
  transform: translateY(-1px);
}

.button:active:not(:disabled),
.mini-button:active:not(:disabled),
.deliverable-open:active,
.link-button:active {
  transform: scale(0.965);
}

.button.primary {
  color: #fff;
  border-color: rgba(0, 94, 214, 0.72);
  background: var(--ios-blue);
  box-shadow: 0 7px 16px rgba(10, 132, 255, 0.22), inset 0 1px rgba(255, 255, 255, 0.22);
}

.button.icon-tool {
  width: 35px;
  min-width: 35px;
  padding: 0;
}

.button.primary:hover:not(:disabled) {
  color: #fff;
  border-color: var(--ios-blue-strong);
  background: var(--ios-blue-strong);
  box-shadow: 0 9px 20px rgba(10, 132, 255, 0.25);
}

.decision-accept { color: #167d4c; }
.decision-reject { color: #c7373d; }

.llm-toggle {
  min-height: 35px;
  gap: 7px;
  border: 1px solid rgba(60, 60, 67, 0.08);
  border-radius: 8px;
  background: rgba(118, 118, 128, 0.07);
  padding: 5px 9px;
  color: var(--ios-secondary);
  cursor: pointer;
}

.llm-track {
  width: 36px;
  height: 22px;
  background: #c7c7cc;
  transition: background 180ms ease, box-shadow 180ms ease;
}

.llm-track::after {
  width: 18px;
  height: 18px;
  box-shadow: 0 2px 5px rgba(31, 35, 48, 0.24);
  transition: transform 260ms var(--ios-motion);
}

.llm-toggle input:checked + .llm-track {
  background: #34c759;
  box-shadow: inset 0 0 0 1px rgba(25, 130, 55, 0.12);
}

.llm-toggle input:checked + .llm-track::after {
  left: 2px;
  transform: translateX(14px);
}

.run-home {
  padding: 16px 20px 22px;
  gap: 12px;
  background: transparent;
}

.ov-stats {
  gap: 10px;
}

.ov-stat,
.flow-card,
.panel-card,
.stat-card {
  border: 1px solid rgba(255, 255, 255, 0.76);
  border-radius: 8px;
  background: var(--ios-glass);
  box-shadow: var(--ios-shadow), inset 0 0 0 1px rgba(60, 60, 67, 0.075);
  backdrop-filter: blur(22px) saturate(160%);
  -webkit-backdrop-filter: blur(22px) saturate(160%);
}

.ov-stat {
  min-height: 88px;
  padding: 13px 15px 12px;
  transition: transform 260ms var(--ios-motion), box-shadow 200ms ease;
}

.ov-stat:hover {
  transform: translateY(-2px);
  box-shadow: 0 16px 34px rgba(31, 35, 48, 0.1), inset 0 0 0 1px rgba(60, 60, 67, 0.08);
}

.ov-stat .k,
.board-head span,
.path-hint,
.panel-subtitle,
.stat-label {
  color: var(--ios-tertiary);
}

.ov-stat .v,
.board-head h4,
.panel-title,
.stat-value {
  color: var(--ios-ink);
}

.flow-card,
.panel-card {
  padding: 15px 17px;
}

.run-meter {
  border: 1px solid rgba(10, 132, 255, 0.18);
  border-radius: 8px;
  background: rgba(10, 132, 255, 0.075);
}

.run-meter-track,
.stage-bar {
  background: rgba(118, 118, 128, 0.13);
}

.run-meter-fill,
.stage-bar i {
  background: var(--ios-blue);
  transition: width 420ms var(--ios-motion);
}

.run-stage-board {
  gap: 16px;
  padding: 8px 4px 10px;
  scroll-padding-inline: 4px;
  scrollbar-width: thin;
}

.run-stage-card {
  min-height: 88px;
  isolation: isolate;
  border: 0;
  border-left: 3px solid #c7c7cc;
  border-radius: 7px;
  background: rgba(118, 118, 128, 0.055);
  box-shadow: inset 0 0 0 1px rgba(60, 60, 67, 0.08);
  transition: background 180ms ease, transform 220ms var(--ios-motion), box-shadow 180ms ease;
}

.run-stage-card:hover {
  background: rgba(255, 255, 255, 0.72);
  transform: translateY(-1px);
}

.run-stage-card.stage-running {
  border-left-color: var(--ios-blue);
  background: rgba(10, 132, 255, 0.075);
  box-shadow: inset 0 0 0 1px rgba(10, 132, 255, 0.12), 0 5px 14px rgba(10, 132, 255, 0.08);
  animation: stage-card-live 2.4s ease-in-out infinite;
}

.run-stage-card.stage-ok { border-left-color: var(--ios-green); }
.run-stage-card.stage-failed { border-left-color: var(--ios-red); }

.stage-title-row {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
}

.stage-title-row .stage-name {
  min-width: 0;
  flex: 1;
}

.stage-signal {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  border: 1px solid rgba(60, 60, 67, 0.2);
  border-radius: 50%;
  background: rgba(118, 118, 128, 0.16);
}

.stage-running .stage-signal {
  border-color: rgba(10, 132, 255, 0.34);
  background: var(--ios-blue);
  animation: stage-signal-pulse 1.8s ease-out infinite;
}

.stage-ok .stage-signal {
  border-color: rgba(29, 138, 92, 0.26);
  background: var(--ios-green);
}

.stage-skipped .stage-signal {
  border-color: rgba(118, 118, 128, 0.26);
  background: #8e8e93;
}

.stage-failed .stage-signal {
  border-color: rgba(214, 58, 64, 0.3);
  background: var(--ios-red);
}

.stage-disabled .stage-signal {
  border-style: dashed;
  background: transparent;
}

.stage-running .stage-bar i {
  position: relative;
  min-width: 12px;
  max-width: 100%;
  overflow: hidden;
  background: linear-gradient(90deg, var(--ios-blue-strong), #52adff);
  box-shadow: 0 0 8px rgba(10, 132, 255, 0.25);
}

.stage-running .stage-bar i::after {
  content: "";
  position: absolute;
  inset: 0;
  width: 58%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.82), transparent);
  animation: stage-progress-sweep 1.35s ease-in-out infinite;
}

.stage-bar {
  position: relative;
}

.stage-bar.is-indeterminate > i {
  min-width: 0;
  opacity: 0;
  transition: none;
}

.stage-indeterminate-runner {
  display: none;
}

.stage-bar.is-indeterminate .stage-indeterminate-runner {
  position: absolute;
  inset-block: 0;
  left: 0;
  display: block;
  width: 34%;
  border-radius: inherit;
  overflow: hidden;
  background: linear-gradient(90deg, var(--ios-blue-strong), #52adff);
  box-shadow: 0 0 8px rgba(10, 132, 255, 0.25);
  animation: stage-progress-travel 1.25s cubic-bezier(0.4, 0, 0.2, 1) infinite;
  will-change: transform;
}

.stage-bar.is-indeterminate .stage-indeterminate-runner::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.72), transparent);
}

.stage-relay {
  position: absolute;
  left: 100%;
  top: 50%;
  z-index: 3;
  width: 16px;
  height: 12px;
  transform: translateY(-50%);
  pointer-events: none;
}

.stage-relay::before {
  content: "";
  position: absolute;
  left: 2px;
  right: 2px;
  top: 5px;
  height: 2px;
  border-radius: 999px;
  background: rgba(118, 118, 128, 0.18);
}

.stage-relay-baton {
  position: absolute;
  left: 2px;
  top: 3px;
  width: 6px;
  height: 6px;
  box-sizing: border-box;
  border: 2px solid var(--ios-blue);
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.1), 0 0 8px rgba(10, 132, 255, 0.38);
  opacity: 0;
}

.relay-ready::before {
  background: linear-gradient(90deg, rgba(10, 132, 255, 0.46), rgba(118, 118, 128, 0.16));
}

.relay-ready .stage-relay-baton {
  background: var(--ios-blue);
  opacity: 0.52;
  transform: scale(0.72);
}

.relay-handoff::before {
  background: linear-gradient(90deg, rgba(29, 138, 92, 0.62), rgba(10, 132, 255, 0.72));
}

.relay-handoff .stage-relay-baton {
  animation: stage-relay-pass 1.45s var(--ios-motion) infinite;
}

.relay-complete::before {
  background: rgba(29, 138, 92, 0.48);
}

.relay-bypass::before {
  background: repeating-linear-gradient(90deg, rgba(118, 118, 128, 0.28) 0 3px, transparent 3px 5px);
}

.relay-blocked::before {
  background: rgba(214, 58, 64, 0.46);
}

@keyframes stage-relay-pass {
  0%, 24% { opacity: 0; transform: translateX(0) scale(0.7); }
  36% { opacity: 1; transform: translateX(0) scale(1); }
  74% { opacity: 1; transform: translateX(8px) scale(1); }
  90%, 100% { opacity: 0; transform: translateX(8px) scale(0.7); }
}

@keyframes stage-signal-pulse {
  0% { box-shadow: 0 0 0 0 rgba(10, 132, 255, 0.32); }
  72%, 100% { box-shadow: 0 0 0 7px rgba(10, 132, 255, 0); }
}

@keyframes stage-progress-sweep {
  from { transform: translateX(-125%); }
  to { transform: translateX(225%); }
}

@keyframes stage-progress-travel {
  0% { opacity: 0; transform: translateX(-115%); }
  16% { opacity: 1; }
  84% { opacity: 1; }
  100% { opacity: 0; transform: translateX(300%); }
}

@keyframes stage-card-live {
  0%, 100% { box-shadow: inset 0 0 0 1px rgba(10, 132, 255, 0.12), 0 5px 14px rgba(10, 132, 255, 0.07); }
  50% { box-shadow: inset 0 0 0 1px rgba(10, 132, 255, 0.2), 0 8px 18px rgba(10, 132, 255, 0.13); }
}

.preview-table th,
thead th {
  background: rgba(118, 118, 128, 0.045);
}

.preview-table tbody tr:hover td,
tbody tr:hover td {
  background: rgba(10, 132, 255, 0.055);
}

tbody tr.selected td {
  background: rgba(10, 132, 255, 0.085);
}

.link-button,
.deliverable-open {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--ios-blue-strong);
  transition: background 160ms ease, transform 220ms var(--ios-motion);
}

.link-button {
  gap: 2px;
}

.deliverable-open {
  width: 32px;
  height: 32px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: rgba(10, 132, 255, 0.08);
}

.deliverable-open:hover,
.link-button:hover {
  background: rgba(10, 132, 255, 0.12);
}

.dl-file {
  border-bottom-color: rgba(60, 60, 67, 0.09);
}

.dl-icon {
  border-radius: 8px;
}

.stat-strip,
.filter-bar,
.status-bar {
  background: rgba(255, 255, 255, 0.7);
  border-color: var(--ios-border);
  backdrop-filter: blur(22px) saturate(165%);
  -webkit-backdrop-filter: blur(22px) saturate(165%);
}

.stat-strip {
  gap: 12px;
  padding: 14px 20px;
}

.stat-card {
  height: 78px;
  padding: 12px 14px;
  transition: border-color 160ms ease, background 160ms ease, transform 220ms var(--ios-motion), box-shadow 180ms ease;
}

.stat-card:hover {
  transform: translateY(-2px);
}

.stat-card.active {
  border-color: rgba(10, 132, 255, 0.22);
  background: rgba(10, 132, 255, 0.085);
  box-shadow: 0 10px 28px rgba(10, 132, 255, 0.09), inset 0 0 0 1px rgba(10, 132, 255, 0.08);
}

.filter-bar {
  gap: 9px;
  padding: 11px 20px;
}

.filter-select,
.search-input,
.comment-box,
.settings-field input,
.template-row input {
  border: 1px solid var(--ios-border);
  border-radius: 8px;
  color: var(--ios-ink);
  background: rgba(255, 255, 255, 0.68);
  box-shadow: inset 0 1px 2px rgba(31, 35, 48, 0.025);
  transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
}

.filter-select:focus,
.search-input:focus,
.comment-box:focus,
.settings-field input:focus,
.template-row input:focus {
  outline: 0;
  border-color: rgba(10, 132, 255, 0.5);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.12);
}

.workspace {
  background: transparent;
}

.table-panel,
.detail-panel {
  background: rgba(255, 255, 255, 0.66);
  backdrop-filter: blur(18px) saturate(150%);
  -webkit-backdrop-filter: blur(18px) saturate(150%);
}

.table-panel,
.panel-head,
.readonly-card,
.mini-row,
.review-box,
.metadata {
  border-color: var(--ios-border);
}

.detail-content {
  background: rgba(241, 243, 247, 0.64);
}

.readonly-card,
.mini-row,
.review-box,
.metadata,
.settings-section {
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 4px 14px rgba(31, 35, 48, 0.035);
}

.readonly-head,
.mini-head {
  background: rgba(118, 118, 128, 0.045);
}

.settings-overlay {
  background: rgba(42, 44, 52, 0.22);
  backdrop-filter: blur(18px) saturate(140%);
  -webkit-backdrop-filter: blur(18px) saturate(140%);
}

.settings-dialog {
  width: min(760px, 100%);
  border: 1px solid rgba(255, 255, 255, 0.76);
  border-radius: 12px;
  background: rgba(249, 250, 253, 0.88);
  box-shadow: 0 30px 80px rgba(24, 28, 38, 0.2), inset 0 0 0 1px rgba(60, 60, 67, 0.08);
  backdrop-filter: blur(34px) saturate(180%);
  -webkit-backdrop-filter: blur(34px) saturate(180%);
}

.settings-head,
.settings-body {
  background: transparent;
}

.settings-section,
.settings-toggle {
  border-color: var(--ios-border);
}

.settings-toggle {
  border-radius: 8px;
  background: rgba(118, 118, 128, 0.045);
  transition: border-color 160ms ease, background 160ms ease;
}

.settings-toggle:hover {
  border-color: rgba(10, 132, 255, 0.22);
  background: rgba(10, 132, 255, 0.045);
}

.settings-toggle input {
  appearance: none;
  -webkit-appearance: none;
  position: relative;
  width: 38px;
  height: 22px;
  margin: 0;
  flex: 0 0 38px;
  border: 0;
  border-radius: 999px;
  background: #c7c7cc;
  box-shadow: inset 0 0 0 1px rgba(60, 60, 67, 0.08);
  cursor: pointer;
  transition: background 180ms ease, box-shadow 180ms ease;
}

.settings-toggle input::after {
  content: "";
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 2px 5px rgba(31, 35, 48, 0.24);
  transition: transform 260ms var(--ios-motion);
}

.settings-toggle input:checked {
  background: #34c759;
  box-shadow: inset 0 0 0 1px rgba(25, 130, 55, 0.12);
}

.settings-toggle input:checked::after {
  transform: translateX(16px);
}

.settings-toggle input:focus-visible {
  outline: 3px solid rgba(10, 132, 255, 0.22);
  outline-offset: 2px;
}

.icon-button {
  border-color: var(--ios-border);
  border-radius: 50%;
  background: rgba(118, 118, 128, 0.08);
  transition: background 160ms ease, color 160ms ease, transform 220ms var(--ios-motion);
}

.icon-button:hover {
  color: var(--ios-ink);
  border-color: transparent;
  background: rgba(118, 118, 128, 0.14);
  transform: rotate(4deg) scale(1.04);
}

.global-message,
.api-message {
  border-color: rgba(10, 132, 255, 0.18);
  border-radius: 8px;
  color: var(--ios-blue-strong);
  background: rgba(236, 246, 255, 0.84);
  box-shadow: 0 8px 24px rgba(10, 132, 255, 0.08);
  backdrop-filter: blur(18px) saturate(150%);
  -webkit-backdrop-filter: blur(18px) saturate(150%);
}

.global-message-close {
  color: currentColor;
}

.status-bar {
  color: var(--ios-secondary);
  font-weight: 560;
}

.kbd-hints {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--ios-tertiary);
}

.switch-label {
  min-height: 38px;
  border: 1px solid var(--ios-border);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.62);
  padding: 0 10px;
}

.switch-label input {
  appearance: none;
  -webkit-appearance: none;
  position: relative;
  width: 34px;
  height: 20px;
  margin: 0;
  border: 0;
  border-radius: 999px;
  background: #c7c7cc;
  cursor: pointer;
  transition: background 180ms ease;
}

.switch-label input::after {
  content: "";
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 4px rgba(31, 35, 48, 0.22);
  transition: transform 240ms var(--ios-motion);
}

.switch-label input:checked { background: #34c759; }
.switch-label input:checked::after { transform: translateX(14px); }

.run-home,
.stat-strip,
.filter-bar,
.workspace,
.doc-review {
  animation: view-enter 360ms var(--ios-motion) both;
}

.spin {
  animation: spin 900ms linear infinite;
}

.sheet-enter-active,
.sheet-leave-active {
  transition: opacity 220ms ease;
}

.sheet-enter-active .settings-dialog,
.sheet-leave-active .settings-dialog {
  transition: opacity 220ms ease, transform 320ms var(--ios-motion);
}

.sheet-enter-from,
.sheet-leave-to,
.sheet-enter-from .settings-dialog,
.sheet-leave-to .settings-dialog {
  opacity: 0;
}

.sheet-enter-from .settings-dialog,
.sheet-leave-to .settings-dialog {
  transform: translateY(18px) scale(0.975);
}

@keyframes view-enter {
  from { opacity: 0; transform: translateY(7px) scale(0.997); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1120px) {
  .shell { grid-template-columns: 72px minmax(0, 1fr); }
  .side-nav { padding-inline: 9px; }
  .nav-button { min-height: 42px; }
}

@media (max-width: 980px) {
  .shell {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr) 64px;
  }

  .main {
    grid-column: 1;
    grid-row: 1;
    height: calc(100vh - 64px);
  }

  .side-nav {
    grid-column: 1;
    grid-row: 2;
    min-height: 64px;
    overflow: hidden;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    gap: 6px;
    border-right: 0;
    border-top: 1px solid var(--ios-border);
    padding: 8px 12px;
  }

  .side-brand,
  .side-user,
  .side-nav > .nav-group:nth-of-type(2),
  .nav-spacer,
  .nav-title {
    display: none;
  }

  .side-nav > .nav-group {
    flex-direction: row;
  }

  .side-nav > .nav-group:first-of-type,
  .side-nav > .nav-group:last-of-type {
    display: flex;
  }

  .nav-button {
    width: 44px;
    height: 44px;
    min-height: 44px;
    justify-content: center;
    padding: 0;
  }

  .nav-button:hover { transform: translateY(-1px); }
  .run-grid { grid-template-columns: minmax(0, 1fr); }
  .ov-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 720px) {
  .app-bar { min-height: 58px; padding: 9px 10px; }
  .page-title { font-size: 17px; }
  .doc-chip { max-width: 160px; }
  .app-actions { flex-wrap: nowrap; overflow-x: auto; }
  .button { flex: 0 0 auto; padding-inline: 9px; }
  .button-label,
  .llm-toggle > svg,
  .llm-toggle > span:last-child { display: none; }
  .llm-toggle { padding-inline: 7px; }
  .run-home { padding: 12px; }
  .stat-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 10px 12px; }
  .filter-bar { padding: 9px 12px; overflow-x: auto; flex-wrap: nowrap; }
  .filter-select { min-width: 140px; }
  .search-input { min-width: 220px; }
  .settings-overlay { padding: 10px; }
  .settings-dialog { max-height: calc(100vh - 20px); }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }

  .stage-bar.is-indeterminate .stage-indeterminate-runner {
    width: 32% !important;
    opacity: 1 !important;
    transform: none !important;
    animation: none !important;
  }
}
</style>




