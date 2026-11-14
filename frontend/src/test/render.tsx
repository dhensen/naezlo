import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'

import { createQueryClient } from '../api/queryClient'
import { App } from '../App'

function CurrentLocation() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname + location.search + location.hash}</output>
}

/**
 * Render the whole app at `path` with a fresh query client (no retries). The current
 * location is in the element with test id `location`. Mock the backend first (`mockApi`).
 */
export function renderApp(path = '/') {
  const queryClient = createQueryClient({ retry: false })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]} useTransitions={false}>
        <App />
        <CurrentLocation />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
