import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import App from "../App.vue";

describe("review workspace shell", () => {
  it("renders the enterprise review workspace structure", () => {
    const wrapper = mount(App);

    expect(wrapper.text()).toContain("标准需求抽取与审查平台");
    expect(wrapper.text()).toContain("审查工作区");
    expect(wrapper.text()).toContain("人工审查");
    expect(wrapper.text()).toContain("需求详情");
    expect(wrapper.text()).toContain("REQ-2024-0001");
    expect(wrapper.find('[data-testid="workflow-stepper"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="requirement-table"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="detail-panel"]').exists()).toBe(true);
  });

  it("updates the selected requirement status from review decisions", async () => {
    const wrapper = mount(App);

    await wrapper.find('[data-testid="row-REQ-2024-0003"]').trigger("click");
    expect(wrapper.find('[data-testid="detail-title"]').text()).toContain("REQ-2024-0003");

    await wrapper.find('[data-testid="decision-rejected"]').trigger("click");

    expect(wrapper.find('[data-testid="detail-status"]').text()).toContain("已拒绝");
    expect(wrapper.find('[data-testid="row-status-REQ-2024-0003"]').text()).toContain("已拒绝");
  });

  it("switches sidebar modules instead of only highlighting navigation", async () => {
    const wrapper = mount(App);

    await wrapper.find('[data-testid="nav-文档管理"]').trigger("click");
    expect(wrapper.find('[data-testid="module-page"]').text()).toContain("文档管理");
    expect(wrapper.find('[data-testid="module-page"]').text()).toContain("文档解析记录");

    await wrapper.find('[data-testid="nav-质量分析"]').trigger("click");
    expect(wrapper.find('[data-testid="module-page"]').text()).toContain("质量分析");
    expect(wrapper.find('[data-testid="module-page"]').text()).toContain("低置信度分布");
  });
});
