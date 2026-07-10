<template>
  <n-config-provider>
    <div class="shell">
      <aside class="side-nav">
        <div class="side-brand">
          <div class="brand-mark">标</div>
          <div class="brand-text">
            <div class="brand-name">标准需求抽取与审查平台</div>
            <div class="brand-sub">Requirement Atomizer</div>
          </div>
        </div>
        <nav class="nav-group">
          <p class="nav-title">工作台</p>
          <button
            v-for="item in phaseNavItems.filter((i) => i.id !== 'settings')"
            :key="item.id"
            class="nav-button"
            :class="{ active: activeNav === item.id }"
            :data-testid="`nav-${item.label}`"
            type="button"
            @click="handleNavAction(item.id)"
          >
            <span class="nav-icon">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </button>
        </nav>
        <nav class="nav-group">
          <p class="nav-title">交付物</p>
          <button class="nav-button" type="button" data-testid="nav-实现规格" @click="openDeliverable('dlms_cosem_spec_requirements.json')">
            <span class="nav-icon">▦</span><span>实现规格</span>
          </button>
          <button class="nav-button" type="button" data-testid="nav-软件需求列表" @click="openDeliverable('软件需求列表-成文.xlsx')">
            <span class="nav-icon">▤</span><span>软件需求列表</span>
          </button>
          <button class="nav-button" type="button" data-testid="nav-澄清清单" @click="openDeliverable('clarification_questions.xlsx')">
            <span class="nav-icon">◔</span><span>澄清清单</span>
          </button>
        </nav>
        <div class="nav-spacer"></div>
        <nav class="nav-group">
          <button
            v-for="item in phaseNavItems.filter((i) => i.id === 'settings')"
            :key="item.id"
            class="nav-button"
            :class="{ active: activeNav === item.id }"
            :data-testid="`nav-${item.label}`"
            type="button"
            @click="handleNavAction(item.id)"
          >
            <span class="nav-icon">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </button>
        </nav>
        <div class="side-user">
          <div class="side-avatar">专</div>
          <div><b>需求评审专家</b><span>GUI Phase 1</span></div>
        </div>
      </aside>

      <main class="main">
        <header class="app-bar">
          <div class="page-title-area">
            <h3 class="page-title">{{ activeNavLabel }}</h3>
            <span class="doc-chip" :title="documentDisplayName">{{ documentDisplayName }}</span>
          </div>

          <div class="app-actions">
            <button class="button" type="button" data-testid="action-open-document" @click="handleOpenDocument">导入文档</button>
            <button class="button" type="button" data-testid="action-select-output-dir" @click="handleOpenOutput">选择输出目录</button>
            <label class="llm-toggle">
              <input v-model="llmMode" type="checkbox" data-testid="llm-mode-toggle" />
              <span class="llm-track" aria-hidden="true"></span>
              <span>LLM 富化</span>
            </label>
            <button class="button" type="button" data-testid="action-test-pipeline" :disabled="isRunning" @click="handleRunPipeline({ llmReviewLimit: TEST_LLM_REVIEW_LIMIT })">测试运行</button>
            <button class="button primary" type="button" data-testid="action-run-pipeline" :disabled="isRunning" @click="() => handleRunPipeline()">
              {{ isRunning ? "运行中" : "▶ 运行" }}
            </button>
            <button v-if="activeNav === 'document'" class="button" type="button" data-testid="action-export-html" @click="handleExportAnnotationHtml">导出批注HTML</button>
            <button v-if="activeNav === 'document'" class="button" type="button" data-testid="action-import-decisions" @click="handleImportDecisions">导入裁决</button>
            <button v-if="activeNav === 'document'" class="button" type="button" data-testid="action-import-answers" @click="handleImportAnswers">导入澄清答复</button>
          </div>
        </header>

        <!-- 统一消息 testid:与审查页 api-message 互斥渲染,任意页面都能拿到运行反馈 -->
        <div v-if="apiMessage && activeNav !== 'review'" class="global-message" data-testid="api-message"
             role="status" @click="apiMessage = ''">{{ apiMessage }}<span class="global-message-close">✕</span></div>

        <section v-if="activeNav === 'run'" class="run-home" data-testid="run-paths-panel">
          <div class="ov-stats">
            <div class="ov-stat">
              <div class="k">原子需求</div>
              <div class="v">{{ runOverview.atoms != null ? runOverview.atoms.toLocaleString("zh-CN") : "—" }}</div>
              <div class="d flat">结构化字段确定性抽取</div>
            </div>
            <div class="ov-stat">
              <div class="k">AI 行为需求</div>
              <div class="v">{{ runOverview.aiReqs != null ? runOverview.aiReqs : "—" }}</div>
              <div class="d up">{{ runOverview.selfCheck != null ? `↑ ${runOverview.selfCheck} 条来自自检补充` : "含自检收敛补充" }}</div>
            </div>
            <div class="ov-stat">
              <div class="k">章节覆盖率</div>
              <div class="v">{{ runOverview.coverage != null ? `${runOverview.coverage.toFixed(1)}%` : "—" }}</div>
              <div class="d up">{{ runOverview.chapters || "跑完整链后统计" }}</div>
            </div>
            <div class="ov-stat">
              <div class="k">必答澄清</div>
              <div class="v">{{ runOverview.questions != null ? runOverview.questions : "—" }}</div>
              <div class="d" :class="runOverview.verdict === 'READY' ? 'up' : 'warn'">
                {{ runOverview.verdict ? `就绪判定:${runOverview.verdict}` : "评审会前必答清单" }}</div>
            </div>
          </div>

          <div class="flow-card">
            <div class="board-head">
              <h4>交付物流水线</h4>
              <span>run_manifest 台账 · 中断可续跑
                <em class="path-hint" data-testid="selected-input-path">{{ currentInputPath || "尚未选择文档" }}</em>
              </span>
            </div>
            <div class="run-meter" data-testid="run-progress">
              <div class="run-meter-head">
                <span>{{ runStage }}</span>
                <strong>{{ runProgress }}%</strong>
              </div>
              <div class="run-meter-detail" data-testid="run-progress-detail">{{ runProgressDetail }}</div>
              <div class="run-meter-track">
                <div class="run-meter-fill" :style="{ width: `${runProgress}%` }"></div>
              </div>
            </div>
            <div class="run-stage-board" data-testid="run-stage-board">
              <div
                v-for="card in runStageCards"
                :key="card.key"
                class="run-stage-card"
                :class="`stage-${card.status}`"
                :data-testid="`run-stage-${card.key}`"
              >
                <span class="stage-name">{{ card.label }}</span>
                <strong class="stage-status">{{ card.statusText }}</strong>
                <small class="stage-detail">{{ card.detail }}</small>
                <span class="stage-bar"><i :style="{ width: `${card.status === 'ok' || card.status === 'skipped' ? 100 : card.percent}%` }"></i></span>
              </div>
            </div>
          </div>

          <div class="run-grid">
            <div class="panel-card">
              <div class="board-head">
                <h4>需求审查 · 待裁决</h4>
                <button class="link-button" type="button" @click="handleNavAction('review')">进入工作台 →</button>
              </div>
              <div class="preview-wrap">
                <table class="preview-table">
                  <thead><tr><th>编号</th><th>需求</th><th>模块</th><th>置信度</th><th>状态</th></tr></thead>
                  <tbody>
                    <tr v-for="row in reviewPreviewRows" :key="row.id" @click="handleNavAction('review')">
                      <td class="rid">{{ row.id }}</td>
                      <td class="req-cell">{{ row.chineseText }}</td>
                      <td><span class="pchip plain">{{ row.module || "未分模块" }}</span></td>
                      <td class="num">{{ row.confidence.toFixed(2) }}</td>
                      <td><span class="pchip" :class="`st-${row.status}`">{{ statusOptionLabel(row.status) }}</span></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div class="panel-card">
              <div class="board-head">
                <h4>最新交付物</h4>
                <span class="path-hint" data-testid="selected-output-dir">{{ currentOutputDir || "尚未选择输出目录" }}</span>
              </div>
              <div class="dl-files" data-testid="deliverable-html">
                <div v-for="f in DELIVERABLE_FILES" :key="f.key" class="dl-file">
                  <span class="dl-icon" :class="f.tone">{{ f.icon }}</span>
                  <span class="dl-name"><strong>{{ f.name }}</strong><small>{{ f.hint }}</small></span>
                  <button class="deliverable-open" type="button" @click="openDeliverable(f.name)">打开</button>
                </div>
              </div>
              <div v-if="lastStageNotes.length" class="note-warn">
                <b>注意</b>
                <span>{{ lastStageNotes.join("；") }}</span>
              </div>
            </div>
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

            <div class="table-wrap independent-table-scroll" data-testid="requirement-table">
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
                  <tr
                    v-for="row in filteredRequirements"
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
                    :disabled="isTranslating || selectedRequirement.id === emptyRequirement.id"
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
                <button class="button" type="button" :disabled="isSubmitting" data-testid="decision-accepted" @click="updateStatus('accepted')">接受</button>
                <button class="button" type="button" :disabled="isSubmitting" data-testid="decision-rejected" @click="updateStatus('rejected')">拒绝</button>
                <button class="button" type="button" :disabled="isSubmitting" @click="updateStatus('needs_discussion')">讨论</button>
                <button class="button" type="button" :disabled="isSubmitting" @click="updateStatus('expert_pending')">专家</button>
              </div>
              <textarea v-model="reviewComment" class="comment-box" placeholder="请输入审查意见" />
              <div v-if="apiMessage" class="api-message" data-testid="api-message">{{ apiMessage }}</div>
            </div>
          </aside>
        </section>
        </template>
        <DocumentReview v-else :client="apiClient" :active="activeNav === 'document'" />

        <footer class="status-bar">
          <span>输出目录：{{ currentOutputDir || "尚未选择输出目录" }}</span>
          <span class="kbd-hints">快捷键：A 接受 · R 拒绝 · D 讨论 · P 固定</span>
        </footer>
      </main>

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
            <button class="icon-button" type="button" data-testid="settings-close" aria-label="关闭设置" @click="closeSettingsPanel">×</button>
          </header>

          <div class="settings-body">
            <section class="settings-section">
              <div class="settings-section-title">运行阶段（点「运行」后按依赖顺序依次执行）</div>
              <label class="settings-toggle">
                <input v-model="runStages.llmReview" type="checkbox" data-testid="stage-llm-review" />
                <span><strong>LLM 审查（规则候选复核）</strong><small>逐条复核规则切出的原子候选。DLMS profile 类文档（对象表密集）建议开；散文类标准可关——交付物主要来自 AI 抽取轨，可省大量审查调用。</small></span>
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
                <input v-model="runStages.analyze" type="checkbox" data-testid="stage-analyze" />
                <span><strong>软件需求分析</strong><small>软/硬/协同归属 + software_requirements.xlsx。<em>依赖 AI 抽取</em>。</small></span>
              </label>
              <label class="settings-toggle">
                <input v-model="runStages.compose" type="checkbox" data-testid="stage-compose" />
                <span><strong>组装工程需求</strong><small>原子需求重组为需求功能 + DLMS 对象两段。</small></span>
              </label>
              <label class="settings-toggle">
                <input v-model="runStages.annotationHtml" type="checkbox" data-testid="stage-annotation-html" />
                <span><strong>导出批注 HTML</strong><small>生成 document_annotation.html，用于专家离线阅读、批注和导出裁决 JSON。</small></span>
              </label>
              <div class="template-row">
                <span class="field-label">需求列表模板（xlsx，选填）</span>
                <input :value="templatePath" readonly placeholder="未设置——设置后分析结果按公司模板格式成文" data-testid="template-path" />
                <button class="button" type="button" data-testid="template-pick" @click="handleSelectTemplate">选择</button>
                <button class="button" type="button" :disabled="!templatePath" @click="templatePath = ''">清除</button>
              </div>
              <p class="settings-hint">LLM 富化跟随上方「LLM 富化」开关：开→AI 抽取/装配/分析走 openai_compatible，关→纯确定性。</p>
            </section>
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
                  {{ isSavingSettings ? "保存中" : "保存配置" }}
                </button>
                <button class="button" type="button" data-testid="settings-test" :disabled="isTestingSettings" @click="handleTestLlmConnection">
                  {{ isTestingSettings ? "测试中" : "测试连接" }}
                </button>
                <button class="button" type="button" data-testid="settings-open-logs" @click="handleOpenLogs">打开日志目录</button>
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
    </div>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import { NConfigProvider } from "naive-ui"
import { RequirementApiClient } from "./api-client"
import DocumentReview from "./DocumentReview.vue"
import { requirements as mockRequirements } from "./mock-data"
import { applyReviewState, mapBackendRequirement, statusDisplay as displayStatus } from "./requirement-mapper"
import type { Requirement, ReviewStatus } from "./types"

type PhaseNavId = "run" | "review" | "document" | "settings"
type StatFilter = "all" | "accepted" | "expert_pending" | "ambiguous"
type LlmSettings = {
  enabled: boolean
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

const phaseNavItems: Array<{ id: PhaseNavId; label: string; icon: string }> = [
  { id: "run", label: "运行", icon: "▶" },
  { id: "review", label: "审查工作台", icon: "▣" },
  { id: "document", label: "文档批注", icon: "▤" },
  { id: "settings", label: "设置", icon: "⚙" },
]

const activeNav = ref<PhaseNavId>("run")
// 运行页总览（样机 2026-07-09）：跑完链后填充,未知显示 —
const runOverview = ref<{ atoms: number | null; aiReqs: number | null; selfCheck: number | null;
  coverage: number | null; chapters: string; questions: number | null; verdict: string }>({
  atoms: null, aiReqs: null, selfCheck: null, coverage: null, chapters: "", questions: null, verdict: "",
})
const lastStageNotes = ref<string[]>([])
const reviewPreviewRows = computed(() => requirementRows.value.slice(0, 4))
const DELIVERABLE_FILES = [
  { key: "software", icon: "XLS", tone: "xls", name: "软件需求列表-成文.xlsx", hint: "V2.3.x 模板成文（B 轨主交付物）" },
  { key: "annotation", icon: "HTM", tone: "htm", name: "document_annotation.html", hint: "批注视图 · 分享给专家离线裁决" },
  { key: "clarification", icon: "XLS", tone: "xls", name: "clarification_questions.xlsx", hint: "必答澄清 · 问客户/内部核对" },
  { key: "manifest", icon: "JSN", tone: "jsn", name: "run_manifest.json", hint: "阶段台账 · 路由与续跑依据" },
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
const apiMessage = ref("")
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
  baseUrl: "http://127.0.0.1:11434/v1",
  model: "qwen2.5:14b",
  apiKeyEnv: "RATOMIZER_LLM_API_KEY",
  temperature: 0,
  maxTokens: 4096,
  timeoutS: 60,
  maxRetries: 3,
  concurrency: 4,
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
// v2（2026-07-08 审计 A1）：整对象持久化 + 旧值优先展开意味着默认值演进永远到不了老用户
// （旧 localStorage 里冻结着 compose:false）。换键 = 所有用户一次性拿到新默认，代价是旧自定义重置。
const RUN_STAGES_KEY = "ratomizer.runStages.v2"
function loadRunStages(): RunStages {
  const fallback: RunStages = {
    llmReview: true,
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
const RUN_STAGE_DEFS = [
  { key: "atomize", label: "原子化" },
  { key: "llm-review", label: "LLM审核" },
  { key: "ai-extract", label: "AI抽取" },
  { key: "functional-synthesis", label: "功能重组" },
  { key: "assemble", label: "组装功能" },
  { key: "requirements-analysis", label: "需求分析" },
  { key: "template-write", label: "格式成文" },
  { key: "clarification-report", label: "澄清清单" },
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

const runStageStates = ref<Record<RunStageKey, RunStageState>>(defaultStageStates())
const runStageCards = computed(() => RUN_STAGE_DEFS.map((item) => {
  const state = runStageStates.value[item.key]
  return {
    ...item,
    ...state,
    statusText: stageStatusText(state),
  }
}))

function stageStatusText(state: RunStageState) {
  if (state.status === "ok") return "已完成"
  if (state.status === "skipped") return "已完成，已跳过"
  if (state.status === "running") return `运行中，进度${Math.round(state.percent)}%`
  if (state.status === "failed") return "失败"
  if (state.status === "disabled") return "未启用"
  return "待完成"
}

function setRunStageState(key: string | undefined, patch: Partial<RunStageState>) {
  if (!key || !(key in runStageStates.value)) return
  const stageKey = key as RunStageKey
  runStageStates.value = {
    ...runStageStates.value,
    [stageKey]: {
      ...runStageStates.value[stageKey],
      ...patch,
    },
  }
}

function resetRunStageBoard() {
  const next = defaultStageStates()
  if (!runStages.value.llmReview) next["llm-review"] = { status: "disabled", percent: 0, detail: "未启用" }
  if (!runStages.value.aiExtract) {
    next["ai-extract"] = { status: "disabled", percent: 0, detail: "未启用" }
    next["functional-synthesis"] = { status: "disabled", percent: 0, detail: "依赖 AI 抽取" }
  }
  if (!runStages.value.assemble) next.assemble = { status: "disabled", percent: 0, detail: "未启用" }
  if (!runStages.value.analyze) {
    next["requirements-analysis"] = { status: "disabled", percent: 0, detail: "未启用" }
    next["template-write"] = { status: "disabled", percent: 0, detail: "未启用" }
    next["clarification-report"] = { status: "disabled", percent: 0, detail: "未启用" }
  }
  if (!templatePath.value) next["template-write"] = { status: "disabled", percent: 0, detail: "未配置模板" }
  if (!runStages.value.compose) next.compose = { status: "disabled", percent: 0, detail: "未启用" }
  if (!runStages.value.annotationHtml) next["export-annotation-html"] = { status: "disabled", percent: 0, detail: "未启用" }
  runStageStates.value = next
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
    } else if (status === "running") {
      setRunStageState(item.key, { status: "running", percent: 0, detail: "上次中断在此阶段" })
    } else if (status === "failed") {
      setRunStageState(item.key, { status: "failed", percent: 0, detail: String(entry.error || "上次执行失败") })
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

const selectedRequirement = computed(() => requirementRows.value.find((item) => item.id === selectedRequirementId.value) ?? requirementRows.value[0] ?? emptyRequirement)
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
  return `显示第 1-${total} 条，共 ${total} 条`
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
  loadInitialApiSession()
  // 恢复已保存的 LLM 开关/端点：此前只在打开设置面板时才加载——重启后 llmMode 恒 false，
  // 整条 AI 交付物轨静默降级 stub（2026-07-08 审计 A2）
  void loadLlmSettings()
})

function handleNavAction(item: PhaseNavId) {
  activeNav.value = item
  if (item === "settings") {
    showSettingsPanel.value = true
    void loadLlmSettings()
  }
}

function closeSettingsPanel() {
  showSettingsPanel.value = false
  if (activeNav.value === "settings") {
    activeNav.value = "review"
  }
}

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
    const payload = await window.ratomizerDesktop?.testLlmConnection?.(buildLlmSettingsPayload(false))
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

async function updateStatus(status: ReviewStatus) {
  if (isSubmitting.value) return
  const row = requirementRows.value.find((item) => item.id === selectedRequirementId.value)
  if (!row) return
  apiMessage.value = ""
  if (!apiClient.value) {
    row.status = status
    return
  }
  isSubmitting.value = true
  try {
    const state = await apiClient.value.applyReviewAction({
      requirementId: row.backendId,
      status,
      actor: "vue3-ui",
      reason: reviewComment.value.trim() || `set ${status} from Vue3 UI`,
    })
    const index = requirementRows.value.findIndex((item) => item.id === row.id)
    if (index >= 0) {
      requirementRows.value[index] = applyReviewState(row, state)
    }
    reviewComment.value = ""
  } catch (error) {
    apiMessage.value = error instanceof Error ? error.message : "审查状态写入失败"
  } finally {
    isSubmitting.value = false
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
    apiMessage.value = `已选择文档：${path}`
    runStage.value = "待运行"
    runProgress.value = 0
  }
}

async function handleOpenOutput() {
  if (window.ratomizerDesktop?.selectOutputDir) {
    const path = await window.ratomizerDesktop.selectOutputDir()
    if (path) {
      currentOutputDir.value = path
      apiMessage.value = `已选择输出目录：${path}`
      runStage.value = "待运行"
      const payload = await window.ratomizerDesktop.getOutputSummary?.({ outDir: path })
      latestTaskSummary.value = objectValue(payload?.summary)
      applyRunManifestSummary(latestTaskSummary.value)
    }
    return
  }
  const session = await window.ratomizerDesktop?.openOutput?.()
  if (session && typeof session === "object" && "baseUrl" in session) {
    await loadFromSession(session)
  }
}

async function handleRunPipeline(options: { llmReviewLimit?: number } = {}) {
  if (isRunning.value) return
  let stopProgress: (() => void) | undefined
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
    resetRunStageBoard()
    runProgress.value = 8
    runStage.value = "准备运行"
    runProgressDetail.value = options.llmReviewLimit ? `测试运行：最多 AI 审查 ${options.llmReviewLimit} 条` : "准备启动本地任务"
    apiMessage.value = options.llmReviewLimit ? `正在测试运行，最多 AI 审查 ${options.llmReviewLimit} 条...` : "正在运行抽取与审查..."
    await nextUiTick()
    runProgress.value = 18
    runStage.value = "运行后端解析"
    runProgressDetail.value = "正在抽取原子化需求"
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
    if (summaryCounts?.atomic_requirements != null) {
      runOverview.value = { ...runOverview.value, atoms: Number(summaryCounts.atomic_requirements) }
    }
    const finalOutDir = String(payload.out_dir || payload.outDir || outDir)
    currentOutputDir.value = finalOutDir
    let apiReconnectWarning = formatApiReconnectWarning(finalOutDir, stringOr(payload.api_warning, ""))
    apiReconnectWarning ||= await refreshAfterDesktopTask(finalOutDir)

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
          skippedForLlm.push("需求分析", "按模板成文", "澄清清单")
        }
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
        lastStageNotes.value = chainNotes
        // 运行页总览瓦片（样机）：从链载荷提取,缺项保持 —
        const q = objectValue(chainPayload?.quality) as Record<string, unknown> | null
        runOverview.value = {
          atoms: runOverview.value.atoms,
          aiReqs: chainPayload?.count != null ? Number(chainPayload.count) : runOverview.value.aiReqs,
          selfCheck: q?.self_check_added != null ? Number(q.self_check_added) : runOverview.value.selfCheck,
          coverage: q?.coverage_pct != null ? Number(q.coverage_pct) : runOverview.value.coverage,
          chapters: q?.sections_total != null ? `${q.sections_total} 章 · 失败 ${q.failed_sections ?? 0}` : runOverview.value.chapters,
          questions: chainPayload?.questions != null ? Number(chainPayload.questions) : runOverview.value.questions,
          verdict: chainReadiness?.verdict || runOverview.value.verdict,
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
        const a = objectValue(sample.analysis) as { analysis_count?: number; enriched?: number } | null
        if (a) sampleNote += `；软件需求 ${Number(a.analysis_count ?? 0)} 条（富化 ${Number(a.enriched ?? 0)}）→ software_requirements.xlsx`
        const w = objectValue(sample.template) as { appended_total?: number } | null
        if (w) sampleNote += `；成文 ${Number(w.appended_total ?? 0)} 行 → 软件需求列表-成文.xlsx`
        const r = objectValue(sample.readiness) as { verdict?: string } | null
        if (r?.verdict) sampleNote += `；就绪判定 ${r.verdict}，必答澄清 ${Number(sample.questions ?? 0)} 条`
        apiReconnectWarning ||= await refreshAfterDesktopTask(finalOutDir)
      } catch (sampleError) {
        sampleNote = `；样本链失败：${sampleError instanceof Error ? sampleError.message : sampleError}`
      }
    }

    runProgress.value = 100
    runStage.value = "运行完成"
    if (options.llmReviewLimit) {
      runProgressDetail.value = `测试运行完成：最多 AI 审查 ${options.llmReviewLimit} 条${sampleNote}`
      apiMessage.value = `测试运行完成${sampleNote}`
    } else {
      const tail = ranStages.length ? `，随后 ${ranStages.join(" → ")}` : ""
      // 一致性闭环：跨章重复/OBIS 待核/覆盖缺口直接进跑完消息（详情看批注视图标记）
      const dup = Number(consistency?.duplicate_groups || 0)
      const differ = Number(consistency?.obis_values_differ || 0)
      const uncovered = Number(consistency?.uncovered_requirement_like || 0)
      const warn = dup || differ || uncovered
        ? `；一致性：疑似跨章重复 ${dup} 组、OBIS 数值待核 ${differ}、覆盖缺口 ${uncovered}（批注视图已标记）`
        : ""
      const apiWarn = apiReconnectWarning
        ? `；${apiReconnectWarning}`
        : ""
      runProgressDetail.value = `全部阶段完成：抽取与审查${tail}`
      apiMessage.value = `运行完成：抽取与审查${tail}${warn}${readinessNote}${apiWarn}`
    }
  } catch (error) {
    runStage.value = "运行失败"
    runProgressDetail.value = "请查看错误信息"
    apiMessage.value = error instanceof Error ? error.message : "抽取与审查失败"
  } finally {
    stopProgress?.()
    isRunning.value = false
  }
}

const CHAIN_STEP_LABELS: Record<string, string> = {
  "ai-extract": "AI 抽取（双引擎）", assemble: "装配实现规格", "requirements-analysis": "软件需求分析",
  "template-write": "成文需求列表", "clarification-report": "澄清问题清单", compose: "组装工程需求",
  "export-annotation-html": "导出批注视图",
}

function handleTaskProgress(event: { stage: string; step?: string; status?: string; completed?: number; total?: number; percent?: number; model?: string }) {
  const completed = Math.max(0, Number(event.completed || 0))
  const total = Math.max(0, Number(event.total || 0))
  const percent = Number.isFinite(Number(event.percent)) ? Math.max(0, Math.min(100, Number(event.percent))) : 0
  if (event.stage === "pipeline_stage") {
    const status = event.status === "skipped" ? "skipped" : event.status === "ok" ? "ok" : "running"
    setRunStageState(event.step, { status, percent, detail: status === "skipped" ? "复用已有产物" : "基础解析产物" })
    return
  }
  if (event.stage === "chain") {
    const label = CHAIN_STEP_LABELS[String(event.step || "")] || String(event.step || "交付物链")
    const status = event.status === "skipped" ? "skipped" : completed >= total && total > 0 ? "ok" : "running"
    setRunStageState(event.step, { status, percent, detail: status === "skipped" ? "复用已有产物" : label })
    runStage.value = total ? `交付物链 ${Math.min(completed + 1, total)}/${total}：${label}` : label
    runProgressDetail.value = `正在执行：${label}…`
    return   // 总进度条由链内细粒度事件（ai_extract/analyze）驱动，这里不回跳
  }
  if (event.stage === "ai_extract") {
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
    const payload = await window.ratomizerDesktop.exportAnnotationHtml({ outDir: currentOutputDir.value })
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
    apiMessage.value = `已导入澄清答复 ${Number(payload.imported ?? 0)} 条——重跑「软件需求分析」后答复将作为权威输入生效`
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
  const session = await window.ratomizerDesktop?.getApiSession?.()
  if (session) {
    await loadFromSession(session)
  }
}

async function loadFromSession(session: { baseUrl: string; token: string; outputDir?: string }) {
  apiMessage.value = session.outputDir ? `已连接输出目录：${session.outputDir}` : ""
  currentOutputDir.value = session.outputDir || currentOutputDir.value
  const client = new RequirementApiClient({ baseUrl: session.baseUrl, token: session.token })
  apiClient.value = client
  try {
    const rows = (await client.loadRequirements()).map(mapBackendRequirement)
    requirementRows.value = rows
    selectedRequirementId.value = rows[0]?.id ?? ""
  } catch (error) {
    apiMessage.value = error instanceof Error ? error.message : "需求加载失败"
    throw error
  }
}

async function refreshAfterDesktopTask(outDir: string): Promise<string> {
  try {
    const session = await window.ratomizerDesktop?.startApiSession?.(outDir)
    if (session) {
      await loadFromSession(session)
    }
    return ""
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    return formatApiReconnectWarning(outDir, message)
  }
}

function formatApiReconnectWarning(outDir: string, reason: string) {
  const text = reason.trim()
  if (!text) return ""
  if (text.includes("输出目录") || text.includes("成果已保留")) {
    return text
  }
  return `结果已生成在输出目录：${outDir}；但本地 API 暂时未连接（${text}）。无需重跑 AI，稍后重新选择该输出目录即可继续查看/批注`
}

function defaultOutputDir(inputPath: string) {
  const stem = inputPath.split(/[\\/]/).pop()?.replace(/\.[^.]+$/, "") || "run"
  return `E:\\Codex\\requirement-atomizer-runs\\${stem}`
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
@media (max-width: 1480px) {
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
  display: grid;
  grid-template-rows: 78px auto 118px 72px minmax(0, 1fr) 32px;
  overflow: hidden;
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
  letter-spacing: -0.01em;
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
  letter-spacing: -0.02em;
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
  align-items: start;
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
.preview-table .rid { font-family: Consolas, monospace; font-size: 12px; color: #5c6675; white-space: nowrap; }
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
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 2px;
}

.run-stage-board .run-stage-card {
  flex: 1 0 118px;
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
  height: 74px;
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
  font-size: 13px;
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
  letter-spacing: -0.02em;
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
  background: #eef2ff; border: 1px solid #c7d3fc; border-radius: 8px; font-size: 13px; color: #1e41c9;
  cursor: pointer; white-space: pre-wrap; word-break: break-all; }
.global-message-close { margin-left: auto; color: #aebdfb; font-size: 12px; }

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
</style>




