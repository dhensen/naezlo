import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'

import { ApiError } from './client'

/** The key of the signed-in user (`useMe`). Its data is null when nobody is signed in. */
export const ME_KEY = ['me'] as const

/**
 * The app's query client. `retry: false` is for tests, which want a failure at once.
 *
 * Any call that answers 401 means the session is gone: the signed-in user is forgotten and
 * the auth guard sends the browser to the login page.
 */
export function createQueryClient(options: { retry?: boolean } = {}): QueryClient {
  const onError = (error: unknown) => {
    if (error instanceof ApiError && error.status === 401) {
      client.setQueryData(ME_KEY, null)
    }
  }
  const client = new QueryClient({
    queryCache: new QueryCache({ onError }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: {
      queries: {
        // A 4xx will not get better by asking again; a network error or a 5xx might.
        retry: (failures, error) =>
          (options.retry ?? true) &&
          failures < 2 &&
          !(error instanceof ApiError && error.status >= 400 && error.status < 500),
      },
    },
  })
  return client
}
