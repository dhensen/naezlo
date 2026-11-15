import { useEffect, useState } from 'react'

interface CopyButtonProps {
  text: string
  /** What is copied, for the accessible name: "Copy <label>". */
  label: string
}

/** Copies a text to the clipboard and says so for a moment. */
export function CopyButton({ text, label }: CopyButtonProps) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')

  useEffect(() => {
    if (state === 'idle') {
      return
    }
    const timer = setTimeout(() => setState('idle'), 2000)
    return () => clearTimeout(timer)
  }, [state])

  function copy() {
    // The clipboard needs a secure context (HTTPS or localhost); without one, say so and
    // leave the text to be selected by hand.
    const written: Promise<void> =
      typeof navigator.clipboard?.writeText === 'function'
        ? navigator.clipboard.writeText(text)
        : Promise.reject(new Error('No clipboard'))
    written.then(
      () => setState('copied'),
      () => setState('failed'),
    )
  }

  return (
    <button
      type="button"
      aria-label={`Copy ${label}`}
      className="shrink-0 rounded-md border border-slate-300 bg-white px-2.5 py-2 text-sm sm:py-1 font-medium text-slate-700 hover:bg-slate-50"
      onClick={copy}
    >
      <span aria-live="polite">{state === 'copied' ? 'Copied' : state === 'failed' ? 'Select it to copy' : 'Copy'}</span>
    </button>
  )
}
