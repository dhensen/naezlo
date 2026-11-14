import { Route, Routes } from 'react-router'

import { HomePage } from './pages/HomePage'

// The routes only; the router itself comes from main.tsx (or a MemoryRouter in tests).
export function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
    </Routes>
  )
}
