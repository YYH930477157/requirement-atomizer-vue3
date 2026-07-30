import { describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import ClaimLedger from "../ClaimLedger.vue"

const ratio = (numerator: number, denominator: number) => ({
  numerator,
  denominator,
  value: denominator ? numerator / denominator : null,
})

function envelope(revision = "sha256:revision-1") {
  return {
    available: true,
    phase: "production-dual-write-v1" as const,
    document_effective_revision: revision,
    base_generation_id: "sha256:base-generation",
    event_prefix_sha256: "sha256:event-prefix",
    effective_fresh: true,
  }
}

function catalogPayload(revision = "sha256:revision-1") {
  return {
    ...envelope(revision),
    schema: "claim-catalog-view/v1",
    total: 1,
    limit: 25,
    offset: 0,
    owner_unit_ids: ["UNIT-1111111111111111"],
    rows: [{
      claim_id: "CLM-1111111111111111",
      claim_hash: "sha256:claim",
      text: "The product shall support operator configuration of the indicator channel.",
      owner_unit_id: "UNIT-1111111111111111",
      locator: { block_id: "BLK-7", line: 2, start: 11, end: 78, position_basis: "repaired_text" },
      eligibility: "claim" as const,
      resolution: "covered" as const,
      classification: "normative" as const,
      classification_status: "validated" as const,
      exclusion_kind: null,
      claim_effective_revision: `${revision}-claim`,
    }],
  }
}

function metricsPayload(revision = "sha256:revision-1") {
  return {
    ...envelope(revision),
    schema: "claim-metrics-view/v1",
    generation_metrics_version: "claim-ledger-v3",
    effective_metrics_version: "claim-effective-reducer-v1",
    generation_metrics: {},
    effective_metrics: {
      inventory_accounted_ratio: ratio(10, 10),
      verified_coverage_ratio: ratio(7, 10),
      verified_exclusion_ratio: ratio(2, 12),
      eligible_resolution_ratio: ratio(9, 10),
      uncertain_count: 1,
    },
    document_ready: false,
    health: {},
  }
}

function queuePayload(revision = "sha256:revision-1") {
  return {
    ...envelope(revision),
    schema: "claim-queue-view/v1",
    proposals: [{
      proposal_id: "CQP-11111111-22222222",
      claim_id: "CLM-2222222222222222",
      parent_block_id: "BLK-9",
      locator: { block_id: "BLK-9", start: 0, end: 21 },
      action: "needs_extraction" as const,
      dry_run: false as const,
      claim_hash: "sha256:queue-claim",
      claim_effective_revision: `${revision}-queue`,
      lifecycle: "open" as const,
      focus_error: null,
      latest_attempt: null,
    }],
    compat_omissions: [{
      omission_id: "OM-BLK-10",
      block_id: "BLK-10",
      reason: "legacy omission",
      compat_whole_block: true as const,
      dry_run: true as const,
    }],
  }
}

function groupsPayload(revision = "sha256:revision-1", target = "AIR-1") {
  return {
    ...envelope(revision),
    schema: "claim-coverage-group-view/v1",
    total: 1,
    groups: [{
      coverage_group_id: "CGR-1111111111111111",
      claim_id: "CLM-1111111111111111",
      validation_method: "independent_semantic" as const,
      status: "validated" as const,
      effective_status: "validated",
      reused: true,
      edges: [{
        edge_id: `CED-${target}`,
        target_kind: "ai_requirement" as const,
        target_requirement_id: target,
        target_review_eligibility: "active" as const,
        relation: "generated_from" as const,
        produced_evidence: [{ field: "description", text: `Evidence ${target}` }],
      }],
    }],
  }
}

function eventsPayload(revision = "sha256:revision-1") {
  return {
    ...envelope(revision),
    schema: "claim-review-event-view/v1",
    total: 1,
    events: [{
      event_seq: 1,
      event_id: "CRE-1-111111111111",
      claim_id: "CLM-1111111111111111",
      event_kind: "target_reactivated" as const,
      recorded_at: "2026-07-28T12:00:00Z",
      target_requirement_id: "AIR-1",
    }],
  }
}

function makeClient(overrides: Record<string, unknown> = {}) {
  return {
    loadClaimCatalog: vi.fn().mockResolvedValue(catalogPayload()),
    loadClaimLedger: vi.fn().mockResolvedValue({ ...envelope(), schema: "claim-ledger-view/v1", rows: [], total: 0, limit: 25, offset: 0 }),
    loadClaimMetrics: vi.fn().mockResolvedValue(metricsPayload()),
    loadClaimQueue: vi.fn().mockResolvedValue(queuePayload()),
    loadClaimCoverageGroups: vi.fn().mockResolvedValue(groupsPayload()),
    loadClaimReviewEvents: vi.fn().mockResolvedValue(eventsPayload()),
    executeClaimQueue: vi.fn().mockResolvedValue({
      schema: "claim-queue-execution/v1",
      proposal_id: "CQP-11111111-22222222",
      attempt_id: "CRA-1111111111111111",
      lifecycle: "executed",
    }),
    applyClaimAdjudication: vi.fn().mockResolvedValue({ ok: true }),
    loadAiExtractionStatus: vi.fn().mockResolvedValue({
      schema: "ai-requirements-partial/v1",
      run_id: "run-1", completed: 1, total: 1, complete: true, rows: [],
      quality: { coverage_pct: 82.5, core_coverage_pct: 75 },
    }),
    ...overrides,
  }
}

describe("ClaimLedger", () => {
  it("renders revision-pinned metrics, comparison, claims, and Queue v2 actions", async () => {
    const client = makeClient()
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    expect(wrapper.text()).toContain("双写观察期 · 不影响 READY 判定")
    expect(wrapper.get('[data-testid="claim-metric-coverage"]').text()).toContain("70.0%")
    expect(wrapper.get('[data-testid="claim-metric-coverage"]').text()).toContain("7 / 10")
    expect(wrapper.text()).toContain("82.5%")
    expect(wrapper.text()).toContain("75.0%")
    expect(wrapper.text()).toContain("ai_extract_quality.json")
    expect(wrapper.get('[data-testid="claim-row"]').text()).toContain("The product shall support")

    await wrapper.findAll('[role="tab"]')[1].trigger("click")
    expect(wrapper.get('[data-testid="claim-queue"]').text()).toContain("CLM-2222222222222222")
    expect(wrapper.get('[data-testid="claim-queue"]').text()).toContain("OM-BLK-10")
    expect(wrapper.get('[data-testid="claim-queue"]').text()).toContain("dry-run")
    expect(wrapper.get('[data-testid="claim-execute-CLM-2222222222222222"]').text()).toContain("执行")
  })

  it("forwards Queue v2 budgets and refreshes all overview views after execution", async () => {
    const executeClaimQueue = vi.fn().mockResolvedValue({
      schema: "claim-queue-execution/v1",
      proposal_id: "CQP-11111111-22222222",
      attempt_id: "CRA-1111111111111111",
      lifecycle: "executed",
    })
    const client = makeClient({ executeClaimQueue })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.findAll('[role="tab"]')[1].trigger("click")
    const budgetInputs = wrapper.get('[data-testid="claim-queue-budget"]').findAll("input")
    await budgetInputs[0].setValue("7")
    await budgetInputs[1].setValue("64000")
    await wrapper.get('[data-testid="claim-execute-CLM-2222222222222222"]').trigger("click")
    await flushPromises()

    expect(executeClaimQueue).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="claim-queue-confirm-execute"]').attributes("disabled")).toBeDefined()
    await wrapper.get('[data-testid="claim-queue-allow-llm"]').setValue(true)
    await wrapper.get('[data-testid="claim-queue-confirm-execute"]').trigger("click")
    await flushPromises()

    expect(executeClaimQueue).toHaveBeenCalledWith({
      proposalId: "CQP-11111111-22222222",
      expectedClaimEffectiveRevision: "sha256:revision-1-queue",
      actor: "reviewer",
      allowLlm: true,
      route: "openai_compatible",
      maximumCalls: 7,
      totalTokenBudget: 64000,
      requestIdempotencyKey: expect.stringMatching(/^claim-queue-/),
    })
    expect(client.loadClaimCatalog).toHaveBeenCalledTimes(2)
    expect(client.loadClaimMetrics).toHaveBeenCalledTimes(2)
    expect(client.loadClaimQueue).toHaveBeenCalledTimes(2)
    expect(client.loadAiExtractionStatus).toHaveBeenCalledTimes(2)

    await wrapper.get('[data-testid="claim-execute-CLM-2222222222222222"]').trigger("click")
    expect((wrapper.get('[data-testid="claim-queue-allow-llm"]').element as HTMLInputElement).checked).toBe(false)
  })

  it("does not retain queue LLM authorization after cancellation or a tab switch", async () => {
    const executeClaimQueue = vi.fn()
    const client = makeClient({ executeClaimQueue })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.findAll('[role="tab"]')[1].trigger("click")
    const execute = wrapper.get('[data-testid="claim-execute-CLM-2222222222222222"]')
    await execute.trigger("click")
    await wrapper.get('[data-testid="claim-queue-allow-llm"]').setValue(true)
    await wrapper.get('[data-testid="claim-queue-cancel"]').trigger("click")
    expect(wrapper.find('[data-testid="claim-queue-confirm"]').exists()).toBe(false)
    expect(executeClaimQueue).not.toHaveBeenCalled()

    await execute.trigger("click")
    expect((wrapper.get('[data-testid="claim-queue-allow-llm"]').element as HTMLInputElement).checked).toBe(false)
    await wrapper.get('[data-testid="claim-queue-allow-llm"]').setValue(true)
    await wrapper.findAll('[role="tab"]')[0].trigger("click")
    expect(wrapper.find('[data-testid="claim-queue-confirm"]').exists()).toBe(false)

    await wrapper.findAll('[role="tab"]')[1].trigger("click")
    await wrapper.get('[data-testid="claim-execute-CLM-2222222222222222"]').trigger("click")
    expect((wrapper.get('[data-testid="claim-queue-allow-llm"]').element as HTMLInputElement).checked).toBe(false)
  })

  it("resumes rebuild_pending with the original request idempotency key", async () => {
    const pending = queuePayload()
    Object.assign(pending.proposals[0], {
      lifecycle: "rebuild_pending",
      latest_attempt: {
        attempt_id: "CRA-pending",
        request_idempotency_key: "claim-queue-original-request",
        lifecycle: "rebuild_pending",
        last_event_seq: 4,
        outcome: null,
      },
    })
    const executeClaimQueue = vi.fn().mockResolvedValue({
      schema: "claim-queue-execution/v1",
      proposal_id: "CQP-11111111-22222222",
      attempt_id: "CRA-pending",
      lifecycle: "executed",
    })
    const client = makeClient({
      loadClaimQueue: vi.fn().mockResolvedValue(pending),
      executeClaimQueue,
    })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.findAll('[role="tab"]')[1].trigger("click")
    const button = wrapper.get('[data-testid="claim-execute-CLM-2222222222222222"]')
    expect(button.text()).toContain("恢复")
    await button.trigger("click")
    await wrapper.get('[data-testid="claim-queue-allow-llm"]').setValue(true)
    await wrapper.get('[data-testid="claim-queue-confirm-execute"]').trigger("click")
    await flushPromises()

    expect(executeClaimQueue).toHaveBeenCalledWith(expect.objectContaining({
      proposalId: "CQP-11111111-22222222",
      requestIdempotencyKey: "claim-queue-original-request",
    }))
  })

  it("submits typed coverage evidence for expert adjudication and refreshes the overview", async () => {
    const catalog = catalogPayload()
    Object.assign(catalog.rows[0], {
      source_text_hash: "sha256:source-text",
      base_resolution_fact_hashes: { positive: ["sha256:base-covered"] },
    })
    const groups = groupsPayload()
    Object.assign(groups.groups[0], { coverage_group_hash: "sha256:coverage-group" })
    const events = eventsPayload()
    Object.assign(events.events[0], {
      event_kind: "expert_adjudication",
      event_hash: "sha256:previous-expert",
    })
    const applyClaimAdjudication = vi.fn().mockResolvedValue({ ok: true })
    const client = makeClient({
      loadClaimCatalog: vi.fn().mockResolvedValue(catalog),
      loadClaimCoverageGroups: vi.fn().mockResolvedValue(groups),
      loadClaimReviewEvents: vi.fn().mockResolvedValue(events),
      applyClaimAdjudication,
    })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.get('[data-testid="claim-row"]').trigger("click")
    await flushPromises()
    await wrapper.get('textarea[aria-label="Claim 裁决理由"]').setValue("人工确认语义覆盖")
    await wrapper.get('[data-testid="claim-adjudicate-covered"]').trigger("click")
    await flushPromises()

    expect(applyClaimAdjudication).toHaveBeenCalledWith({
      claimId: "CLM-1111111111111111",
      claimHash: "sha256:claim",
      adjudication: "covered",
      reason: "人工确认语义覆盖",
      evidence: {
        kind: "coverage_group",
        coverage_group_id: "CGR-1111111111111111",
        coverage_group_hash: "sha256:coverage-group",
      },
      actor: "reviewer",
      expectedClaimEffectiveRevision: "sha256:revision-1-claim",
      supersedesFactHashes: ["sha256:base-covered", "sha256:previous-expert"],
      requestIdempotencyKey: expect.stringMatching(/^claim-adjudication-/),
    })
    expect(client.loadClaimCatalog).toHaveBeenCalledTimes(2)
  })

  it("supersedes both sides of a base coverage conflict", async () => {
    const catalog = catalogPayload()
    Object.assign(catalog.rows[0], {
      resolution: "uncertain",
      source_text_hash: "sha256:source-text",
      base_resolution_fact_hashes: {
        positive: ["sha256:base-positive"],
        negative: ["sha256:base-negative-a", "sha256:base-negative-b"],
      },
    })
    const groups = groupsPayload()
    Object.assign(groups.groups[0], { coverage_group_hash: "sha256:coverage-group" })
    const applyClaimAdjudication = vi.fn().mockResolvedValue({ ok: true })
    const client = makeClient({
      loadClaimCatalog: vi.fn().mockResolvedValue(catalog),
      loadClaimCoverageGroups: vi.fn().mockResolvedValue(groups),
      applyClaimAdjudication,
    })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.get('[data-testid="claim-row"]').trigger("click")
    await flushPromises()
    await wrapper.get('[data-testid="claim-adjudication"] textarea').setValue("Supersede both base conflict sides")
    await wrapper.get('[data-testid="claim-adjudicate-covered"]').trigger("click")
    await flushPromises()

    expect(applyClaimAdjudication).toHaveBeenCalledWith(expect.objectContaining({
      adjudication: "covered",
      supersedesFactHashes: [
        "sha256:base-positive",
        "sha256:base-negative-a",
        "sha256:base-negative-b",
      ],
    }))
  })

  it("offers and submits exactly the backend-controlled non-normative exclusion reasons", async () => {
    const catalog = catalogPayload()
    Object.assign(catalog.rows[0], { source_text_hash: "sha256:source-text" })
    const applyClaimAdjudication = vi.fn().mockResolvedValue({ ok: true })
    const client = makeClient({
      loadClaimCatalog: vi.fn().mockResolvedValue(catalog),
      applyClaimAdjudication,
    })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    const reasons = ["scope_statement", "definition", "informative", "example", "instrument_only"] as const
    for (const [index, reason] of reasons.entries()) {
      await wrapper.get('[data-testid="claim-row"]').trigger("click")
      await flushPromises()
      const select = wrapper.get('select[aria-label="非规范内容类型"]')
      if (index === 0) {
        expect(select.findAll("option").map((option) => option.attributes("value"))).toEqual(reasons)
        expect(select.findAll('option[value="context_only"]')).toHaveLength(0)
      }
      await select.setValue(reason)
      await wrapper.get('textarea[aria-label="Claim 裁决理由"]').setValue(`排除：${reason}`)
      await wrapper.get('[data-testid="claim-adjudicate-excluded"]').trigger("click")
      await flushPromises()

      expect(applyClaimAdjudication).toHaveBeenNthCalledWith(index + 1, expect.objectContaining({
        adjudication: "excluded_non_normative",
        evidence: expect.objectContaining({
          kind: "source_exclusion",
          exclusion_reason: reason,
        }),
      }))
    }
  })

  it("defaults structural false-positive override to a zero-LLM rebuild", async () => {
    const catalog = catalogPayload()
    Object.assign(catalog, { catalog_generation_id: "sha256:catalog-generation" })
    Object.assign(catalog.rows[0], {
      resolution: "excluded",
      exclusion_kind: "structural",
      exclusion: { reason: "repeated_page_furniture" },
    })
    const confirmClaimStructuralOverride = vi.fn().mockResolvedValue({ ok: true, status: "rebuilt" })
    const client = makeClient({
      loadClaimCatalog: vi.fn().mockResolvedValue(catalog),
      confirmClaimStructuralOverride,
    })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.get('[data-testid="claim-row"]').trigger("click")
    await flushPromises()
    expect(wrapper.get('[data-testid="claim-structural-mode"]').text()).toContain("0 LLM")
    expect((wrapper.get('[data-testid="claim-structural-llm"]').element as HTMLInputElement).checked).toBe(false)

    await wrapper.get('textarea[aria-label="Claim 裁决理由"]').setValue("确认该内容不是重复页眉页脚")
    await wrapper.get('[data-testid="claim-structural-override"]').trigger("click")
    await flushPromises()

    expect(confirmClaimStructuralOverride).toHaveBeenCalledWith({
      claimId: "CLM-1111111111111111",
      claimHash: "sha256:claim",
      expectedCatalogGenerationId: "sha256:catalog-generation",
      expectedClaimEffectiveRevision: "sha256:revision-1-claim",
      priorStructuralReason: "repeated_page_furniture",
      reason: "确认该内容不是重复页眉页脚",
      actor: "reviewer",
      requestIdempotencyKey: expect.stringMatching(/^claim-structural-/),
      allowLlm: false,
      route: "stub",
      verifierMaxCalls: 0,
      verifierMaxTotalTokens: 0,
    })
  })

  it("uses the paid structural verifier only after explicit authorization", async () => {
    const catalog = catalogPayload()
    Object.assign(catalog, { catalog_generation_id: "sha256:catalog-generation" })
    Object.assign(catalog.rows[0], {
      resolution: "excluded",
      exclusion_kind: "structural",
      exclusion: { reason: "repeated_page_furniture" },
    })
    const confirmClaimStructuralOverride = vi.fn().mockResolvedValue({ ok: true, status: "rebuilt" })
    const client = makeClient({
      loadClaimCatalog: vi.fn().mockResolvedValue(catalog),
      confirmClaimStructuralOverride,
    })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.get('[data-testid="claim-row"]').trigger("click")
    await flushPromises()
    await wrapper.get('[data-testid="claim-structural-llm"]').setValue(true)
    expect(wrapper.get('[data-testid="claim-structural-mode"]').text()).toContain("LLM 语义复核")
    await wrapper.get('button[aria-label="关闭详情"]').trigger("click")
    await wrapper.get('[data-testid="claim-row"]').trigger("click")
    await flushPromises()
    expect((wrapper.get('[data-testid="claim-structural-llm"]').element as HTMLInputElement).checked).toBe(false)
    await wrapper.get('[data-testid="claim-structural-llm"]').setValue(true)
    const budgetInputs = wrapper.get('[data-testid="claim-structural-budget"]').findAll("input")
    await budgetInputs[0].setValue("3")
    await budgetInputs[1].setValue("18000")
    await wrapper.get('textarea[aria-label="Claim 裁决理由"]').setValue("确认后使用语义复核")
    await wrapper.get('[data-testid="claim-structural-override"]').trigger("click")
    await flushPromises()

    expect(confirmClaimStructuralOverride).toHaveBeenCalledWith(expect.objectContaining({
      allowLlm: true,
      route: "openai_compatible",
      verifierMaxCalls: 3,
      verifierMaxTotalTokens: 18000,
    }))
  })

  it("renders an unavailable legacy directory with its null revision envelope", async () => {
    const unavailable = {
      available: false,
      phase: "production-dual-write-v1" as const,
      document_effective_revision: null,
      base_generation_id: null,
      event_prefix_sha256: null,
      effective_fresh: false,
      reason: "当前输出目录尚无 Claim Ledger generation",
    }
    const client = makeClient({
      loadClaimCatalog: vi.fn().mockResolvedValue({
        ...unavailable,
        schema: "claim-catalog-view/v1",
        rows: [], total: 0, limit: 100, offset: 0, owner_unit_ids: [],
      }),
      loadClaimMetrics: vi.fn().mockResolvedValue({
        ...unavailable,
        schema: "claim-metrics-view/v1",
        generation_metrics: {}, effective_metrics: {}, document_ready: null,
      }),
      loadClaimQueue: vi.fn().mockResolvedValue({
        ...unavailable,
        schema: "claim-queue-view/v1",
        proposals: [], compat_omissions: [], total: 0,
      }),
    })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    expect(wrapper.get('[data-testid="claim-unavailable"]').text()).toContain("当前目录没有可用账本")
    expect(wrapper.text()).toContain("当前输出目录尚无 Claim Ledger generation")
    expect(wrapper.text()).toContain("Revision —")
  })

  it("loads coverage edges and review events only for the pinned revision", async () => {
    const client = makeClient()
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.get('[data-testid="claim-row"]').trigger("click")
    await flushPromises()

    expect(wrapper.get('[data-testid="claim-detail"]').text()).toContain("AIR-1")
    expect(wrapper.get('[data-testid="claim-group"]').text()).toContain("independent_semantic")
    expect(wrapper.get('[data-testid="claim-event"]').text()).toContain("目标恢复")
  })

  it("discards mismatched detail responses and refetches against one new revision", async () => {
    const revision1 = "sha256:revision-1"
    const revision2 = "sha256:revision-2"
    const loadClaimCatalog = vi.fn()
      .mockResolvedValueOnce(catalogPayload(revision1))
      .mockResolvedValueOnce(catalogPayload(revision2))
    const loadClaimMetrics = vi.fn()
      .mockResolvedValueOnce(metricsPayload(revision1))
      .mockResolvedValueOnce(metricsPayload(revision2))
    const loadClaimQueue = vi.fn()
      .mockResolvedValueOnce(queuePayload(revision1))
      .mockResolvedValueOnce(queuePayload(revision2))
    const loadClaimCoverageGroups = vi.fn()
      .mockResolvedValueOnce(groupsPayload(revision2, "STALE-TARGET"))
      .mockResolvedValueOnce(groupsPayload(revision2, "FRESH-TARGET"))
    const loadClaimReviewEvents = vi.fn()
      .mockResolvedValueOnce(eventsPayload(revision1))
      .mockResolvedValueOnce(eventsPayload(revision2))
    const client = makeClient({
      loadClaimCatalog,
      loadClaimMetrics,
      loadClaimQueue,
      loadClaimCoverageGroups,
      loadClaimReviewEvents,
    })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.get('[data-testid="claim-row"]').trigger("click")
    await flushPromises()

    const detail = wrapper.get('[data-testid="claim-detail"]').text()
    expect(detail).toContain("FRESH-TARGET")
    expect(detail).not.toContain("STALE-TARGET")
    expect(loadClaimCatalog).toHaveBeenCalledTimes(2)
    expect(loadClaimCoverageGroups).toHaveBeenCalledTimes(2)
  })

  it("sends resolution and owner filters with a reset offset", async () => {
    const loadClaimCatalog = vi.fn().mockResolvedValue(catalogPayload())
    const client = makeClient({ loadClaimCatalog })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.get('select[aria-label="Claim 结论"]').setValue("uncertain")
    await flushPromises()

    expect(loadClaimCatalog).toHaveBeenLastCalledWith({
      resolution: "uncertain",
      ownerUnitId: "",
      limit: 25,
      offset: 0,
    })
  })
})
