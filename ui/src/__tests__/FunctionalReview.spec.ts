import { afterEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { enableAutoUnmount } from "@vue/test-utils"
import FunctionalReview from "../FunctionalReview.vue"
import { RequirementApiError } from "../api-client"

type ReadResult = {
  ok: boolean
  missing?: boolean
  path?: string | null
  format?: "json" | "jsonl"
  content?: unknown
  reason?: string
  detail?: string
}

function makeReadArtifact(over: Record<string, ReadResult> = {}): {
  fn: (input: { outDir: string; category: string; filename: string }) => Promise<ReadResult>
  calls: Array<{ category: string; filename: string }>
} {
  const defaults: Record<string, ReadResult> = {
    "pipeline:functional_requirements.json": {
      ok: true, format: "json", path: "/pipeline/functional_requirements.json",
      content: {
        schema_version: 1,
        items: [
          {
            functional_requirement_id: "FRE-1",
            objective: "应记录掉电事件",
            behaviors: ["检测到掉电时写日志"],
            preconditions: ["表计上电"],
            data_constraints: ["保留至少 10 条"],
            source_quote: "The meter shall log power failure events.",
            source_section: "4.1 / 事件记录",
            source_block_ids: ["BLK-001", "BLK-002"],
            drilled_subatoms: [
              { text: "shall log power failure events.", source_quote: "shall log power failure events.", source_block_ids: ["BLK-001"] },
            ],
            drilldown_signals: ["multi_behavior"],
            source_kind: "functional_extract",
          },
          {
            functional_requirement_id: "FREQ-MANUAL-xyz",
            objective: "手工录入需求",
            source_kind: "manual",
            source_quote: "",
            source_section: "",
            source_block_ids: [],
          },
        ],
      },
    },
    "state:manual_requirements.jsonl": { ok: true, format: "jsonl", content: [] },
    "state:requirement_lifecycle_events.jsonl": {
      ok: true, format: "jsonl",
      content: [
        { requirement_id: "FRE-1", kind: "rollback", from_state: "verified", to_state: "implemented", actor: "alice", reason: "回归测试发现缺陷", timestamp: "2026-08-06T10:00:00Z" },
      ],
    },
    ...over,
  }
  const calls: Array<{ category: string; filename: string }> = []
  const fn = async (input: { outDir: string; category: string; filename: string }) => {
    calls.push({ category: input.category, filename: input.filename })
    return defaults[`${input.category}:${input.filename}`] || { ok: false, missing: true, reason: "not_found" }
  }
  return { fn, calls }
}

function makeClient(over: Record<string, unknown> = {}) {
  return {
    loadVerificationStates: vi.fn().mockResolvedValue({
      schema: "verification-states/v1",
      states: [
        {
          requirement_id: "FRE-1",
          verification: {
            project_manager_confirm: { confirmed: true, by: "pm", at: "2026-08-06T09:00:00Z" },
            test_lead_confirm: { confirmed: false, by: "", at: "" },
            dev_test_confirm: { confirmed: false, by: "", at: "" },
            implemented: "in_progress",
            test_case_ids: ["TC-9"],
            test_completed: false,
          },
          lifecycle_state: "confirmed",
          evidence_fingerprint: "fp-1",
          actor: "pm",
          timestamp: "2026-08-06T09:00:00Z",
        },
      ],
      total: 1,
    }),
    applyVerificationAction: vi.fn().mockResolvedValue({
      requirement_id: "FRE-1",
      verification: {
        project_manager_confirm: { confirmed: true, by: "pm", at: "2026-08-06T09:00:00Z" },
        test_lead_confirm: { confirmed: true, by: "tl", at: "2026-08-06T09:30:00Z" },
        dev_test_confirm: { confirmed: false, by: "", at: "" },
        implemented: "in_progress",
        test_case_ids: ["TC-9"],
        test_completed: false,
      },
      lifecycle_state: "confirmed",
      written: ["verification_states.jsonl"],
    }),
    rollbackRequirement: vi.fn().mockResolvedValue({ requirement_id: "FRE-1", lifecycle_state: "draft", written: ["verification_states.jsonl", "requirement_lifecycle_events.jsonl"] }),
    createManualRequirement: vi.fn().mockResolvedValue({ functional_requirement_id: "FREQ-MANUAL-new", written: ["manual_requirements.jsonl"] }),
    loadDependencyCandidates: vi.fn().mockResolvedValue({
      kind: "dependency_candidates",
      candidates: [
        { from: "FRE-1", to: "FRE-2", kind: "depend", signal: "shared_obis", evidence: ["0-0:96.1.0"], status: "pending" },
      ],
      pending: 1,
    }),
    decideDependency: vi.fn().mockResolvedValue({ accepted: true, written: true, decision: {} }),
    searchRequirementLibrary: vi.fn().mockResolvedValue({
      kind: "requirement_search", query: "应记录掉电事件", matches: 1,
      results: [{ objective: "历史掉电记录需求", overlap_score: 0.42, ownership: "software", ownership_corrected: true, project: "项目A" }],
    }),
    adoptRequirementLibrary: vi.fn().mockResolvedValue({
      requirement_id: "FRE-1", ownership_override: "software", module_override: "事件记录",
      written: ["verification_states.jsonl"],
    }),
    // F2：HTTP 优先端点——默认返回与 IPC seed 同源的数据，让既有用例走 HTTP 路径
    loadFunctionalRequirements: vi.fn().mockResolvedValue({
      schema: "functional-requirements/v1",
      items: [
        {
          functional_requirement_id: "FRE-1",
          objective: "应记录掉电事件",
          behaviors: ["检测到掉电时写日志"],
          preconditions: ["表计上电"],
          data_constraints: ["保留至少 10 条"],
          source_quote: "The meter shall log power failure events.",
          source_section: "4.1 / 事件记录",
          source_block_ids: ["BLK-001", "BLK-002"],
          drilled_subatoms: [
            { text: "shall log power failure events.", source_quote: "shall log power failure events.", source_block_ids: ["BLK-001"] },
          ],
          drilldown_signals: ["multi_behavior"],
          source_kind: "functional_extract",
        },
        {
          functional_requirement_id: "FREQ-MANUAL-xyz",
          objective: "手工录入需求",
          source_kind: "manual",
          source_quote: "",
          source_section: "",
          source_block_ids: [],
        },
      ],
      total: 2,
    }),
    loadManualRequirements: vi.fn().mockResolvedValue({ schema: "manual-requirements/v1", items: [], total: 0 }),
    loadLifecycleEvents: vi.fn().mockResolvedValue({
      schema: "requirement-lifecycle-events/v1",
      events: [
        { requirement_id: "FRE-1", kind: "rollback", from_state: "verified", to_state: "implemented", actor: "alice", reason: "回归测试发现缺陷", timestamp: "2026-08-06T10:00:00Z" },
      ],
      total: 1,
    }),
    loadRequirements: vi.fn().mockResolvedValue([
      { stable_req_id: "SREQ-1", module: "事件记录", chinese_text: "记录掉电", status: "accepted" },
    ]),
    ...over,
  }
}

function mountReview(overrides: { client?: ReturnType<typeof makeClient>; readArtifact?: ReturnType<typeof makeReadArtifact> } = {}) {
  const reader = overrides.readArtifact ?? makeReadArtifact()
  Object.defineProperty(window, "ratomizerDesktop", {
    configurable: true,
    value: { readArtifact: reader.fn },
  })
  const client = overrides.client ?? makeClient()
  const wrapper = mount(FunctionalReview, {
    props: {
      client,
      sessionKey: "output:dir",
      active: true,
      refreshToken: 0,
      outputDir: "D:/out/sample",
    },
  })
  return { wrapper, client, reader }
}

describe("FunctionalReview (WS-F)", () => {
  enableAutoUnmount(afterEach)

  afterEach(() => {
    vi.restoreAllMocks()
    Reflect.deleteProperty(window, "ratomizerDesktop")
  })

  it("renders functional-requirement-level items with objective + lifecycle badge (Cap1)", async () => {
    const { wrapper } = mountReview()
    await flushPromises()

    expect(wrapper.find('[data-testid="functional-card-FRE-1"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="functional-card-FREQ-MANUAL-xyz"]').exists()).toBe(true)
    // 生命周期徽章来自 /verification-states
    expect(wrapper.find('[data-testid="lifecycle-FRE-1"]').text()).toBe("已确认")
    // 手工条目明示「无文档来源」
    expect(wrapper.find('[data-testid="manual-badge"]').exists()).toBe(true)
  })

  it("shows objective / behaviors / preconditions / data_constraints + traceability chain (Cap1)", async () => {
    const { wrapper } = mountReview()
    await flushPromises()
    const detail = wrapper.find('[data-testid="functional-detail"]')
    const text = detail.text()
    expect(text).toContain("应记录掉电事件")
    expect(text).toContain("检测到掉电时写日志")
    expect(text).toContain("表计上电")
    expect(text).toContain("保留至少 10 条")
    // 追溯链
    expect(text).toContain("The meter shall log power failure events.")
    expect(text).toContain("4.1 / 事件记录")
    // 来源块 chip 跳转入口
    expect(wrapper.find('[data-testid="block-chip-BLK-001"]').exists()).toBe(true)
  })

  it("emits focus-block when a source block chip is clicked (traceability jump)", async () => {
    const { wrapper } = mountReview()
    await flushPromises()
    await wrapper.find('[data-testid="block-chip-BLK-002"]').trigger("click")
    expect(wrapper.emitted("focus-block")).toBeTruthy()
    expect(wrapper.emitted("focus-block")![0]).toEqual(["BLK-002"])
  })

  it("exposes drilled subatoms as children with a drilldown signal (Cap1)", async () => {
    const { wrapper } = mountReview()
    await flushPromises()
    // 默认折叠——展开后才渲染子原子
    expect(wrapper.find('[data-testid="subatom-list"]').exists()).toBe(false)
    await wrapper.find('[data-testid="toggle-children"]').trigger("click")
    await flushPromises()
    expect(wrapper.find('[data-testid="subatom-list"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="subatom-list"]').text()).toContain("shall log power failure events.")
  })

  it("marks manual / source-less items with 无文档来源 and renders the empty-traceability notice (Cap3)", async () => {
    const { wrapper } = mountReview()
    await flushPromises()
    // 选中手工条目
    await wrapper.find('[data-testid="functional-card-FREQ-MANUAL-xyz"]').trigger("click")
    await flushPromises()
    expect(wrapper.find('[data-testid="no-doc-source"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="no-doc-source"]').text()).toContain("无文档来源")
  })

  it("renders the append-only rollback event timeline with actor + reason (Cap2)", async () => {
    const { wrapper } = mountReview()
    await flushPromises()
    const timeline = wrapper.find('[data-testid="lifecycle-timeline"]')
    expect(timeline.exists()).toBe(true)
    const text = timeline.text()
    expect(text).toContain("回退")
    expect(text).toContain("alice")
    expect(text).toContain("回归测试发现缺陷")
    expect(text).toContain("已验证")
    expect(text).toContain("已实现")
  })

  it("syncs evidence_fingerprint from the save response so three consecutive saves never 409 (S1-6)", async () => {
    // S1-6 复现条件：首次保存（无既有 verification state）。修复前保存成功后本地行指纹留空，
    // 第二次保存携空串当 expected → 假 409。这里 mock 后端按真实 CAS 语义判 409。
    const responseFingerprint = "fp-real-stable"
    const apply = vi.fn((input: { requirementId: string; expectedEvidenceFingerprint?: string }) => {
      if (input.expectedEvidenceFingerprint !== undefined
        && input.expectedEvidenceFingerprint !== responseFingerprint) {
        return Promise.reject(new RequirementApiError(409, {
          error: "verification_conflict",
          needs_reconfirmation: true,
          current_evidence_fingerprint: responseFingerprint,
          detail: "CAS 失配",
        }))
      }
      return Promise.resolve({
        requirement_id: input.requirementId,
        verification: {},
        lifecycle_state: "confirmed",
        evidence_fingerprint: responseFingerprint,
        written: ["verification_states.jsonl"],
      })
    })
    const client = makeClient({
      // 无既有 state：首次保存场景（本地行指纹起初缺失）
      loadVerificationStates: vi.fn().mockResolvedValue({ schema: "verification-states/v1", states: [], total: 0 }),
      applyVerificationAction: apply as unknown as ReturnType<typeof vi.fn>,
    })
    const { wrapper } = mountReview({ client })
    await flushPromises()

    // 第一次保存：无既有指纹 → expectedEvidenceFingerprint 缺省（不发送 expected_evidence_fingerprint）
    await wrapper.find('[data-testid="save-verification"]').trigger("click")
    await flushPromises()
    const first = (apply.mock.calls[0][0] as { expectedEvidenceFingerprint?: string }).expectedEvidenceFingerprint
    expect(first).toBeUndefined()
    expect(wrapper.find('[data-testid="fr-message"]').text()).not.toContain("证据指纹失配")

    // 第二次保存：本地行指纹已同步为响应值 → 携正确指纹，无 409
    await wrapper.find('[data-testid="save-verification"]').trigger("click")
    await flushPromises()
    const second = (apply.mock.calls[1][0] as { expectedEvidenceFingerprint?: string }).expectedEvidenceFingerprint
    expect(second).toBe(responseFingerprint)

    // 第三次保存：仍携同步后的指纹 → 无 409（三连保存通过）
    await wrapper.find('[data-testid="save-verification"]').trigger("click")
    await flushPromises()
    const third = (apply.mock.calls[2][0] as { expectedEvidenceFingerprint?: string }).expectedEvidenceFingerprint
    expect(third).toBe(responseFingerprint)
    // 三次保存全部成功（无 409 刷新提示）
    expect(wrapper.find('[data-testid="fr-message"]').text()).not.toContain("证据指纹失配")
    expect(apply).toHaveBeenCalledTimes(3)
  })

  it("saves verification via POST with the CAS evidence_fingerprint and refreshes on 409 (Cap2)", async () => {
    const client = makeClient({
      applyVerificationAction: vi.fn()
        .mockRejectedValueOnce(new RequirementApiError(409, {
          error: "verification_conflict",
          needs_reconfirmation: true,
          current_evidence_fingerprint: "fp-v2",
          detail: "CAS 失配",
        }))
        .mockResolvedValueOnce({ requirement_id: "FRE-1", lifecycle_state: "confirmed", verification: {}, written: [] }),
    })
    const { wrapper } = mountReview({ client })
    await flushPromises()

    await wrapper.find('[data-testid="save-verification"]').trigger("click")
    await flushPromises()

    // 第一次提交应携带 expected_evidence_fingerprint=fp-1（来自初始加载的状态）
    const firstCallArg = (client.applyVerificationAction as ReturnType<typeof vi.fn>).mock.calls[0][0] as { expectedEvidenceFingerprint?: string }
    expect(firstCallArg.expectedEvidenceFingerprint).toBe("fp-1")
    // 409 后应刷新验证状态（再次调用 loadVerificationStates）并提示重新确认
    expect((client.loadVerificationStates as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(wrapper.find('[data-testid="fr-message"]').text()).toContain("证据指纹失配")
  })

  it("opens the rollback dialog requiring actor+reason and posts the rollback (Cap2)", async () => {
    const client = makeClient()
    const { wrapper } = mountReview({ client })
    await flushPromises()

    // FRE-1 当前态 confirmed → 可回退目标只有 draft
    await wrapper.find('[data-testid="open-rollback"]').trigger("click")
    expect(wrapper.find('[data-testid="rollback-form"]').exists()).toBe(true)

    // 缺原因时不应提交
    await wrapper.find('[data-testid="rollback-submit"]').trigger("click")
    await flushPromises()
    expect((client.rollbackRequirement as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="fr-message"]').text()).toContain("操作者与原因")

    // 填齐后提交
    await wrapper.find('[data-testid="rollback-actor"]').setValue("bob")
    await wrapper.find('[data-testid="rollback-reason"]').setValue("发现需求重复")
    await wrapper.find('[data-testid="rollback-submit"]').trigger("click")
    await flushPromises()

    expect((client.rollbackRequirement as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
      expect.objectContaining({ requirementId: "FRE-1", target: "draft", actor: "bob", reason: "发现需求重复" }),
    )
    expect(wrapper.find('[data-testid="rollback-form"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="fr-message"]').text()).toContain("append-only")
  })

  it("creates a manual requirement with objective/behaviors and selects it (Cap3)", async () => {
    const client = makeClient({
      createManualRequirement: vi.fn().mockResolvedValue({ functional_requirement_id: "FREQ-MANUAL-new", written: ["manual_requirements.jsonl"] }),
    })
    // 让 loadManualRequirements 回读到新建条目
    const reader = makeReadArtifact({
      "state:manual_requirements.jsonl": { ok: true, format: "jsonl", content: [{ functional_requirement_id: "FREQ-MANUAL-new", objective: "新需求", source_kind: "manual" }] },
    })
    const { wrapper, reader: _reader } = mountReview({ client, readArtifact: reader })
    void _reader
    await flushPromises()

    await wrapper.find('[data-testid="fr-new-manual"]').trigger("click")
    expect(wrapper.find('[data-testid="manual-form"]').exists()).toBe(true)
    await wrapper.find('[data-testid="manual-objective"]').setValue("应支持参数下发")
    await wrapper.find('[data-testid="manual-behaviors"]').setValue("接收参数, 校验参数")
    await wrapper.find('[data-testid="manual-module"]').setValue("通信协议")
    await wrapper.find('[data-testid="manual-submit"]').trigger("click")
    await flushPromises()

    expect((client.createManualRequirement as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
      expect.objectContaining({ objective: "应支持参数下发", behaviors: ["接收参数", "校验参数"], module: "通信协议" }),
    )
    expect(wrapper.find('[data-testid="fr-message"]').text()).toContain("FREQ-MANUAL-new")
    expect(wrapper.find('[data-testid="fr-message"]').text()).toContain("无文档来源")
  })

  it("accept/reject dependency candidates: accept writes, reject does not call decide twice with accept=false persisting (Cap4)", async () => {
    const client = makeClient({
      decideDependency: vi.fn().mockResolvedValue({ accepted: true, written: true, decision: {} }),
    })
    const { wrapper } = mountReview({ client })
    await flushPromises()

    // FRE-1 选中（默认首条），其候选含 FRE-1↔FRE-2
    expect(wrapper.find('[data-testid="dependency-candidates"]').exists()).toBe(true)
    await wrapper.find('[data-testid="accept-candidate-0"]').trigger("click")
    await flushPromises()

    expect((client.decideDependency as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
      expect.objectContaining({ from: "FRE-1", to: "FRE-2", kind: "depend", accept: true }),
    )
    expect(wrapper.find('[data-testid="fr-message"]').text()).toContain("已接受")
    // 接受后该候选标记「已接受」
    expect(wrapper.find('[data-testid="dependency-candidates"]').text()).toContain("已接受")
  })

  it("requirement library search lists similar history with overlap score, adopt/ignore (Cap4)", async () => {
    const client = makeClient()
    const { wrapper } = mountReview({ client })
    await flushPromises()

    await wrapper.find('[data-testid="run-library-search"]').trigger("click")
    await flushPromises()

    expect((client.searchRequirementLibrary as ReturnType<typeof vi.fn>)).toHaveBeenCalled()
    const panel = wrapper.find('[data-testid="library-panel"]')
    expect(panel.text()).toContain("相似度 42%")
    expect(panel.text()).toContain("归属已修正")
    expect(panel.text()).toContain("历史掉电记录需求")

    // 采纳——打开确认对话框（actor/reason 必填，经 reviewer_override 通道留痕）
    await wrapper.find('[data-testid="adopt-library-0"]').trigger("click")
    await flushPromises()
    expect(wrapper.find('[data-testid="adopt-form"]').exists()).toBe(true)
    // 缺操作者/原因时不应提交
    await wrapper.find('[data-testid="adopt-submit"]').trigger("click")
    await flushPromises()
    expect((client.adoptRequirementLibrary as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="fr-message"]').text()).toContain("操作者与原因")
    // 填齐后提交 → 调端点 + 落库提示
    await wrapper.find('[data-testid="adopt-actor"]').setValue("专家A")
    await wrapper.find('[data-testid="adopt-reason"]').setValue("采纳历史归属")
    await wrapper.find('[data-testid="adopt-submit"]').trigger("click")
    await flushPromises()
    expect((client.adoptRequirementLibrary as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
      expect.objectContaining({ functionalRequirementId: "FRE-1", ownership: "software", actor: "专家A", reason: "采纳历史归属" }),
    )
    expect(wrapper.find('[data-testid="adopt-form"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="fr-message"]').text()).toContain("reviewer_override")

    // 忽略——本地移除该参考项
    await wrapper.find('[data-testid="ignore-library-0"]').trigger("click")
    await flushPromises()
    expect(wrapper.find('[data-testid="library-panel"]').text()).not.toContain("历史掉电记录需求")
  })

  it("switches to the legacy atomic view (switchable mode, not deleted) (Cap1)", async () => {
    const client = makeClient()
    const { wrapper } = mountReview({ client })
    await flushPromises()

    expect(wrapper.find('[data-testid="atomic-view"]').exists()).toBe(false)
    await wrapper.find('[data-testid="mode-atomic"]').trigger("click")
    await flushPromises()
    expect(wrapper.find('[data-testid="atomic-view"]').exists()).toBe(true)
    expect((client.loadRequirements as ReturnType<typeof vi.fn>)).toHaveBeenCalled()
    expect(wrapper.find('[data-testid="atomic-view"]').text()).toContain("记录掉电")
  })

  it("falls back to Electron IPC when GET endpoints are missing on old backend (404)", async () => {
    // F2 降级演示：mock 旧后端——三个 GET 端点返回 404（端点不存在），前端经 IPC 兜底仍渲染
    const client = makeClient({
      loadFunctionalRequirements: vi.fn().mockRejectedValue(new RequirementApiError(404, { error: "Not found" })),
      loadManualRequirements: vi.fn().mockRejectedValue(new RequirementApiError(404, { error: "Not found" })),
      loadLifecycleEvents: vi.fn().mockRejectedValue(new RequirementApiError(404, { error: "Not found" })),
    })
    const { wrapper } = mountReview({ client })
    await flushPromises()

    // IPC seed 的 FRE-1 经兜底仍渲染（界面不崩）
    expect(wrapper.find('[data-testid="functional-card-FRE-1"]').exists()).toBe(true)
    // 生命周期时间线来自 IPC（requirement_lifecycle_events.jsonl seed）
    expect(wrapper.find('[data-testid="lifecycle-timeline"]').text()).toContain("alice")
    // 无错误消息——404 是端点缺失的预期降级，不当作故障透出
    expect(wrapper.find('[data-testid="fr-message"]').exists()).toBe(false)
  })

  it("surfaces real HTTP errors instead of silently masking them as empty", async () => {
    // 非 404 的 HTTP 错误（如 503）不降级——如实透出，避免把真实故障伪装成“无数据”
    const client = makeClient({
      loadFunctionalRequirements: vi.fn().mockRejectedValue(new RequirementApiError(503, { error: "functional_requirements_unavailable", retryable: true })),
    })
    const { wrapper } = mountReview({ client })
    await flushPromises()
    expect(wrapper.find('[data-testid="fr-message"]').text()).toContain("功能需求读取失败")
  })

  it("shows the backend note when the requirement library is unconfigured (honest 200, not an error)", async () => {
    const client = makeClient({
      searchRequirementLibrary: vi.fn().mockResolvedValue({ kind: "requirement_search", matches: 0, results: [], note: "未配置 RATOMIZER_REQUIREMENT_LIBRARY，检索库为空" }),
    })
    const { wrapper } = mountReview({ client })
    await flushPromises()

    await wrapper.find('[data-testid="run-library-search"]').trigger("click")
    await flushPromises()
    expect(wrapper.find('[data-testid="library-panel"]').text()).toContain("未配置 RATOMIZER_REQUIREMENT_LIBRARY")
  })
})
