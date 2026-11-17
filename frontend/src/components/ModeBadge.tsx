import { useId } from 'react'

import { modeInfo } from '../lists/modes'
import type { ListMode } from '../lists/modes'

const STYLES: Record<ListMode, string> = {
  human_only: 'bg-ink-100 text-ink-700 ring-ink-200',
  ai_only: 'bg-brand-50 text-brand-700 ring-brand-200',
  mixed: 'bg-mint-50 text-mint-800 ring-mint-200',
}

const PERSON = (
  <>
    <circle cx="8" cy="5" r="2.5" />
    <path d="M3 13.5c0-2.5 2.2-4.5 5-4.5s5 2 5 4.5" />
  </>
)

const ROBOT = (
  <>
    <rect x="3" y="6" width="10" height="7" rx="1.5" />
    <path d="M8 6V3.5" />
    <circle cx="8" cy="2.75" r="0.75" />
    <path d="M6.25 9.25v1M9.75 9.25v1" />
  </>
)

// A person on the left and a small robot on the right.
const BOTH = (
  <>
    <circle cx="4.5" cy="5.5" r="2" />
    <path d="M1 13c0-2 1.6-3.5 3.5-3.5S8 11 8 13" />
    <rect x="9.5" y="7.5" width="5.5" height="5" rx="1" />
    <path d="M12.25 7.5V5.5" />
    <path d="M11.4 9.75v.75M13.1 9.75v.75" />
  </>
)

const ICONS: Record<ListMode, typeof PERSON> = { human_only: PERSON, ai_only: ROBOT, mixed: BOTH }

/** The icon of a list mode; decoration next to the mode's label. */
export function ModeIcon({ mode, className = 'size-3.5' }: { mode: ListMode; className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      data-mode-icon={mode}
      className={`shrink-0 ${className}`}
    >
      {ICONS[mode]}
    </svg>
  )
}

/**
 * Who works on a list: the mode's icon and label, with a tooltip that explains it on hover
 * and on keyboard focus.
 */
export function ModeBadge({ mode }: { mode: ListMode }) {
  const tooltipId = useId()
  const info = modeInfo(mode)

  return (
    <span className="group relative inline-flex">
      <span
        tabIndex={0}
        aria-describedby={tooltipId}
        className={`inline-flex cursor-default items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${STYLES[mode]}`}
      >
        <ModeIcon mode={mode} />
        {info.label}
      </span>
      <span
        role="tooltip"
        id={tooltipId}
        className="pointer-events-none invisible absolute top-full right-0 z-10 mt-1 w-56 rounded-lg bg-ink-900 px-2.5 py-1.5 text-xs font-normal text-white opacity-0 shadow-float transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100"
      >
        {info.explanation}
      </span>
    </span>
  )
}
