import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError, unwrap } from '../api/client'
import type { Me, Schemas } from '../api/client'
import { ME_KEY } from '../api/queryClient'

async function fetchMe(): Promise<Me | null> {
  try {
    return await unwrap(api.GET('/api/me'))
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null
    }
    throw error
  }
}

/** The signed-in user with their organizations; `data` is null when nobody is signed in. */
export function useMe() {
  return useQuery({ queryKey: ME_KEY, queryFn: fetchMe })
}

/** Which ways of signing in this deployment offers. */
export function useAppConfig() {
  return useQuery({
    queryKey: ['config'],
    queryFn: () => unwrap(api.GET('/api/config')),
    staleTime: Infinity,
  })
}

/** Sign in without a password (development only). The signed-in user is stored for `useMe`. */
export function useDevLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['DevLoginIn']) =>
      unwrap(api.POST('/api/auth/dev-login', { body })),
    onSuccess: (me) => {
      queryClient.setQueryData(ME_KEY, me)
    },
  })
}

/** Sign out and forget everything that was loaded for this user. */
export function useSignOut() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/auth/logout')),
    onSuccess: () => {
      queryClient.setQueryData(ME_KEY, null)
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_KEY[0] })
    },
  })
}
