import { useEffect, useState } from 'react'

interface CopyButtonProps {
  text: string
  /** What is copied, for the accessible name: "Copy <label>". */
  label: string
  /** Inside the dark field of the text it copies, instead of next to it. */
  embedded?: boolean
}

/** Copies a text to the clipboard and says so for a moment. */
export function CopyButton({ text, label, embedded = false }: CopyButtonProps) {
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
      className={
        embedded
          ? 'min-h-9 shrink-0 rounded-md bg-white/10 px-2.5 text-xs font-semibold text-white hover:bg-white/20 focus-visible:outline-white sm:min-h-7'
          : 'shrink-0 rounded-lg border border-ink-300 bg-white px-2.5 py-2 text-sm font-medium text-ink-700 hover:bg-ink-50 sm:py-1'
      }
      onClick={copy}
    >
      <span aria-live="polite">{state === 'copied' ? 'Copied' : state === 'failed' ? 'Select it to copy' : 'Copy'}</span>
    </button>
  )
}
