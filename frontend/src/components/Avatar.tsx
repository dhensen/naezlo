import { ModeIcon } from './ModeBadge'

interface AvatarProps {
  name: string
  /** A person is a circle with their initial, an agent a blue square with the robot. */
  kind: 'user' | 'agent'
  /** The size and anything about its place: `size-6`. */
  className?: string
}

/** Who it is at a glance, next to a name: decoration, the name itself says it in words. */
export function Avatar({ name, kind, className = 'size-6' }: AvatarProps) {
  if (kind === 'agent') {
    return (
      <span
        aria-hidden="true"
        data-avatar="agent"
        className={`inline-flex shrink-0 items-center justify-center rounded-md bg-brand-600 text-white ${className}`}
      >
        <ModeIcon mode="ai_only" className="size-[62%]" />
      </span>
    )
  }
  return (
    <span
      aria-hidden="true"
      data-avatar="user"
      // The initial is drawn by the stylesheet: it is decoration, not part of the row's text.
      data-initial={name.trim().charAt(0).toUpperCase()}
      className={`inline-flex shrink-0 items-center justify-center rounded-full bg-ink-800 text-[0.6875rem] leading-none font-semibold text-white before:content-[attr(data-initial)] ${className}`}
    />
  )
}
