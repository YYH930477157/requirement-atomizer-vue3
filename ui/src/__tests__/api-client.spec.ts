import { describe, expect, it, vi } from "vitest"
import { RequirementApiClient, RequirementApiError, isNeedsReconfirmationError } from "../api-client"
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
})
