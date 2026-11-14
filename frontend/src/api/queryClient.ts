import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import type { QueryKey } from '@tanstack/react-query'

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

/**
 * Put a change that the server confirmed into a cached query.
 *
 * A fetch of that query that is still under way started before the change and would bring
 * the old state back, so it is cancelled first. Without cached data there is nothing to
 * update: the query is fetched (again) instead.
 */
export async function applyToCache<T>(client: QueryClient, queryKey: QueryKey, update: (data: T) => T): Promise<void> {
  await client.cancelQueries({ queryKey, exact: true })
  if (client.getQueryData<T>(queryKey) === undefined) {
    await client.invalidateQueries({ queryKey, exact: true })
  } else {
    client.setQueryData<T>(queryKey, (data) => (data === undefined ? data : update(data)))
  }
}
