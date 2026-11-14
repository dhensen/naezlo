import { useId } from 'react'
import type { ReactNode } from 'react'

interface DialogProps {
  title: string
  /** Escape and a press next to the dialog close it; the content brings its own Cancel button. */
  onClose: () => void
  children: ReactNode
}

/** A modal dialog, named by its heading. */
export function Dialog({ title, onClose, children }: DialogProps) {
  const titleId = useId()

  return (
    <div
      className="fixed inset-0 z-30 flex items-center justify-center bg-slate-900/40 p-4"
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
        className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl"
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            onClose()
          }
        }}
      >
        <h2 id={titleId} className="text-lg font-semibold tracking-tight break-words">
          {title}
        </h2>
        {children}
      </div>
    </div>
  )
}

export const DIALOG_INPUT =
  'rounded-md border border-slate-300 px-3 py-2 font-normal text-slate-900 focus:border-slate-500 focus:outline-none'
export const DIALOG_LABEL = 'flex flex-col gap-1 text-sm font-medium text-slate-700'
export const DIALOG_CANCEL =
  'rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50'
export const DIALOG_SUBMIT =
  'rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60'
export const DIALOG_DANGER =
  'rounded-md bg-red-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-600 disabled:opacity-60'
