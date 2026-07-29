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
      dry_run: true as const,
      claim_effective_revision: `${revision}-queue`,
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
    loadAiExtractionStatus: vi.fn().mockResolvedValue({
      schema: "ai-requirements-partial/v1",
      run_id: "run-1", completed: 1, total: 1, complete: true, rows: [],
      quality: { coverage_pct: 82.5, core_coverage_pct: 75 },
    }),
    ...overrides,
  }
}

describe("ClaimLedger", () => {
  it("renders revision-pinned metrics, comparison, claims, and read-only dry-run queues", async () => {
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
    expect(wrapper.get('[data-testid="claim-queue"]').findAll("button")).toHaveLength(0)
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
