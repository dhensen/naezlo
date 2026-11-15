import type { KeyboardEvent, ReactNode } from 'react'

export interface Tab<Id extends string> {
  id: Id
  label: string
}

interface TabsProps<Id extends string> {
  /** What the tabs choose between: the accessible name of the tab list. */
  label: string
  tabs: readonly Tab<Id>[]
  selected: Id
  onSelect: (id: Id) => void
}

function tabId(id: string): string {
  return `tab-${id}`
}

/**
 * The tabs of a page; show the chosen part in a `<TabPanel>`. Left and Right move between
 * the tabs, as people expect of a tab list; only the selected tab is in the Tab order.
 */
export function Tabs<Id extends string>({ label, tabs, selected, onSelect }: TabsProps<Id>) {
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (step === 0) {
      return
    }
    event.preventDefault()
    const index = tabs.findIndex((tab) => tab.id === selected)
    const next = tabs[(index + step + tabs.length) % tabs.length]
    onSelect(next.id)
    event.currentTarget.querySelector<HTMLButtonElement>(`#${tabId(next.id)}`)?.focus()
  }

  return (
    <div role="tablist" aria-label={label} className="flex gap-1 border-b border-slate-200" onKeyDown={onKeyDown}>
      {tabs.map((tab) => {
        const current = tab.id === selected
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={tabId(tab.id)}
            aria-selected={current}
            tabIndex={current ? 0 : -1}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              current
                ? 'border-slate-900 text-slate-900'
                : 'border-transparent text-slate-600 hover:border-slate-300 hover:text-slate-900'
            }`}
            onClick={() => onSelect(tab.id)}
          >
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}

/** The part of the page that belongs to the selected tab. */
export function TabPanel({ tab, className, children }: { tab: string; className?: string; children: ReactNode }) {
  return (
    <div role="tabpanel" aria-labelledby={tabId(tab)} className={className}>
      {children}
    </div>
  )
}
