import { describe, expect, it, vi } from "vitest"
import { useReviewShortcuts } from "../useReviewShortcuts"

function keyEvent(key: string, overrides: Partial<KeyboardEvent> = {}) {
  return new KeyboardEvent("keydown", { key, bubbles: true, ...overrides })
}

describe("useReviewShortcuts", () => {
  it("navigates with j/k when items exist", () => {
    const step = vi.fn()
    const { onKeydown } = useReviewShortcuts({ isActive: () => true, hasItems: () => true, step })
    onKeydown(keyEvent("j"))
    onKeydown(keyEvent("k"))
    expect(step).toHaveBeenCalledWith(1)
    expect(step).toHaveBeenCalledWith(-1)
  })

  it("decides with a/r/d when a selection exists and not busy", () => {
    const decide = vi.fn()
    const { onKeydown } = useReviewShortcuts({
      isActive: () => true,
      hasItems: () => true,
      step: () => undefined,
      decisions: { hasSelection: () => true, isBusy: () => false, decide },
    })
    onKeydown(keyEvent("a"))
    onKeydown(keyEvent("r"))
    onKeydown(keyEvent("d"))
    expect(decide).toHaveBeenNthCalledWith(1, "accepted")
    expect(decide).toHaveBeenNthCalledWith(2, "rejected")
    expect(decide).toHaveBeenNthCalledWith(3, "needs_discussion")
  })

  it("ignores keys when inactive", () => {
    const step = vi.fn()
    const { onKeydown } = useReviewShortcuts({ isActive: () => false, hasItems: () => true, step })
    onKeydown(keyEvent("j"))
    expect(step).not.toHaveBeenCalled()
  })

  it("does not navigate when there are no items", () => {
    const step = vi.fn()
    const { onKeydown } = useReviewShortcuts({ isActive: () => true, hasItems: () => false, step })
    onKeydown(keyEvent("j"))
    expect(step).not.toHaveBeenCalled()
  })

  it("ignores modifier/compose/repeat/editable-target events", () => {
    const step = vi.fn()
    const decide = vi.fn()
    const { onKeydown } = useReviewShortcuts({
      isActive: () => true,
      hasItems: () => true,
      step,
      decisions: { hasSelection: () => true, isBusy: () => false, decide },
    })
    onKeydown(keyEvent("j", { ctrlKey: true }))
    onKeydown(keyEvent("a", { metaKey: true }))
    onKeydown(keyEvent("r", { altKey: true }))
    onKeydown(keyEvent("d", { isComposing: true } as Partial<KeyboardEvent>))
    onKeydown(keyEvent("j", { repeat: true }))
    const input = document.createElement("input")
    document.body.appendChild(input)
    // dispatch via input to make target an INPUT (editable target must be ignored)
    const evt = new KeyboardEvent("keydown", { key: "a", bubbles: true })
    Object.defineProperty(evt, "target", { value: input })
    onKeydown(evt)
    expect(step).not.toHaveBeenCalled()
    expect(decide).not.toHaveBeenCalled()
  })

  it("does not decide without selection or while busy", () => {
    const decide = vi.fn()
    const make = (sel: boolean, busy: boolean) =>
      useReviewShortcuts({
        isActive: () => true,
        hasItems: () => true,
        step: () => undefined,
        decisions: { hasSelection: () => sel, isBusy: () => busy, decide },
      }).onKeydown
    make(false, false)(keyEvent("a"))
    make(true, true)(keyEvent("r"))
    expect(decide).not.toHaveBeenCalled()
  })

  it("omits decision shortcuts entirely when no decisions binding is provided", () => {
    const step = vi.fn()
    const { onKeydown } = useReviewShortcuts({ isActive: () => true, hasItems: () => true, step })
    // a/r/d should be no-ops (no decisions binding) but j/k still navigate
    onKeydown(keyEvent("a"))
    onKeydown(keyEvent("j"))
    expect(step).toHaveBeenCalledTimes(1)
  })

  it("installs and uninstalls the window listener", () => {
    const addSpy = vi.spyOn(window, "addEventListener")
    const removeSpy = vi.spyOn(window, "removeEventListener")
    const { install, uninstall } = useReviewShortcuts({ isActive: () => true, hasItems: () => true, step: () => undefined })
    install()
    uninstall()
    expect(addSpy).toHaveBeenCalledTimes(1)
    expect(removeSpy).toHaveBeenCalledTimes(1)
    addSpy.mockRestore()
    removeSpy.mockRestore()
  })
})
