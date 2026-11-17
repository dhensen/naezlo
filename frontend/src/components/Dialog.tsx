import { useEffect, useId } from 'react'
import type { ReactNode } from 'react'

interface DialogProps {
  title: string
  /** Escape and a press next to the dialog close it; the content brings its own Cancel button. */
  onClose: () => void
  /** More room, for a dialog with rows of data instead of a small form. */
  wide?: boolean
  children: ReactNode
}

/** A modal dialog, named by its heading. */
export function Dialog({ title, onClose, wide = false, children }: DialogProps) {
  const titleId = useId()

  // The page behind it does not scroll along with a swipe on the dialog.
  useEffect(() => {
    document.body.classList.add('overflow-hidden')
    return () => document.body.classList.remove('overflow-hidden')
  }, [])

  // At phone width it sits at the top, so the on-screen keyboard does not cover its fields.
  return (
    <div
      className="fixed inset-0 z-30 flex items-start justify-center bg-ink-900/45 p-3 backdrop-blur-[2px] sm:items-center sm:p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose()
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`max-h-full w-full overflow-y-auto overscroll-contain rounded-2xl bg-white p-4 shadow-float sm:p-6 ${wide ? 'max-w-xl' : 'max-w-sm'}`}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            onClose()
          }
        }}
      >
        <h2 id={titleId} className="text-lg font-semibold break-words">
          {title}
        </h2>
        {children}
      </div>
    </div>
  )
}

export const DIALOG_INPUT =
  'rounded-lg border border-ink-300 px-3 py-2 font-normal text-ink-900 focus:border-brand-500 focus:ring-3 focus:ring-brand-500/15 focus:outline-none'
export const DIALOG_LABEL = 'flex flex-col gap-1 text-sm font-medium text-ink-700'
export const DIALOG_CANCEL =
  'rounded-lg border border-ink-300 px-3 py-2 text-sm font-medium text-ink-700 hover:bg-ink-50 sm:py-1.5'
export const DIALOG_SUBMIT =
  'rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60 sm:py-1.5'
export const DIALOG_DANGER =
  'rounded-lg bg-red-700 px-3 py-2 text-sm font-medium text-white hover:bg-red-600 disabled:opacity-60 sm:py-1.5'
