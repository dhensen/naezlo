import type { ListRole } from './hooks'

/** The roles as the UI names them. A project role is one of these without `none`. */
export const ROLE_LABELS: Record<ListRole, string> = {
  viewer: 'Viewer',
  editor: 'Editor',
  admin: 'Admin',
  none: 'No access',
}
