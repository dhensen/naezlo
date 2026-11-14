import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'
import type { Schemas } from '../api/client'
import { projectListsKey } from '../projects/hooks'
import type { TodoList } from '../projects/hooks'

export type Item = Schemas['ItemOut']

export function itemsKey(listId: string) {
  return ['lists', listId, 'items'] as const
}

/** The items of a list in their order, open and done ones together. */
export function useItems(listId: string) {
  return useQuery({
    queryKey: itemsKey(listId),
    queryFn: () => unwrap(api.GET('/api/lists/{list_id}/items', { params: { path: { list_id: listId } } })),
  })
}

const UNSAVED_PREFIX = 'unsaved-'

/** An item that is shown already but that the server has not stored yet: it has no real id. */
export function isUnsaved(item: Item): boolean {
  return item.id.startsWith(UNSAVED_PREFIX)
}

/** One change to the items of a list. */
export type ItemChange =
  | { kind: 'add'; listId: string; title: string; unsavedId: string }
  | { kind: 'update'; item: Item; patch: Schemas['ItemPatch'] }
  /** Put the item before another item of the list, or at the end (null). */
  | { kind: 'move'; item: Item; beforeItemId: string | null }
  | { kind: 'delete'; item: Item }

/** An "add" change: a new item with this title at the end of the list. */
export function addItem(listId: string, title: string): ItemChange {
  return { kind: 'add', listId, title, unsavedId: `${UNSAVED_PREFIX}${crypto.randomUUID()}` }
}

/** Positions are 1 to n, as the server keeps them. */
function renumbered(items: Item[]): Item[] {
  return items.map((item, index) => (item.position === index + 1 ? item : { ...item, position: index + 1 }))
}

function patched(item: Item, patch: Schemas['ItemPatch'], userId: string): Item {
  const next = { ...item }
  if (patch.title != null) {
    next.title = patch.title.trim()
  }
  if (patch.notes !== undefined) {
    next.notes = patch.notes
  }
  if (patch.status != null && patch.status !== item.status) {
    const done = patch.status === 'done'
    next.status = patch.status
    next.completed_at = done ? new Date().toISOString() : null
    next.completed_by = done ? { kind: 'user', id: userId } : null
  }
  return next
}

/**
 * The items after a change. Without `saved` it is the expected result (shown at once); with
 * `saved`, the server's answer, it is the confirmed one. Applying a change twice gives the
 * same list, so confirming is safe whatever happened to the cache in between.
 */
export function applyItemChange(items: Item[], change: ItemChange, userId: string, saved?: Item): Item[] {
  switch (change.kind) {
    case 'add': {
      const added: Item = saved ?? {
        id: change.unsavedId,
        list_id: change.listId,
        title: change.title.trim(),
        notes: null,
        status: 'open',
        position: items.length + 1,
        created_by: { kind: 'user', id: userId },
        completed_by: null,
        completed_at: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      const known = items.some((item) => item.id === change.unsavedId || item.id === added.id)
      return known
        ? items.map((item) => (item.id === change.unsavedId || item.id === added.id ? added : item))
        : [...items, added]
    }
    case 'update':
      return items.map((item) => (item.id === change.item.id ? (saved ?? patched(item, change.patch, userId)) : item))
    case 'move': {
      const moved = items.find((item) => item.id === change.item.id)
      if (moved === undefined) {
        return items
      }
      const others = items.filter((item) => item.id !== moved.id)
      const before = change.beforeItemId === null ? -1 : others.findIndex((item) => item.id === change.beforeItemId)
      const index = before === -1 ? others.length : before
      return renumbered([...others.slice(0, index), saved ?? moved, ...others.slice(index)])
    }
    case 'delete':
      return renumbered(items.filter((item) => item.id !== change.item.id))
  }
}

async function send(change: ItemChange): Promise<Item | undefined> {
  switch (change.kind) {
    case 'add':
      return unwrap(
        api.POST('/api/lists/{list_id}/items', {
          params: { path: { list_id: change.listId } },
          body: { title: change.title },
        }),
      )
    case 'update':
      return unwrap(
        api.PATCH('/api/items/{item_id}', { params: { path: { item_id: change.item.id } }, body: change.patch }),
      )
    case 'move':
      return unwrap(
        api.POST('/api/items/{item_id}/move', {
          params: { path: { item_id: change.item.id } },
          body: { before_item_id: change.beforeItemId },
        }),
      )
    case 'delete':
      await unwrap(api.DELETE('/api/items/{item_id}', { params: { path: { item_id: change.item.id } } }))
      return undefined
  }
}

/**
 * Change the items of a list: `mutate(change)`.
 *
 * The change shows at once. The requests of one list go to the server one after another, in
 * the order they were made, so two quick additions keep their order. When the server
 * rejects a change the items go back to what they were, `onError` gets the error and the
 * list is fetched again, which also settles any change that was still waiting.
 */
export function useChangeItems(list: TodoList, userId: string, onError: (error: unknown) => void) {
  const queryClient = useQueryClient()
  const queryKey = itemsKey(list.id)
  return useMutation({
    mutationKey: [...queryKey, 'change'],
    scope: { id: `items-of-${list.id}` },
    mutationFn: send,
    onMutate: async (change) => {
      // A fetch that is under way predates the change and would undo it on the screen.
      await queryClient.cancelQueries({ queryKey, exact: true })
      const previous = queryClient.getQueryData<Item[]>(queryKey)
      queryClient.setQueryData<Item[]>(queryKey, (items) => items && applyItemChange(items, change, userId))
      return { previous }
    },
    onSuccess: (saved, change) => {
      queryClient.setQueryData<Item[]>(queryKey, (items) => items && applyItemChange(items, change, userId, saved))
    },
    onError: async (error, _change, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData(queryKey, context.previous)
      }
      onError(error)
      await queryClient.cancelQueries({ queryKey, exact: true })
      void queryClient.invalidateQueries({ queryKey, exact: true })
    },
    onSettled: async () => {
      // The project's page shows the number of open items per list.
      const counted = projectListsKey(list.project_id)
      await queryClient.cancelQueries({ queryKey: counted, exact: true })
      void queryClient.invalidateQueries({ queryKey: counted, exact: true })
    },
  })
}
