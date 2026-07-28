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
        block_id: "BLK-T1", row_index: 2, actor: "reviewer", reason: "", route: "",
      }),
    }))

    // LLM 不可用：503 + ok:false → 抛出带真实后端原因的错误（按钮不假装可用）
    await expect(client.spotExtract({ blockId: "B2" })).rejects.toMatchObject({
      status: 503, message: "openai_compatible route is not configured",
    })
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8770/spot-extract", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        block_id: "B2", row_index: null, actor: "", reason: "", route: "",
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
    })

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8770/ai-review-actions",
      expect.objectContaining({
        body: JSON.stringify({
          ai_req_id: "AIR-1", status: "accepted",
          source_fingerprint: "source-v2", review_subject_fingerprint: "subject-v2",
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
