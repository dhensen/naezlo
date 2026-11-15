import { Route, Routes } from 'react-router'

import { RequireAuth } from './auth/RequireAuth'
import { AppLayout } from './components/AppLayout'
import { AgentsPage } from './pages/AgentsPage'
import { HomePage } from './pages/HomePage'
import { ListPage } from './pages/ListPage'
import { LoginPage } from './pages/LoginPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { OrganizationPage } from './pages/OrganizationPage'
import { OrganizationSettingsPage } from './pages/OrganizationSettingsPage'
import { ProjectPage } from './pages/ProjectPage'

// The routes only; the router and the query client come from main.tsx (or from
// `renderApp` in tests). Every page except /login goes inside the guard. Pages of an
// organization go under /o/:orgSlug, where the layout shows the sidebar and
// `useCurrentOrganization()` gives the organization.
export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route path="/o/:orgSlug" element={<AppLayout />}>
          <Route index element={<OrganizationPage />} />
          <Route path="agents" element={<AgentsPage />} />
          <Route path="settings" element={<OrganizationSettingsPage />} />
          <Route path="p/:projectId" element={<ProjectPage />} />
          <Route path="l/:listId" element={<ListPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
        <Route element={<AppLayout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
