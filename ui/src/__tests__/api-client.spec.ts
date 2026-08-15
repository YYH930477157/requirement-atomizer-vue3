import { describe, expect, it, vi } from "vitest"
import {
  RequirementApiClient,
  RequirementApiError,
  isClaimRecoveryPendingError,
  isNeedsReconfirmationError,
} from "../api-client"
import { runDesktopTask } from "../desktop-bridge"

describe("RequirementApiClient", () => {
  it("loads requirements with the local API token", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{ stable_req_id: "SREQ-1" }],
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770",
      token: "local-token",
      fetchImpl: fetchMock,
    })

    const rows = await client.loadRequirements()

    expect(rows).toEqual([{ stable_req_id: "SREQ-1" }])
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8770/requirements?limit=5000", {
      headers: { "X-Requirement-Atomizer-Token": "local-token" },
    })
  })

  it("loads the source manifest for restored run context", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ input: "C:\\input\\standard.docx", counts: { blocks: 3 } }),
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770/",
      token: "local-token",
      fetchImpl: fetchMock,
    })

    await expect(client.loadManifest()).resolves.toEqual({
      input: "C:\\input\\standard.docx",
      counts: { blocks: 3 },
    })
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8770/manifest", {
      headers: { "X-Requirement-Atomizer-Token": "local-token" },
    })
  })

  it("requests explicit package verification with verify=1 (S5)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ layout: "package_v1", package: null }),
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770",
      token: "local-token",
      fetchImpl: fetchMock,
    })

    await client.loadResultPackage({ verify: true })

    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8770/result-package?verify=1", {
      headers: { "X-Requirement-Atomizer-Token": "local-token" },
    })
  })

  it("posts review actions with reason and actor", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ requirement_id: "SREQ-1", status: "accepted" }),
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770/",
      token: "local-token",
      fetchImpl: fetchMock,
    })

    const state = await client.applyReviewAction({
      requirementId: "SREQ-1",
      status: "accepted",
      actor: "reviewer",
      reason: "accepted in Vue3 UI",
      expectedTargetFingerprint: "sha256:target-v1",
      expectedTargetPublicationRevision: "sha256:publication-v1",
      expectedTargetAuthorityWriteRevision: "sha256:authority-v1",
    })

    expect(state.status).toBe("accepted")
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8770/review-actions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requirement-Atomizer-Token": "local-token",
      },
      body: JSON.stringify({
        requirement_id: "SREQ-1",
        status: "accepted",
        actor: "reviewer",
        reason: "accepted in Vue3 UI",
        expected_target_fingerprint: "sha256:target-v1",
        expected_target_publication_revision: "sha256:publication-v1",
        expected_target_authority_write_revision: "sha256:authority-v1",
      }),
    })
  })

  it("loads table reviews and posts one table-scoped role decision", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          schema: "table-review-view/v1",
          tables: [{ table_id: "TBL-1", structure_review_status: "pending" }],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          table_id: "TBL-1",
          structure_review_status: "ready",
        }),
      })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770/",
      token: "local-token",
      fetchImpl: fetchMock,
    })

    await expect(client.loadTableReviews()).resolves.toMatchObject({
      schema: "table-review-view/v1",
    })
    await client.applyTableReviewAction({
      tableId: "TBL-1",
      expectedEvidenceFingerprint: "sha256:evidence-v1",
      roleMapping: {
        "TBL-1-R000001-C000001": {
          role: "row_header",
          disposition: "context",
        },
      },
      actor: "reviewer",
      reason: "Confirmed table regions",
    })

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8770/table-reviews", {
      headers: { "X-Requirement-Atomizer-Token": "local-token" },
    })
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8770/table-review-actions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requirement-Atomizer-Token": "local-token",
      },
      body: JSON.stringify({
        table_id: "TBL-1",
        expected_evidence_fingerprint: "sha256:evidence-v1",
        role_mapping: {
          "TBL-1-R000001-C000001": {
            role: "row_header",
            disposition: "context",
          },
        },
        actor: "reviewer",
        reason: "Confirmed table regions",
      }),
    })
  })

  it("posts requirement text for translation", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        requirement_id: "SREQ-1",
        translation: "读取客户端应支持 xDLMS 服务：使用 GET 的块传输。",
      }),
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770/",
      token: "local-token",
      fetchImpl: fetchMock,
    })

    const payload = await client.translateRequirement({
      requirementId: "SREQ-1",
      text: 'Reading client shall support xDLMS Service: Block transfer with "GET".',
      context: "Reading client",
    })

    expect(payload.translation).toBe("读取客户端应支持 xDLMS 服务：使用 GET 的块传输。")
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8770/translations", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requirement-Atomizer-Token": "local-token",
      },
      body: JSON.stringify({
        requirement_id: "SREQ-1",
        text: 'Reading client shall support xDLMS Service: Block transfer with "GET".',
        context: "Reading client",
      }),
    })
  })

  it("calls browser fetch with the window/global receiver", async () => {
    const fetchMock = vi.fn(function (this: unknown) {
      if (this !== globalThis) {
        throw new TypeError("Illegal invocation")
      }
      return Promise.resolve({
        ok: true,
        json: async () => [{ stable_req_id: "SREQ-1" }],
      })
    }) as unknown as typeof fetch
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770",
      token: "local-token",
      fetchImpl: fetchMock,
    })

    await expect(client.loadRequirements()).resolves.toEqual([{ stable_req_id: "SREQ-1" }])
  })

  it("loads incremental extraction status and omission states", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          schema: "ai-requirements-partial/v1", run_id: "run-1",
          completed: 2, total: 5, complete: false, rows: [{ ai_req_id: "AIR-1" }],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ schema: "omission-actions/v1", states: [] }),
      })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "local-token", fetchImpl: fetchMock,
    })

    await expect(client.loadAiExtractionStatus()).resolves.toMatchObject({ completed: 2, total: 5 })
    await expect(client.loadOmissionActions()).resolves.toEqual({ schema: "omission-actions/v1", states: [] })
    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8770/ai-extraction-status", {
      headers: { "X-Requirement-Atomizer-Token": "local-token" },
    })
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8770/omission-actions", {
      headers: { "X-Requirement-Atomizer-Token": "local-token" },
    })
  })

  it("posts omission triage and targeted re-extraction actions", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ omission_id: "OM-B3", block_id: "B3", status: "needs_extraction" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          schema: "omission-reextract/v1", omission: {}, supplement: {},
          requirements: 1, effective_count: 2, written: ["ai_supplements.jsonl"],
        }),
      })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "local-token", fetchImpl: fetchMock,
    })

    await client.applyOmissionAction({
      omissionId: "OM-B3", blockId: "B3", sourceFingerprint: "source-B3", status: "needs_extraction",
      reason: "规范性语句", actor: "reviewer",
    })
    await client.reextractOmission({
      omissionId: "OM-B3", blockId: "B3", sourceFingerprint: "source-B3",
      focusLines: ["The meter shall hold."],
      actor: "reviewer", reason: "确认遗漏", route: "openai_compatible",
    })

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8770/omission-actions", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        omission_id: "OM-B3", block_id: "B3", source_fingerprint: "source-B3", status: "needs_extraction",
        reason: "规范性语句", actor: "reviewer",
      }),
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8770/omission-reextract", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        omission_id: "OM-B3", block_id: "B3", source_fingerprint: "source-B3",
        focus_lines: ["The meter shall hold."],
        actor: "reviewer", reason: "确认遗漏", route: "openai_compatible",
      }),
    }))
  })

  it("posts spot extraction for a single block or table row", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          schema: "spot-extract/v1", block_id: "BLK-T1", row_index: 2,
          strategy: "deterministic_param_row", drafts: 1, draft_ids: ["SPOT-BLK-T1-R2"],
          already_covered: false, written: ["ai_requirements.jsonl"],
        }),
      })
      .mockResolvedValueOnce({
        ok: false, status: 503,
        json: async () => ({ ok: false, error: "openai_compatible route is not configured" }),
      })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "local-token", fetchImpl: fetchMock,
    })

    const payload = await client.spotExtract({ blockId: "BLK-T1", rowIndex: 2, actor: "reviewer" })
    expect(payload.draft_ids).toEqual(["SPOT-BLK-T1-R2"])
    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8770/spot-extract", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        block_id: "BLK-T1", row_index: 2, cell_id: null, actor: "reviewer", reason: "", route: "",
      }),
    }))

    // LLM 不可用：503 + ok:false → 抛出带真实后端原因的错误（按钮不假装可用）
    await expect(client.spotExtract({ blockId: "B2" })).rejects.toMatchObject({
      status: 503, message: "openai_compatible route is not configured",
    })
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8770/spot-extract", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        block_id: "B2", row_index: null, cell_id: null, actor: "", reason: "", route: "",
      }),
    }))
  })

  it("posts spot extraction for a single table cell with dual-header context", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        schema: "spot-extract/v1", block_id: "BLK-T1", row_index: 1,
        cell_id: "TBL-000001-R000002-C000002",
        strategy: "llm", drafts: 1, draft_ids: ["SPOT-BLK-T1"],
        already_covered: false, written: ["ai_requirements.jsonl"],
      }),
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "local-token", fetchImpl: fetchMock,
    })

    const payload = await client.spotExtract({
      blockId: "BLK-T1", cellId: "TBL-000001-R000002-C000002", actor: "reviewer",
    })
    expect(payload.cell_id).toBe("TBL-000001-R000002-C000002")
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8770/spot-extract", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        block_id: "BLK-T1", row_index: null, cell_id: "TBL-000001-R000002-C000002",
        actor: "reviewer", reason: "", route: "",
      }),
    }))
  })

  it("loads and batch acknowledges internal checks with evidence fingerprints", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          schema: "clarification-internal-checks/v1", total: 1, unresolved: 1,
          entries: [{ clarification_id: "CLR-1", evidence_fingerprint: "FP-1" }], groups: [],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ requested: 1, applied: 1, stale: [], missing: [] }),
      })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "local-token", fetchImpl: fetchMock,
    })

    await client.loadClarificationInternalChecks()
    await client.applyClarificationCheckBatch({
      checks: [{ clarificationId: "CLR-1", evidenceFingerprint: "FP-1" }],
      action: "verified_ok", actor: "reviewer", note: "逐项核对完成",
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8770/clarification-check-actions/batch",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          checks: [{ clarification_id: "CLR-1", evidence_fingerprint: "FP-1" }],
          action: "verified_ok", actor: "reviewer", note: "逐项核对完成",
        }),
      }),
    )
  })

  it("binds AI decisions to the displayed source and subject fingerprints", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ai_req_id: "AIR-1", status: "accepted" }),
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "local-token", fetchImpl: fetchMock,
    })

    await client.applyAiReviewAction({
      aiReqId: "AIR-1", status: "accepted",
      sourceFingerprint: "source-v2", reviewSubjectFingerprint: "subject-v2",
      expectedTargetFingerprint: "sha256:target-v2",
      expectedTargetPublicationRevision: "sha256:publication-v2",
      expectedTargetAuthorityWriteRevision: "sha256:authority-v2",
    })

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8770/ai-review-actions",
      expect.objectContaining({
        body: JSON.stringify({
          ai_req_id: "AIR-1", status: "accepted",
          source_fingerprint: "source-v2", review_subject_fingerprint: "subject-v2",
          expected_target_fingerprint: "sha256:target-v2",
          expected_target_publication_revision: "sha256:publication-v2",
          expected_target_authority_write_revision: "sha256:authority-v2",
          clear_module_override: false, ownership_override: "", reason: "", actor: "",
        }),
      }),
    )
  })

  it("uses an explicit flag to clear a module override", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ai_req_id: "AIR-1", status: "accepted", module_override: null }),
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "local-token", fetchImpl: fetchMock,
    })

    await client.applyAiReviewAction({
      aiReqId: "AIR-1", status: "accepted", clearModuleOverride: true,
    })

    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(body).not.toHaveProperty("module_override")
    expect(body.clear_module_override).toBe(true)
  })

  it("preserves structured 409 reconfirmation details", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        error: "AI requirement changed; refresh before adjudicating",
        needs_reconfirmation: true,
        source_fingerprint: "source-v2",
      }),
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "local-token", fetchImpl: fetchMock,
    })

    const error = await client.applyAiReviewAction({ aiReqId: "AIR-1", status: "accepted" })
      .catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(RequirementApiError)
    expect(isNeedsReconfirmationError(error)).toBe(true)
    expect((error as RequirementApiError).status).toBe(409)
    expect((error as RequirementApiError).details.source_fingerprint).toBe("source-v2")
  })

  it("loads all six read-only claim views with filters and revision envelopes", async () => {
    const claimEnvelope = {
      schema: "claim-view/v1",
      available: true,
      phase: "production-dual-write-v1",
      document_effective_revision: "sha256:effective-1",
      base_generation_id: "sha256:base-1",
      event_prefix_sha256: "sha256:events-1",
      effective_fresh: true,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => claimEnvelope,
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "local-token", fetchImpl: fetchMock,
    })

    await client.loadClaimCatalog({ resolution: "covered", ownerUnitId: "UNIT-1", limit: 10, offset: 20 })
    await client.loadClaimLedger({ resolution: "uncertain", limit: 5, offset: 15 })
    await client.loadClaimCoverageGroups("CLM-1/2")
    await client.loadClaimMetrics()
    await client.loadClaimReviewEvents("CLM-1/2")
    await client.loadClaimQueue()

    const urls = fetchMock.mock.calls.map((call) => call[0])
    expect(urls).toEqual([
      "http://127.0.0.1:8770/claim-catalog?limit=10&offset=20&resolution=covered&owner_unit_id=UNIT-1",
      "http://127.0.0.1:8770/claim-ledger?limit=5&offset=15&resolution=uncertain",
      "http://127.0.0.1:8770/claim-coverage-groups?claim_id=CLM-1%2F2&limit=100&offset=0",
      "http://127.0.0.1:8770/claim-metrics",
      "http://127.0.0.1:8770/claim-review-events?claim_id=CLM-1%2F2&limit=100&offset=0",
      "http://127.0.0.1:8770/claim-queue?limit=100&offset=0&compat_limit=100&compat_offset=0",
    ])
    for (const [, init] of fetchMock.mock.calls) {
      expect(init).toEqual({ headers: { "X-Requirement-Atomizer-Token": "local-token" } })
    }
  })

  it("posts complete Queue v2, expert adjudication, and structural override contracts", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          schema: "claim-queue-execution/v1", proposal_id: "CQP-1", attempt_id: "CRA-1",
          lifecycle: "executed",
        }),
      })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "local-token", fetchImpl: fetchMock,
    })

    await client.executeClaimQueue({
      proposalId: "CQP-1",
      expectedClaimEffectiveRevision: "sha256:claim-revision-1",
      actor: "queue-reviewer",
      allowLlm: true,
      route: "deepseek",
      maximumCalls: 6,
      totalTokenBudget: 72000,
      requestIdempotencyKey: "queue-request-1",
      expectedRouteConfigRevision: "sha256:queue-route-config-1",
    })
    await client.applyClaimAdjudication({
      claimId: "CLM-1",
      claimHash: "sha256:claim-1",
      adjudication: "covered",
      reason: "validated against the active requirement",
      evidence: {
        kind: "coverage_group",
        coverage_group_id: "CGR-1",
        coverage_group_hash: "sha256:group-1",
      },
      actor: "expert-reviewer",
      expectedClaimEffectiveRevision: "sha256:claim-revision-2",
      supersedesFactHashes: ["sha256:fact-1", "sha256:fact-2"],
      requestIdempotencyKey: "adjudication-request-1",
    })
    await client.confirmClaimStructuralOverride({
      claimId: "CLM-2",
      claimHash: "sha256:claim-2",
      expectedCatalogGenerationId: "sha256:catalog-1",
      expectedClaimEffectiveRevision: "sha256:claim-revision-3",
      priorStructuralReason: "repeated_page_furniture",
      decision: "promote_to_claim",
      reason: "confirmed as document content",
      actor: "structural-reviewer",
      requestIdempotencyKey: "structural-request-1",
      allowLlm: true,
      route: "openai_compatible",
      verifierMaxCalls: 2,
      verifierMaxTotalTokens: 12000,
      reconfirmPaidWork: true,
    })

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8770/claim-queue/execute", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requirement-Atomizer-Token": "local-token",
      },
      body: JSON.stringify({
        proposal_id: "CQP-1",
        expected_claim_effective_revision: "sha256:claim-revision-1",
        expected_ledger_state: "uncertain",
        actor: "queue-reviewer",
        allow_llm: true,
        route: "deepseek",
        maximum_calls: 6,
        total_token_budget: 72000,
        request_idempotency_key: "queue-request-1",
        expected_route_config_revision: "sha256:queue-route-config-1",
      }),
    })
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8770/claim-adjudications", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requirement-Atomizer-Token": "local-token",
      },
      body: JSON.stringify({
        claim_id: "CLM-1",
        claim_hash: "sha256:claim-1",
        adjudication: "covered",
        reason: "validated against the active requirement",
        evidence: {
          kind: "coverage_group",
          coverage_group_id: "CGR-1",
          coverage_group_hash: "sha256:group-1",
        },
        actor: "expert-reviewer",
        expected_claim_effective_revision: "sha256:claim-revision-2",
        supersedes_fact_hashes: ["sha256:fact-1", "sha256:fact-2"],
        request_idempotency_key: "adjudication-request-1",
      }),
    })
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://127.0.0.1:8770/claim-structural-overrides", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requirement-Atomizer-Token": "local-token",
      },
      body: JSON.stringify({
        claim_id: "CLM-2",
        claim_hash: "sha256:claim-2",
        expected_catalog_generation_id: "sha256:catalog-1",
        expected_claim_effective_revision: "sha256:claim-revision-3",
        prior_structural_reason: "repeated_page_furniture",
        decision: "promote_to_claim",
        reason: "confirmed as document content",
        actor: "structural-reviewer",
        request_idempotency_key: "structural-request-1",
        allow_llm: true,
        route: "openai_compatible",
        verifier_max_calls: 2,
        verifier_max_total_tokens: 12000,
        reconfirm_paid_work: true,
      }),
    })
  })

  it("serializes queue LLM authorization from the caller instead of granting it implicitly", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        schema: "claim-queue-execution/v1", proposal_id: "CQP-1", attempt_id: "CRA-1",
        lifecycle: "rebuild_pending",
      }),
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "local-token", fetchImpl: fetchMock,
    })

    await client.executeClaimQueue({
      proposalId: "CQP-1",
      expectedClaimEffectiveRevision: "sha256:claim-revision-1",
      allowLlm: false,
      route: "stub",
      maximumCalls: 0,
      totalTokenBudget: 0,
      requestIdempotencyKey: "queue-recovery-1",
    })

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      allow_llm: false,
      route: "stub",
      maximum_calls: 0,
      total_token_budget: 0,
    })
  })

  it("rejects a claim view that omits its effective revision pin", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ schema: "claim-metrics-view/v1", available: true }),
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "local-token", fetchImpl: fetchMock,
    })

    await expect(client.loadClaimMetrics()).rejects.toMatchObject({
      status: 502,
      message: "Claim ledger response is missing document_effective_revision",
    })
  })

  it("accepts the null revision envelope for a legacy directory without a ledger", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        schema: "claim-metrics-view/v1",
        available: false,
        phase: "production-dual-write-v1",
        document_effective_revision: null,
        base_generation_id: null,
        event_prefix_sha256: null,
        effective_fresh: false,
        reason: "当前输出目录尚无 Claim Ledger generation",
      }),
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "local-token", fetchImpl: fetchMock,
    })

    await expect(client.loadClaimMetrics()).resolves.toMatchObject({
      available: false,
      document_effective_revision: null,
    })
  })
})

describe("RequirementApiClient claim-maintenance auto-recovery", () => {
  const recoveryPending = {
    ok: false,
    status: 503,
    json: async () => ({
      error: "effective_recovery_pending",
      detail: "claim effective snapshot recovery is pending",
      retryable: true,
    }),
  }

  const claimEnvelope = {
    schema: "claim-metrics-view/v1",
    available: true,
    phase: "production-dual-write-v1",
    document_effective_revision: "sha256:effective-1",
    base_generation_id: "sha256:base-1",
    event_prefix_sha256: "sha256:events-1",
    effective_fresh: true,
  }

  it("recovers a GET by posting /claim-maintenance once and replaying the request", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(recoveryPending)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) })
      .mockResolvedValueOnce({ ok: true, json: async () => claimEnvelope })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "local-token", fetchImpl: fetchMock,
    })

    await expect(client.loadClaimMetrics()).resolves.toMatchObject({
      document_effective_revision: "sha256:effective-1",
    })

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "http://127.0.0.1:8770/claim-metrics",
      "http://127.0.0.1:8770/claim-maintenance",
      "http://127.0.0.1:8770/claim-metrics",
    ])
    expect(fetchMock.mock.calls[1][1]).toEqual({
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requirement-Atomizer-Token": "local-token",
      },
      body: "{}",
    })
    // 重放的是原始 GET（无 method）
    expect(fetchMock.mock.calls[2][1]).toEqual({
      headers: { "X-Requirement-Atomizer-Token": "local-token" },
    })
  })

  it("accepts the nested {error:{code}} envelope shape", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 503,
        json: async () => ({
          error: { code: "claim_artifact_recovery_required" },
          retryable: true,
        }),
      })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) })
      .mockResolvedValue({ ok: true, json: async () => [{ stable_req_id: "SREQ-1" }] })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "", fetchImpl: fetchMock,
    })

    await expect(client.loadRequirements()).resolves.toEqual([{ stable_req_id: "SREQ-1" }])
    expect(fetchMock.mock.calls[1][0]).toBe("http://127.0.0.1:8770/claim-maintenance")
  })

  it("shares one maintenance POST across concurrent failing GETs", async () => {
    let recovered = false
    const maintenanceCalls: number[] = []
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/claim-maintenance")) {
        maintenanceCalls.push(1)
        expect(recovered).toBe(false)
        recovered = true
        return Promise.resolve({ ok: true, json: async () => ({ ok: true }) })
      }
      if (!recovered) {
        return Promise.resolve({
          ok: false,
          status: 503,
          json: async () => ({
            error: "effective_recovery_pending",
            retryable: true,
          }),
        })
      }
      return Promise.resolve({ ok: true, json: async () => claimEnvelope })
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770",
      token: "t",
      fetchImpl: fetchMock as unknown as typeof fetch,
    })

    const [first, second] = await Promise.all([
      client.loadClaimMetrics(),
      client.loadClaimMetrics(),
    ])

    expect(first).toMatchObject({ available: true })
    expect(second).toMatchObject({ available: true })
    expect(maintenanceCalls).toHaveLength(1)
    expect(fetchMock.mock.calls.filter((call) => call[0].endsWith("/claim-metrics"))).toHaveLength(4)
  })

  it("does not re-trigger maintenance for a slow GET whose 503 predates a completed recovery", async () => {
    // 时间线：GET-A（慢）在维护开始前派发 → GET-B（快）命中 503 触发维护并恢复 →
    // GET-A 这才带着旧 503 返回。世代已前进：A 不再触发第二个维护 POST，只重放一次并成功。
    // （否则 180ms 轮询下每个迟到的旧 503 都会重复昂贵的恢复/fold 操作。）
    let maintenanceCalls = 0
    let metricsCalls = 0
    let releaseSlowGet: () => void = () => {}
    const slowGet = new Promise<void>((resolve) => {
      releaseSlowGet = resolve
    })
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/claim-maintenance")) {
        maintenanceCalls += 1
        return Promise.resolve({ ok: true, json: async () => ({ ok: true }) })
      }
      metricsCalls += 1
      if (metricsCalls === 1) {
        // GET-A 首发：挂起，待恢复完成后才交付旧 503
        return slowGet.then(() => ({
          ok: false,
          status: 503,
          json: async () => ({ error: "effective_recovery_pending", retryable: true }),
        }))
      }
      if (metricsCalls === 2) {
        // GET-B 首发：立刻 503（此刻尚无恢复 → 触发维护）
        return Promise.resolve({
          ok: false,
          status: 503,
          json: async () => ({ error: "effective_recovery_pending", retryable: true }),
        })
      }
      // 重放（GET-B 与 GET-A 各一次）：恢复后的新服务端视图 → 成功
      return Promise.resolve({ ok: true, json: async () => claimEnvelope })
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770",
      token: "t",
      fetchImpl: fetchMock as unknown as typeof fetch,
    })

    const slowPromise = client.loadClaimMetrics()
    const fastPromise = client.loadClaimMetrics()
    await expect(fastPromise).resolves.toMatchObject({ available: true })
    expect(maintenanceCalls).toBe(1)

    releaseSlowGet()
    await expect(slowPromise).resolves.toMatchObject({ available: true })
    // 旧 503 迟到：不再有第二个维护 POST，但 GET-A 仍重放了一次并成功
    expect(maintenanceCalls).toBe(1)
    expect(fetchMock.mock.calls.filter((call) => call[0].endsWith("/claim-metrics"))).toHaveLength(4)
  })

  it("triggers maintenance again for a fresh 503 dispatched after a completed recovery", async () => {
    // 恢复完成后新派发的 GET 再次命中恢复码：世代相等（派发后无人恢复过）→ 照常触发新一轮维护
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(recoveryPending)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) })
      .mockResolvedValueOnce({ ok: true, json: async () => claimEnvelope })
      .mockResolvedValueOnce(recoveryPending)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) })
      .mockResolvedValueOnce({ ok: true, json: async () => claimEnvelope })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "t", fetchImpl: fetchMock,
    })

    await expect(client.loadClaimMetrics()).resolves.toMatchObject({ available: true })
    await expect(client.loadClaimMetrics()).resolves.toMatchObject({ available: true })

    expect(
      fetchMock.mock.calls.filter((call) => call[0].endsWith("/claim-maintenance")),
    ).toHaveLength(2)
  })

  it("surfaces the original error when maintenance does not fix it", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(recoveryPending)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) })
      .mockResolvedValue(recoveryPending)
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "t", fetchImpl: fetchMock,
    })

    const error = await client.loadClaimMetrics().catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(RequirementApiError)
    expect(isClaimRecoveryPendingError(error)).toBe(true)
    expect((error as RequirementApiError).status).toBe(503)
    expect((error as RequirementApiError).details.error).toBe("effective_recovery_pending")
    // 重放失败不再二次触发维护
    const maintenanceCalls = fetchMock.mock.calls.filter(
      (call) => call[0] === "http://127.0.0.1:8770/claim-maintenance",
    )
    expect(maintenanceCalls).toHaveLength(1)
  })

  it("does not trigger maintenance for ordinary retryable errors", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ error: "claim_artifact_unavailable", retryable: true }),
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "t", fetchImpl: fetchMock,
    })

    await expect(client.loadClaimMetrics()).rejects.toBeInstanceOf(RequirementApiError)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("does not trigger maintenance without the retryable flag", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ error: "effective_recovery_pending", retryable: false }),
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "t", fetchImpl: fetchMock,
    })

    await expect(client.loadClaimMetrics()).rejects.toMatchObject({ status: 503 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("never auto-recovers POST requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({
        error: "claim_artifact_recovery_required",
        retryable: true,
      }),
    })
    const client = new RequirementApiClient({
      baseUrl: "http://127.0.0.1:8770", token: "t", fetchImpl: fetchMock,
    })

    await expect(
      client.applyAiReviewAction({ aiReqId: "AIR-1", status: "accepted" }),
    ).rejects.toMatchObject({ status: 503 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8770/ai-review-actions")
  })
})

describe("desktop bridge tasks", () => {
  it("runs pipeline through the desktop bridge", async () => {
    const bridge = {
      runPipeline: vi.fn().mockResolvedValue({
        kind: "pipeline",
        outDir: "E:\\out\\run",
        summary: { counts: { requirements: 2 } },
      }),
    }

    const payload = await runDesktopTask(bridge, "runPipeline", {
      inputPath: "C:\\input.docx",
      outDir: "E:\\out\\run",
    })

    expect(payload.kind).toBe("pipeline")
    expect(bridge.runPipeline).toHaveBeenCalledWith({ inputPath: "C:\\input.docx", outDir: "E:\\out\\run" })
  })

  it("runs AI extraction through the desktop bridge", async () => {
    const bridge = {
      aiExtract: vi.fn().mockResolvedValue({
        kind: "ai_extract",
        outDir: "E:\\out\\run",
        count: 2,
      }),
    }

    const payload = await runDesktopTask(bridge, "aiExtract", {
      outDir: "E:\\out\\run",
    })

    expect(payload.kind).toBe("ai_extract")
    expect(bridge.aiExtract).toHaveBeenCalledWith({ outDir: "E:\\out\\run" })
  })

  // ===== WS-F / WS4 =====
  it("loads verification states over GET /verification-states (WS-F)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        schema: "verification-states/v1",
        states: [{ requirement_id: "FRE-1", verification: {}, lifecycle_state: "draft", evidence_fingerprint: "fp-1" }],
        total: 1,
      }),
    })
    const client = new RequirementApiClient({ baseUrl: "http://127.0.0.1:8770", token: "t", fetchImpl: fetchMock })

    const payload = await client.loadVerificationStates()

    expect(payload.total).toBe(1)
    expect(payload.states[0].requirement_id).toBe("FRE-1")
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8770/verification-states", expect.objectContaining({ headers: { "X-Requirement-Atomizer-Token": "t" } }))
  })

  it("posts verification override with CAS evidence fingerprint (WS-F)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ requirement_id: "FRE-1", verification: {}, lifecycle_state: "confirmed", written: ["verification_states.jsonl"] }),
    })
    const client = new RequirementApiClient({ baseUrl: "http://127.0.0.1:8770", token: "t", fetchImpl: fetchMock })

    await client.applyVerificationAction({
      requirementId: "FRE-1",
      verification: {
        project_manager_confirm: { confirmed: true, by: "pm", at: "2026-08-06T00:00:00Z" },
        test_lead_confirm: { confirmed: false, by: "", at: "" },
        dev_test_confirm: { confirmed: false, by: "", at: "" },
        implemented: "done",
        test_case_ids: ["TC-1"],
        test_completed: true,
      },
      expectedEvidenceFingerprint: "fp-1",
    })

    const [, init] = fetchMock.mock.calls[0]
    const body = JSON.parse(init.body)
    expect(body.requirement_id).toBe("FRE-1")
    expect(body.verification.implemented).toBe("done")
    expect(body.expected_evidence_fingerprint).toBe("fp-1")
    expect(body.actor).toBe("vue3-ui")
  })

  it("omits expected_evidence_fingerprint on first verification write (CAS opt-in)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ requirement_id: "FRE-2", lifecycle_state: "draft", written: [] }) })
    const client = new RequirementApiClient({ baseUrl: "http://127.0.0.1:8770", token: "t", fetchImpl: fetchMock })

    await client.applyVerificationAction({
      requirementId: "FRE-2",
      verification: {
        project_manager_confirm: { confirmed: false, by: "", at: "" },
        test_lead_confirm: { confirmed: false, by: "", at: "" },
        dev_test_confirm: { confirmed: false, by: "", at: "" },
        implemented: "not_started",
        test_case_ids: [],
        test_completed: false,
      },
    })

    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body).not.toHaveProperty("expected_evidence_fingerprint")
  })

  it("surfaces verification_conflict 409 as a reconfirmation error with the current fingerprint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        error: "verification_conflict",
        detail: "CAS 失配",
        requirement_id: "FRE-1",
        current_evidence_fingerprint: "fp-v2",
        needs_reconfirmation: true,
      }),
    })
    const client = new RequirementApiClient({ baseUrl: "http://127.0.0.1:8770", token: "t", fetchImpl: fetchMock })

    const error = await client.applyVerificationAction({
      requirementId: "FRE-1",
      verification: {
        project_manager_confirm: { confirmed: true, by: "", at: "" },
        test_lead_confirm: { confirmed: false, by: "", at: "" },
        dev_test_confirm: { confirmed: false, by: "", at: "" },
        implemented: "not_started",
        test_case_ids: [],
        test_completed: false,
      },
      expectedEvidenceFingerprint: "fp-v1",
    }).catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(RequirementApiError)
    expect(isNeedsReconfirmationError(error)).toBe(true)
    expect((error as RequirementApiError).details.current_evidence_fingerprint).toBe("fp-v2")
  })

  it("posts manual requirement with provenance fields (WS-F)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ functional_requirement_id: "FREQ-MANUAL-abc", written: ["manual_requirements.jsonl"] }),
    })
    const client = new RequirementApiClient({ baseUrl: "http://127.0.0.1:8770", token: "t", fetchImpl: fetchMock })

    const payload = await client.createManualRequirement({ objective: "应记录事件", behaviors: ["记录掉电"], module: "事件记录", ownership: "software" })

    expect(payload.functional_requirement_id).toBe("FREQ-MANUAL-abc")
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.objective).toBe("应记录事件")
    expect(body.behaviors).toEqual(["记录掉电"])
    expect(body.module).toBe("事件记录")
    expect(body.ownership).toBe("software")
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8770/manual-requirement")
  })

  it("posts a dependency decision (accept writes, reject does not)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ accepted: true, written: true, decision: {} }) })
    const client = new RequirementApiClient({ baseUrl: "http://127.0.0.1:8770", token: "t", fetchImpl: fetchMock })

    await client.decideDependency({ from: "FRE-1", to: "FRE-2", kind: "depend", accept: true })

    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body).toEqual({ from: "FRE-1", to: "FRE-2", kind: "depend", accept: true, actor: "vue3-ui", reason: "" })
  })

  it("searches the requirement library via query string (WS-F)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ kind: "requirement_search", query: "load profile", matches: 1, results: [{ objective: "x", overlap_score: 0.5 }] }),
    })
    const client = new RequirementApiClient({ baseUrl: "http://127.0.0.1:8770", token: "t", fetchImpl: fetchMock })

    const payload = await client.searchRequirementLibrary({ query: "load profile", limit: 5 })

    expect(payload.results?.[0].overlap_score).toBe(0.5)
    expect(fetchMock.mock.calls[0][0]).toContain("/requirement-library/search?q=load+profile&limit=5")
  })
})
