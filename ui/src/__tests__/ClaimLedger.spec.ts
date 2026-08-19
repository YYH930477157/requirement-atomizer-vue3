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
    structural_candidate_decision_registry: {
      version: "claim-structural-candidate-decision-v2",
      prefix_sha256: "sha256:decision-prefix-1",
      prefix_count: 0,
    },
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
    structural_review_pending_count: 1,
    structural_review_confirmed_exclusion_count: 2,
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
    total: 1,
    limit: 25,
    offset: 0,
    compat_omission_total: 1,
    compat_omission_limit: 1,
    compat_omission_offset: 0,
    route_preflight: {
      route: "openai_compatible",
      configured: true,
      model: "deepseek-chat",
      route_config_revision: "sha256:route-config-1",
    },
  }
}

function groupsPayload(revision = "sha256:revision-1", target = "AIR-1") {
  return {
    ...envelope(revision),
    schema: "claim-coverage-group-view/v1",
    total: 1,
    limit: 500,
    offset: 0,
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
    limit: 500,
    offset: 0,
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

    expect(wrapper.text()).toContain("看原文有没有被功能条盖住 · 不是需求流水线")
    expect(wrapper.get('[data-testid="claim-structural-pending-count"]').text()).toContain("1")
    expect(wrapper.get('[data-testid="claim-structural-confirmed-count"]').text()).toContain("2")
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

  it("retries overview when the structural decision registry changes mid-read", async () => {
    const firstCatalog = catalogPayload()
    const firstMetrics = metricsPayload()
    const firstQueue = queuePayload()
    firstMetrics.structural_candidate_decision_registry = {
      version: "claim-structural-candidate-decision-v2",
      prefix_sha256: "sha256:decision-prefix-2",
      prefix_count: 1,
    }
    const settledCatalog = catalogPayload()
    const settledMetrics = metricsPayload()
    const settledQueue = queuePayload()
    for (const payload of [settledCatalog, settledMetrics, settledQueue]) {
      payload.structural_candidate_decision_registry = {
        version: "claim-structural-candidate-decision-v2",
        prefix_sha256: "sha256:decision-prefix-2",
        prefix_count: 1,
      }
    }
    const loadClaimCatalog = vi.fn()
      .mockResolvedValueOnce(firstCatalog)
      .mockResolvedValue(settledCatalog)
    const loadClaimMetrics = vi.fn()
      .mockResolvedValueOnce(firstMetrics)
      .mockResolvedValue(settledMetrics)
    const loadClaimQueue = vi.fn()
      .mockResolvedValueOnce(firstQueue)
      .mockResolvedValue(settledQueue)
    const client = makeClient({
      loadClaimCatalog,
      loadClaimMetrics,
      loadClaimQueue,
    })

    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    expect(loadClaimCatalog).toHaveBeenCalledTimes(2)
    expect(loadClaimMetrics).toHaveBeenCalledTimes(2)
    expect(loadClaimQueue).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-testid="claim-row"]').text()).toContain(
      "The product shall support",
    )
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
    expect(wrapper.get('[data-testid="claim-queue-model"]').text()).toBe("deepseek-chat")
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
      expectedRouteConfigRevision: "sha256:route-config-1",
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
    expect(wrapper.get('[data-testid="claim-queue-recovery-notice"]').text())
      .toContain("不会调用 LLM")
    expect(wrapper.find('[data-testid="claim-queue-allow-llm"]').exists()).toBe(false)
    await wrapper.get('[data-testid="claim-queue-confirm-execute"]').trigger("click")
    await flushPromises()

    expect(executeClaimQueue).toHaveBeenCalledWith(expect.objectContaining({
      proposalId: "CQP-11111111-22222222",
      requestIdempotencyKey: "claim-queue-original-request",
      allowLlm: false,
      maximumCalls: 0,
      totalTokenBudget: 0,
    }))
  })

  it("submits typed coverage evidence for expert adjudication and refreshes the overview", async () => {
    const catalog = catalogPayload()
    Object.assign(catalog.rows[0], {
      source_text_hash: "sha256:source-text",
      base_resolution_fact_hashes: { positive: ["sha256:base-covered"] },
      active_resolution_facts: [
        { fact_hash: "sha256:base-covered", kind: "coverage_group", polarity: "positive" },
        { fact_hash: "sha256:previous-expert", kind: "expert_adjudication", polarity: "negative" },
      ],
      required_supersedes_fact_hashes: {
        covered: ["sha256:base-covered", "sha256:previous-expert"],
      },
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
      required_supersedes_fact_hashes: {
        covered: ["sha256:base-positive", "sha256:base-negative-a", "sha256:base-negative-b"],
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
      decision: "promote_to_claim",
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
        proposals: [], compat_omissions: [], total: 0, limit: 0, offset: 0,
        compat_omission_total: 0,
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

  it("resumes a pending structural operation with its server-restored identity", async () => {
    const catalog = catalogPayload()
    Object.assign(catalog, { catalog_generation_id: "sha256:catalog-generation" })
    Object.assign(catalog.rows[0], {
      resolution: "excluded",
      exclusion_kind: "structural",
      exclusion: { reason: "repeated_page_furniture" },
      pending_structural_operation: {
        operation_id: "CSOP-aaaa1111bbbb2222",
        lifecycle: "failed",
        checkpoints: ["audit_appended", "override_registered"],
        route_requested: "stub",
        route_model: null,
        route_config_revision: null,
        allow_llm: false,
        verifier_budget: {
          max_calls: 0,
          max_total_tokens: 0,
          attempted_calls: 0,
          failed_calls: 0,
          used_tokens: 0,
          reserved_tokens: 0,
          remaining_calls: 0,
          remaining_tokens: 0,
          usage_complete: true,
          unknown_remote_result: false,
        },
        needs_reconfirmation: false,
      },
    })
    const confirmClaimStructuralOverride = vi.fn().mockResolvedValue({
      ok: true,
      status: "rebuilt",
      operation_id: "CSOP-aaaa1111bbbb2222",
    })
    const client = makeClient({
      loadClaimCatalog: vi.fn().mockResolvedValue(catalog),
      confirmClaimStructuralOverride,
    })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.get('[data-testid="claim-row"]').trigger("click")
    await flushPromises()
    expect(wrapper.get('[data-testid="claim-structural-override"]').text())
      .toContain("恢复结构复核重建")
    expect(wrapper.get('[data-testid="claim-structural-mode"]').text())
      .toContain("确定性重建 · 0 LLM")
    expect(wrapper.find('[data-testid="claim-structural-paid-reconfirmation"]').exists())
      .toBe(false)

    await wrapper.get('textarea[aria-label="Claim 裁决理由"]').setValue("续跑中断的重建")
    await wrapper.get('[data-testid="claim-structural-override"]').trigger("click")
    await flushPromises()

    expect(confirmClaimStructuralOverride).toHaveBeenCalledWith(
      expect.objectContaining({
        operationId: "CSOP-aaaa1111bbbb2222",
        requestIdempotencyKey: "",
        allowLlm: false,
        route: "stub",
        verifierMaxCalls: 0,
        verifierMaxTotalTokens: 0,
      }),
    )
  })

  it("shows original paid authorization and requires explicit reconfirmation only when requested", async () => {
    const catalog = catalogPayload()
    Object.assign(catalog, { catalog_generation_id: "sha256:catalog-generation" })
    Object.assign(catalog.rows[0], {
      resolution: "excluded",
      exclusion_kind: "structural",
      exclusion: { reason: "repeated_page_furniture" },
      pending_structural_operation: {
        operation_id: "CSOP-paid1111bbbb22",
        lifecycle: "needs_reconfirmation",
        checkpoints: ["audit_appended", "override_registered"],
        route_requested: "openai_compatible",
        route_model: "deepseek-chat",
        route_config_revision: "sha256:route-1",
        allow_llm: true,
        verifier_budget: {
          max_calls: 4,
          max_total_tokens: 50000,
          attempted_calls: 1,
          failed_calls: 0,
          used_tokens: 12000,
          reserved_tokens: 8000,
          remaining_calls: 3,
          remaining_tokens: 30000,
          usage_complete: false,
          unknown_remote_result: true,
        },
        needs_reconfirmation: true,
      },
    })
    const confirmClaimStructuralOverride = vi.fn().mockRejectedValue(
      new Error("remote result remains unknown"),
    )
    const client = makeClient({
      loadClaimCatalog: vi.fn().mockResolvedValue(catalog),
      confirmClaimStructuralOverride,
    })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.get('[data-testid="claim-row"]').trigger("click")
    await flushPromises()
    const authorization = wrapper.get('[data-testid="claim-structural-pending-authorization"]').text()
    expect(authorization).toContain("deepseek-chat")
    expect(authorization).toContain("4 次 / 50,000 tokens")
    expect(authorization).toContain("1 次 / 12,000 tokens")
    expect(authorization).toContain("3 次 / 30,000 tokens")
    expect(authorization).toContain("8,000 tokens 远端结果未知")
    expect(authorization).not.toContain("0 LLM")

    await wrapper.get('textarea[aria-label="Claim 裁决理由"]').setValue("确认继续原付费操作")
    const command = wrapper.get('[data-testid="claim-structural-override"]')
    expect(command.attributes("disabled")).toBeDefined()
    await wrapper.get('[data-testid="claim-structural-paid-reconfirmation"]').setValue(true)
    expect(command.attributes("disabled")).toBeUndefined()
    await command.trigger("click")
    await flushPromises()

    expect(confirmClaimStructuralOverride).toHaveBeenCalledWith(expect.objectContaining({
      operationId: "CSOP-paid1111bbbb22",
      requestIdempotencyKey: "",
      allowLlm: true,
      route: "openai_compatible",
      verifierMaxCalls: 4,
      verifierMaxTotalTokens: 50000,
      reconfirmPaidWork: true,
    }))
    expect((wrapper.get('[data-testid="claim-structural-paid-reconfirmation"]')
      .element as HTMLInputElement).checked).toBe(false)
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

  it("paginates the proposal queue with an independent offset and a real total", async () => {
    const proposalPage = (offset: number, count: number) => ({
      ...queuePayload(),
      proposals: Array.from({ length: count }, (_, index) => ({
        ...queuePayload().proposals[0],
        proposal_id: `CQP-${String(offset + index).padStart(8, "0")}-00000000`,
        claim_id: `CLM-${String(offset + index).padStart(16, "0")}`,
      })),
      total: 30,
      limit: 25,
      offset,
    })
    const loadClaimQueue = vi.fn()
      .mockImplementation(({ offset = 0 } = {}) => Promise.resolve(
        proposalPage(offset, offset === 0 ? 25 : 5),
      ))
    const client = makeClient({ loadClaimQueue })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.findAll('[role="tab"]')[1].trigger("click")
    expect(loadClaimQueue).toHaveBeenLastCalledWith({
      limit: 25,
      offset: 0,
      compatLimit: 25,
      compatOffset: 0,
    })
    const pager = wrapper.get('[data-testid="claim-queue-pagination"]')
    expect(pager.text()).toContain("第 1 / 2 页")

    await pager.get('button[aria-label="队列下一页"]').trigger("click")
    await flushPromises()

    expect(loadClaimQueue).toHaveBeenLastCalledWith({
      limit: 25,
      offset: 25,
      compatLimit: 25,
      compatOffset: 0,
    })
    expect(wrapper.get('[data-testid="claim-queue-pagination"]').text()).toContain("第 2 / 2 页")
    expect(wrapper.text()).toContain("CLM-0000000000000029")
  })

  it("paginates compat omissions independently from claim proposals", async () => {
    const compatPage = (compatOffset: number, count: number) => ({
      ...queuePayload(),
      compat_omissions: Array.from({ length: count }, (_, index) => ({
        omission_id: `OM-${compatOffset + index}`,
        block_id: `BLK-${compatOffset + index}`,
        reason: "legacy omission",
        compat_whole_block: true as const,
        dry_run: true as const,
      })),
      compat_omission_total: 30,
      compat_omission_limit: 25,
      compat_omission_offset: compatOffset,
    })
    const loadClaimQueue = vi.fn()
      .mockImplementation(({ compatOffset = 0 } = {}) => Promise.resolve(
        compatPage(compatOffset, compatOffset === 0 ? 25 : 5),
      ))
    const client = makeClient({ loadClaimQueue })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.findAll('[role="tab"]')[1].trigger("click")
    const pager = wrapper.get('[data-testid="claim-compat-pagination"]')
    expect(pager.text()).toContain("第 1 / 2 页")
    await pager.get('button[aria-label="兼容遗漏下一页"]').trigger("click")
    await flushPromises()

    expect(loadClaimQueue).toHaveBeenLastCalledWith({
      limit: 25,
      offset: 0,
      compatLimit: 25,
      compatOffset: 25,
    })
    expect(wrapper.get('[data-testid="claim-compat-pagination"]').text())
      .toContain("第 2 / 2 页")
    expect(wrapper.text()).toContain("OM-29")
  })

  it("reloads open drawer details and gates adjudication on a revision switch", async () => {
    const revision1 = "sha256:revision-1"
    const revision2 = "sha256:revision-2"
    const catalog1 = catalogPayload(revision1)
    const catalog2 = catalogPayload(revision2)
    Object.assign(catalog2.rows[0], {
      required_supersedes_fact_hashes: { covered: ["sha256:fresh-fact"] },
    })
    const loadClaimCatalog = vi.fn()
      .mockResolvedValueOnce(catalog1)
      .mockResolvedValue(catalog2)
    const loadClaimMetrics = vi.fn()
      .mockResolvedValueOnce(metricsPayload(revision1))
      .mockResolvedValue(metricsPayload(revision2))
    const loadClaimQueue = vi.fn()
      .mockResolvedValueOnce(queuePayload(revision1))
      .mockResolvedValue(queuePayload(revision2))
    const deferred: { release?: (value: unknown) => void } = {}
    const loadClaimCoverageGroups = vi.fn()
      .mockResolvedValueOnce(groupsPayload(revision1, "STALE-GROUP"))
      .mockImplementationOnce(() => new Promise((resolve) => {
        deferred.release = resolve
      }))
      .mockResolvedValue(groupsPayload(revision2, "FRESH-GROUP"))
    const loadClaimReviewEvents = vi.fn()
      .mockResolvedValueOnce(eventsPayload(revision1))
      .mockResolvedValue(eventsPayload(revision2))
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
    expect(wrapper.get('[data-testid="claim-detail"]').text()).toContain("STALE-GROUP")

    await wrapper.get('textarea[aria-label="Claim 裁决理由"]').setValue("版本切换探针")
    await wrapper.get('[data-testid="claim-refresh"]').trigger("click")
    await flushPromises()

    // The drawer shows the new row immediately but old details are cleared and
    // adjudication is gated until same-revision details arrive.
    const midSwitch = wrapper.get('[data-testid="claim-detail"]').text()
    expect(midSwitch).toContain("sha256:revision-2-claim")
    expect(midSwitch).not.toContain("STALE-GROUP")
    expect(midSwitch).toContain("加载同代详情")
    expect(wrapper.find('[data-testid="claim-adjudicate-covered"]').exists()).toBe(false)

    deferred.release?.(groupsPayload(revision2, "FRESH-GROUP"))
    await flushPromises()

    const settled = wrapper.get('[data-testid="claim-detail"]').text()
    expect(settled).toContain("FRESH-GROUP")
    expect(settled).not.toContain("STALE-GROUP")
    expect(wrapper.get('[data-testid="claim-adjudicate-covered"]').attributes("disabled")).toBeUndefined()
    // The adjudication draft survives the 409-style revision refresh.
    expect((wrapper.get('textarea[aria-label="Claim 裁决理由"]').element as HTMLTextAreaElement).value)
      .toBe("版本切换探针")
  })

  it("converges through a two-step revision drift R1->R2->R3 and keeps the draft", async () => {
    const revision1 = "sha256:revision-1"
    const revision2 = "sha256:revision-2"
    const revision3 = "sha256:revision-3"
    const loadClaimCatalog = vi.fn()
      .mockResolvedValueOnce(catalogPayload(revision1))
      .mockResolvedValueOnce(catalogPayload(revision2))
      .mockResolvedValueOnce(catalogPayload(revision3))
    const loadClaimMetrics = vi.fn()
      .mockResolvedValueOnce(metricsPayload(revision1))
      .mockResolvedValueOnce(metricsPayload(revision2))
      .mockResolvedValueOnce(metricsPayload(revision3))
    const loadClaimQueue = vi.fn()
      .mockResolvedValueOnce(queuePayload(revision1))
      .mockResolvedValueOnce(queuePayload(revision2))
      .mockResolvedValueOnce(queuePayload(revision3))
    // The server is already at R3 while the drawer opens at R1: groups come back at
    // R3 twice (discarded against R1 then R2) before the overview catches up to R3.
    const loadClaimCoverageGroups = vi.fn()
      .mockResolvedValueOnce(groupsPayload(revision3, "STALE3"))
      .mockResolvedValueOnce(groupsPayload(revision3, "STALE3"))
      .mockResolvedValueOnce(groupsPayload(revision3, "FRESH3"))
    const loadClaimReviewEvents = vi.fn()
      .mockResolvedValueOnce(eventsPayload(revision3))
      .mockResolvedValueOnce(eventsPayload(revision3))
      .mockResolvedValueOnce(eventsPayload(revision3))
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
    await wrapper.get('textarea[aria-label="Claim 裁决理由"]').setValue("收敛探针")
    await flushPromises()

    const detail = wrapper.get('[data-testid="claim-detail"]').text()
    expect(detail).toContain("FRESH3")
    expect(detail).not.toContain("STALE3")
    // Bounded budget: a two-step drift converges in exactly three detail fetches.
    expect(loadClaimCoverageGroups).toHaveBeenCalledTimes(3)
    expect((wrapper.get('textarea[aria-label="Claim 裁决理由"]').element as HTMLTextAreaElement).value)
      .toBe("收敛探针")
  })

  it("converges an already-open drawer through passive R1->R2->R3 refresh", async () => {
    const revision1 = "sha256:revision-1"
    const revision2 = "sha256:revision-2"
    const revision3 = "sha256:revision-3"
    const loadClaimCatalog = vi.fn()
      .mockResolvedValueOnce(catalogPayload(revision1))
      .mockResolvedValueOnce(catalogPayload(revision2))
      .mockResolvedValueOnce(catalogPayload(revision3))
    const loadClaimMetrics = vi.fn()
      .mockResolvedValueOnce(metricsPayload(revision1))
      .mockResolvedValueOnce(metricsPayload(revision2))
      .mockResolvedValueOnce(metricsPayload(revision3))
    const loadClaimQueue = vi.fn()
      .mockResolvedValueOnce(queuePayload(revision1))
      .mockResolvedValueOnce(queuePayload(revision2))
      .mockResolvedValueOnce(queuePayload(revision3))
    const loadClaimCoverageGroups = vi.fn()
      .mockResolvedValueOnce(groupsPayload(revision1, "INITIAL-R1"))
      .mockResolvedValueOnce(groupsPayload(revision3, "STALE-R3"))
      .mockResolvedValueOnce(groupsPayload(revision3, "FRESH-R3"))
    const loadClaimReviewEvents = vi.fn()
      .mockResolvedValueOnce(eventsPayload(revision1))
      .mockResolvedValueOnce(eventsPayload(revision3))
      .mockResolvedValueOnce(eventsPayload(revision3))
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
    expect(wrapper.get('[data-testid="claim-detail"]').text()).toContain("INITIAL-R1")
    await wrapper.get('textarea[aria-label="Claim 裁决理由"]').setValue("被动收敛草稿")

    await wrapper.get('[data-testid="claim-refresh"]').trigger("click")
    await flushPromises()

    const detail = wrapper.get('[data-testid="claim-detail"]').text()
    expect(detail).toContain("FRESH-R3")
    expect(detail).not.toContain("INITIAL-R1")
    expect(detail).not.toContain("STALE-R3")
    expect(loadClaimCoverageGroups).toHaveBeenCalledTimes(3)
    expect((wrapper.get('textarea[aria-label="Claim 裁决理由"]').element as HTMLTextAreaElement).value)
      .toBe("被动收敛草稿")
  })

  it("stops bounded refresh on persistent drift and keeps structural mutation gated", async () => {
    const revision1 = "sha256:revision-1"
    const catalog2 = catalogPayload("sha256:revision-2")
    Object.assign(catalog2.rows[0], {
      resolution: "excluded",
      exclusion_kind: "structural",
      exclusion: { reason: "repeated_page_furniture" },
    })
    const loadClaimCatalog = vi.fn()
      .mockResolvedValueOnce(catalogPayload(revision1))
      .mockResolvedValue(catalog2)
    const loadClaimMetrics = vi.fn()
      .mockResolvedValueOnce(metricsPayload(revision1))
      .mockResolvedValue(metricsPayload("sha256:revision-2"))
    const loadClaimQueue = vi.fn()
      .mockResolvedValueOnce(queuePayload(revision1))
      .mockResolvedValue(queuePayload("sha256:revision-2"))
    // The server always answers details at a revision newer than the pinned one, so
    // the drawer can never converge — it must stop at the bounded budget and stay stale.
    const loadClaimCoverageGroups = vi.fn().mockImplementation(({ revision }) =>
      Promise.resolve(groupsPayload(`${revision}-drift`, "DRIFT")),
    )
    const loadClaimReviewEvents = vi.fn().mockImplementation(({ revision }) =>
      Promise.resolve(eventsPayload(`${revision}-drift`)),
    )
    const confirmClaimStructuralOverride = vi.fn().mockResolvedValue({
      ok: true,
      status: "rebuilt",
      effective_fresh: true,
    })
    const client = makeClient({
      loadClaimCatalog,
      loadClaimMetrics,
      loadClaimQueue,
      loadClaimCoverageGroups,
      loadClaimReviewEvents,
      confirmClaimStructuralOverride,
    })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    await wrapper.get('[data-testid="claim-row"]').trigger("click")
    await flushPromises()

    // Persistent drift is bounded: at most DETAIL_REFRESH_BUDGET+1 detail fetches, and
    // the drawer never shows the never-converging DRIFT group.
    expect(loadClaimCoverageGroups).toHaveBeenCalledTimes(3)
    expect(wrapper.get('[data-testid="claim-detail"]').text()).not.toContain("DRIFT")
    // Details stay stale, so the structural mutation button stays disabled and the
    // handler gate keeps the mutation API unreached even on a forced click.
    const structuralBtn = wrapper.get('[data-testid="claim-structural-override"]')
    expect(structuralBtn.attributes("disabled")).toBeDefined()
    await structuralBtn.trigger("click")
    await flushPromises()
    expect(confirmClaimStructuralOverride).not.toHaveBeenCalled()
  })

  it("shows structural review badges and can confirm a cell exclusion without LLM", async () => {
    const pending = catalogPayload() as any
    pending.catalog_generation_id = "sha256:catalog-generation"
    Object.assign(pending.rows[0], {
      eligibility: "excluded",
      resolution: "excluded",
      classification: "non_normative",
      exclusion_kind: "structural",
      exclusion: { reason: "untyped_colon_spec_cell" },
      structural_review_status: "pending_review",
      structural_candidate_decision: null,
    })
    const confirmed = structuredClone(pending)
    Object.assign(confirmed.rows[0], {
      structural_review_status: "confirmed_excluded",
      structural_candidate_decision: {
        decision_id: "CSCD-1111111111111111",
        decision: "confirm_exclusion",
        actor: "reviewer",
        reason: "确认该冒号规格属于上下文",
        recorded_at: "2026-08-01T12:00:00Z",
      },
    })
    const loadClaimCatalog = vi.fn()
      .mockResolvedValueOnce(pending)
      .mockResolvedValue(confirmed)
    const confirmClaimStructuralOverride = vi.fn().mockResolvedValue({
      ok: true,
      status: "confirmed_excluded",
      appended: true,
    })
    const client = makeClient({
      loadClaimCatalog,
      confirmClaimStructuralOverride,
    })
    const wrapper = mount(ClaimLedger, { props: { client, active: true } })
    await flushPromises()

    expect(wrapper.get('[data-testid="claim-structural-list-status"]').text())
      .toContain("结构待审")
    await wrapper.get('[data-testid="claim-row"]').trigger("click")
    await flushPromises()
    await wrapper.get('textarea[aria-label="Claim 裁决理由"]')
      .setValue("确认该冒号规格属于上下文")
    await wrapper.get('[data-testid="claim-structural-confirm-exclusion"]').trigger("click")
    await flushPromises()

    expect(confirmClaimStructuralOverride).toHaveBeenCalledWith(expect.objectContaining({
      priorStructuralReason: "untyped_colon_spec_cell",
      decision: "confirm_exclusion",
      allowLlm: false,
      route: "stub",
      verifierMaxCalls: 0,
      verifierMaxTotalTokens: 0,
    }))
    expect(wrapper.get('[data-testid="claim-structural-list-status"]').text())
      .toContain("已确认排除")
    await wrapper.get('[data-testid="claim-row"]').trigger("click")
    await flushPromises()
    expect(wrapper.get('[data-testid="claim-structural-confirmed-exclusion"]').text())
      .toContain("确认该冒号规格属于上下文")
  })
})
