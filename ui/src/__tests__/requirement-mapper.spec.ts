import { describe, expect, it } from "vitest"
import { mapBackendRequirement, statusDisplay, toBackendStatus } from "../requirement-mapper"

describe("requirement mapper", () => {
  it("maps backend requirement fields and English review status into the UI model", () => {
    const row = mapBackendRequirement({
      stable_req_id: "SREQ-1",
      req_id: "AREQ-9",
      requirement_type: "cosem_attribute_access",
      object_name: "Clock",
      description: "The meter shall expose Clock attributes.",
      source_quote: "Clock object attributes shall be accessible.",
      source_ref: "Appendix 9 p.12",
      confidence: 0.82,
      review_state: { requirement_id: "SREQ-1", status: "expert_pending" },
      review: { risk: "high", review_notes: ["needs expert confirmation"] },
      labels: ["security"],
    })

    expect(row.id).toBe("SREQ-1")
    expect(row.backendId).toBe("SREQ-1")
    expect(row.type).toBe("接口")
    expect(row.object).toBe("Clock")
    expect(row.chineseText).toBe("The meter shall expose Clock attributes.")
    expect(row.originalText).toBe("Clock object attributes shall be accessible.")
    expect(row.status).toBe("expert_pending")
    expect(row.ambiguity.level).toBe("高")
    expect(row.ambiguity.reasons).toEqual(["needs expert confirmation"])
  })

  it("keeps backend status values separate from display labels", () => {
    expect(statusDisplay("accepted")).toBe("已接受")
    expect(statusDisplay("rejected")).toBe("已拒绝")
    expect(toBackendStatus("accepted")).toBe("accepted")
  })
})
