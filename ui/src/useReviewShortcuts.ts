/**
 * 评审键盘流 composable（G9-2 抽取）。
 *
 * 此前 DocumentReview.vue 内联了一份 handleReviewShortcut：j/k 在需求列表上下导航、
 * a/r/d 对当前选中需求给出接受/拒绝/讨论裁决。FunctionalReview.vue 没有任何键盘流。
 * 本 composable 把这份逻辑抽成可复用件，两个评审组件共用同一份守卫与键位映射，
 * 避免行为漂移（如守卫条件、键位大小写、可编辑目标判定在两处各自演化）。
 *
 * 设计取舍：
 *  - 导航（j/k）是两个组件真正共享的交互（都有列表 + selectedId），故为必选 binding。
 *  - 裁决快捷键（a/r/d）是可选 binding。DocumentReview 逐条 accept/reject/discuss 适用；
 *    FunctionalReview 的裁决是批量 runAdjudication + 需 actor/reason 留痕的 overturn
 *    （append-only），不适用一键 a/r/d，故只接导航、不接裁决。
 */

export type ReviewShortcutDecision = "accepted" | "rejected" | "needs_discussion"

/** 裁决键位映射：a=接受 / r=拒绝 / d=讨论，与 DocumentReview 旧行为逐字一致。 */
const DECISION_KEYS: Record<string, ReviewShortcutDecision> = {
  a: "accepted",
  r: "rejected",
  d: "needs_discussion",
}

/** 可选裁决快捷键 binding；不提供则 a/r/d 不响应。 */
export interface ReviewShortcutDecisions {
  hasSelection: () => boolean
  isBusy: () => boolean
  decide: (decision: ReviewShortcutDecision) => void
}

export interface ReviewShortcutBindings {
  /** 组件是否处于活动 nav（非活动组件不抢全局键）。 */
  isActive: () => boolean
  /** 列表是否有可导航项（j/k 前置门）。 */
  hasItems: () => boolean
  /** 上下导航回调：正数向下、负数向上。 */
  step: (delta: number) => void
  /** 可选裁决快捷键 binding。 */
  decisions?: ReviewShortcutDecisions
}

/** 是否在可编辑元素上（输入框/文本域/下拉/contenteditable）——这些目标不抢快捷键。 */
export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
}

export function useReviewShortcuts(bindings: ReviewShortcutBindings) {
  function onKeydown(event: KeyboardEvent) {
    if (!bindings.isActive() || event.defaultPrevented || event.repeat || event.isComposing
        || event.ctrlKey || event.metaKey || event.altKey || isEditableTarget(event.target)) return
    const key = event.key.toLowerCase()
    if ((key === "j" || key === "k") && bindings.hasItems()) {
      event.preventDefault()
      bindings.step(key === "j" ? 1 : -1)
      return
    }
    const decisions = bindings.decisions
    if (!decisions || !decisions.hasSelection() || decisions.isBusy()) return
    const decision = DECISION_KEYS[key]
    if (!decision) return
    event.preventDefault()
    decisions.decide(decision)
  }

  function install() {
    window.addEventListener("keydown", onKeydown)
  }

  function uninstall() {
    window.removeEventListener("keydown", onKeydown)
  }

  return { onKeydown, install, uninstall }
}
