import { useEffect } from 'react'
import type { RefObject } from 'react'

/**
 * Close an open menu: on Escape, on a press outside `ref`, and when the focus moves out of it.
 * (Not on blur alone: Safari does not focus a button that is clicked, so a click inside the
 * menu would look like the focus leaving.)
 */
export function useDismiss(ref: RefObject<HTMLElement | null>, open: boolean, onDismiss: () => void): void {
  useEffect(() => {
    if (!open) {
      return
    }
    const outside = (target: EventTarget | null) =>
      target instanceof Node && ref.current !== null && !ref.current.contains(target)
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onDismiss()
      }
    }
    const onPointerDown = (event: PointerEvent) => {
      if (outside(event.target)) {
        onDismiss()
      }
    }
    const onFocusIn = (event: FocusEvent) => {
      if (outside(event.target)) {
        onDismiss()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('focusin', onFocusIn)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('focusin', onFocusIn)
    }
  }, [ref, open, onDismiss])
}
