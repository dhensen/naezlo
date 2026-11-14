import { screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { APP_NAME } from '../config'
import { ADA, json, mockApi } from '../test/api'
import { renderApp } from '../test/render'

test('the home page shows the app name', async () => {
  mockApi({ 'GET /api/me': json(ADA) })

  renderApp('/')

  expect(await screen.findByRole('heading', { level: 1, name: APP_NAME })).toBeInTheDocument()
})

test('the home page shows the name of the first organization', async () => {
  mockApi({
    'GET /api/me': json({
      ...ADA,
      organizations: [
        { id: '0190a000-0000-7000-8000-0000000000a1', name: "Ada Lovelace's organization", slug: 'ada-lovelace', role: 'owner' },
        { id: '0190a000-0000-7000-8000-0000000000a2', name: 'Analytical Engines', slug: 'analytical-engines', role: 'member' },
      ],
    }),
  })

  renderApp('/')

  expect(await screen.findByText("Ada Lovelace's organization")).toBeInTheDocument()
  expect(screen.queryByText('Analytical Engines')).not.toBeInTheDocument()
})
