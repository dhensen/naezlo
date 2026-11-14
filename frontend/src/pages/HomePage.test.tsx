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
