import type { Schemas } from '../api/client'

export type ListMode = Schemas['ListMode']

export interface ModeInfo {
  mode: ListMode
  label: string
  /** Who works on a list in this mode: the badge's tooltip and the text next to the choice. */
  explanation: string
}

/** The list modes in the order a choice offers them. */
export const MODES: readonly ModeInfo[] = [
  {
    mode: 'human_only',
    label: 'Human only',
    explanation: 'Only people work on this list. AI agents cannot see it.',
  },
  {
    mode: 'ai_only',
    label: 'AI only',
    explanation: 'AI agents work on this list. People can read it, but not change its items.',
  },
  {
    mode: 'mixed',
    label: 'Mixed',
    explanation: 'People and AI agents work on this list together.',
  },
]

export function modeInfo(mode: ListMode): ModeInfo {
  return MODES.find((candidate) => candidate.mode === mode) ?? MODES[0]
}
