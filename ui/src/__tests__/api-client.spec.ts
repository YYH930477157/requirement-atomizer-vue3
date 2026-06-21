import { describe, expect, it, vi } from "vitest"
import { RequirementApiClient } from "../api-client"
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
})
