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
    expect(row.category).toBe("COSEM 属性访问")
    expect(row.categoryCode).toBe("cosem_attribute_access")
    expect(row.object).toBe("Clock")
    expect(row.chineseText).toBe("The meter shall expose Clock attributes.")
    expect(row.originalText).toBe("Clock object attributes shall be accessible.")
    expect(row.status).toBe("expert_pending")
    expect(row.ambiguity.level).toBe("高")
    expect(row.ambiguity.reasons).toEqual(["needs expert confirmation"])
  })

  it("preserves ABNT module and raw classification fields for review", () => {
    const row = mapBackendRequirement({
      stable_req_id: "SREQ-ABNT-1",
      requirement_type: "cosem_attribute_access",
      object: "Clock",
      requirement: "The Clock object shall expose attribute 2.",
      domain: "access_control",
      domain_tags: ["access_control", "cosem_object", "meter_function"],
      section_path: ["2 20 Control of"],
      source_refs: ["BLK-002001"],
      confidence: 0.72,
    })

    expect(row.type).toBe("接口")
    expect(row.module).toBe("访问控制")
    expect(row.moduleCode).toBe("access_control")
    expect(row.category).toBe("COSEM 属性访问")
    expect(row.categoryCode).toBe("cosem_attribute_access")
    expect(row.domainTags).toEqual(["access_control", "cosem_object", "meter_function"])
    expect(row.sectionPath).toEqual(["2 20 Control of"])
    expect(row.sourceLocation).toBe("BLK-002001")
  })

  it("does not collapse access-control requirements into a generic functional label", () => {
    const row = mapBackendRequirement({
      stable_req_id: "SREQ-ABNT-2",
      requirement_type: "access_control",
      object: "Public Client",
      requirement: "The Public Client shall only read public data.",
      domain: "association",
    })

    expect(row.type).toBe("安全")
    expect(row.category).toBe("访问控制")
    expect(row.categoryCode).toBe("access_control")
    expect(row.module).toBe("关联/客户端")
  })

  it("keeps backend status values separate from display labels", () => {
    expect(statusDisplay("accepted")).toBe("已接受")
    expect(statusDisplay("rejected")).toBe("已拒绝")
    expect(toBackendStatus("accepted")).toBe("accepted")
  })

  it("maps backend risk values (high_risk / mandatory_review / low_risk) to UI levels", () => {
    const base = {
      stable_req_id: "SREQ-RISK-1",
      requirement_type: "security_policy_bit",
      object: "Security Policy",
      requirement: "shall enforce security policy.",
      confidence: 0.9,
    }

    const high = mapBackendRequirement({ ...base, review: { risk: "high_risk" } })
    expect(high.risk).toBe("高")
    expect(high.ambiguity.level).toBe("高")

    const mandatory = mapBackendRequirement({ ...base, review: { risk: "mandatory_review" } })
    expect(mandatory.risk).toBe("高")

    const low = mapBackendRequirement({ ...base, review: { risk: "low_risk" } })
    expect(low.risk).toBe("低")
  })
})
