import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'

import type { Me, Schemas } from '../api/client'
import { ACME, ADA_IN_ORGS, apiError, BETA, json, mockApi } from '../test/api'
import { renderApp } from '../test/render'

type Member = Schemas['MemberOut']
type Routes = Parameters<typeof mockApi>[0]

const ADA_MEMBER: Member = { user_id: ADA_IN_ORGS.user.id, email: 'ada@example.com', name: 'Ada Lovelace', role: 'owner' }
const GRACE: Member = {
  user_id: '0190a000-0000-7000-8000-000000000002',
  email: 'grace@example.com',
  name: 'Grace Hopper',
  role: 'member',
}
const LINUS: Member = {
  user_id: '0190a000-0000-7000-8000-000000000003',
  email: 'linus@example.com',
  name: 'Linus Owner',
  role: 'owner',
}
const INVITATION: Schemas['InvitationOut'] = {
  id: '0190a000-0000-7000-8000-0000000000c1',
  email: 'new@example.com',
  role: 'admin',
  invited_by: { user_id: ADA_IN_ORGS.user.id, name: 'Ada Lovelace' },
  created_at: '2026-11-01T10:00:00Z',
}

function me(role: Schemas['MembershipRole']): Me {
  return { ...ADA_IN_ORGS, organizations: [{ ...ACME, role }, BETA] }
}

function routes(role: Schemas['MembershipRole'] = 'owner', members: Member[] = [ADA_MEMBER, GRACE]): Routes {
  return {
    'GET /api/me': json(me(role)),
    [`GET /api/orgs/${ACME.id}/projects`]: json([]),
    [`GET /api/orgs/${BETA.id}/projects`]: json([]),
    [`GET /api/orgs/${ACME.id}/members`]: json(members.map((m) => (m === ADA_MEMBER ? { ...m, role } : m))),
    [`GET /api/orgs/${ACME.id}/invitations`]: json([INVITATION]),
  }
}

async function membersTable() {
  const table = await screen.findByRole('table', { name: 'Members' })
  await within(table).findByRole('rowheader', { name: /Ada Lovelace/ })
  return table
}

test('the sidebar links to the settings page', async () => {
  mockApi(routes())
  renderApp('/o/acme')

  await userEvent.click(await screen.findByRole('link', { name: 'Settings' }))

  expect(screen.getByTestId('location')).toHaveTextContent('/o/acme/settings')
  expect(await screen.findByRole('heading', { level: 1, name: 'Organization settings' })).toBeInTheDocument()
})

test('an owner renames the organization and the switcher follows', async () => {
  let sent: unknown
  mockApi({
    ...routes(),
    [`PATCH /api/orgs/${ACME.id}`]: async (request) => {
      sent = await request.json()
      return json({ ...ACME, name: 'Acme Corp' })
    },
  })
  renderApp('/o/acme/settings')

  const name = await screen.findByLabelText('Organization name')
  expect(name).toHaveValue('Acme')
  expect(screen.getByRole('button', { name: 'Rename' })).toBeDisabled()
  await userEvent.clear(name)
  await userEvent.type(name, 'Acme Corp')
  await userEvent.click(screen.getByRole('button', { name: 'Rename' }))

  expect(await screen.findByRole('button', { name: 'Organization: Acme Corp' })).toBeInTheDocument()
  expect(sent).toEqual({ name: 'Acme Corp' })
  expect(screen.getByText(/Renamed/)).toBeInTheDocument()
  expect(screen.getByTestId('location')).toHaveTextContent('/o/acme/settings')
})

test('the members table shows name, email and role with controls for an owner', async () => {
  mockApi(routes())
  renderApp('/o/acme/settings')

  const table = await membersTable()
  const rows = within(table).getAllByRole('row').slice(1)
  expect(rows).toHaveLength(2)
  expect(within(rows[0]).getByRole('rowheader')).toHaveTextContent('Ada Lovelace (you)')
  expect(within(rows[0]).getByText('ada@example.com')).toBeInTheDocument()
  expect(within(rows[0]).getByRole('combobox', { name: 'Role of Ada Lovelace' })).toHaveValue('owner')
  expect(within(rows[0]).getByRole('button', { name: 'Leave organization' })).toBeInTheDocument()
  expect(within(rows[1]).getByText('grace@example.com')).toBeInTheDocument()
  expect(within(rows[1]).getByRole('combobox', { name: 'Role of Grace Hopper' })).toHaveValue('member')
  expect(within(rows[1]).getByRole('button', { name: 'Remove Grace Hopper' })).toBeInTheDocument()
})

test('changing a role sends it and shows the new role', async () => {
  let sent: unknown
  mockApi({
    ...routes(),
    [`PATCH /api/orgs/${ACME.id}/members/${GRACE.user_id}`]: async (request) => {
      sent = await request.json()
      return json({ ...GRACE, role: 'admin' })
    },
  })
  renderApp('/o/acme/settings')
  await membersTable()

  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Role of Grace Hopper' }), 'Admin')

  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Role of Grace Hopper' })).toHaveValue('admin'))
  expect(sent).toEqual({ role: 'admin' })
})

test('the last-owner error is shown and the role stays', async () => {
  mockApi({
    ...routes(),
    [`PATCH /api/orgs/${ACME.id}/members/${ADA_MEMBER.user_id}`]: apiError(
      409,
      'last_owner',
      'An organization needs at least one owner; make someone else owner first',
    ),
    [`DELETE /api/orgs/${ACME.id}/members/${ADA_MEMBER.user_id}`]: apiError(
      409,
      'last_owner',
      'An organization needs at least one owner; make someone else owner first',
    ),
  })
  renderApp('/o/acme/settings')
  await membersTable()

  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Role of Ada Lovelace' }), 'Member')
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'An organization needs at least one owner; make someone else owner first',
  )
  expect(screen.getByRole('combobox', { name: 'Role of Ada Lovelace' })).toHaveValue('owner')

  await userEvent.click(screen.getByRole('button', { name: 'Leave organization' }))
  await userEvent.click(screen.getByRole('button', { name: 'Yes, leave' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('An organization needs at least one owner')
  expect(screen.getByTestId('location')).toHaveTextContent('/o/acme/settings')
})

test('removing a member asks first and takes them out of the table', async () => {
  const fetchMock = mockApi({
    ...routes(),
    [`DELETE /api/orgs/${ACME.id}/members/${GRACE.user_id}`]: new Response(null, { status: 204 }),
  })
  renderApp('/o/acme/settings')
  const table = await membersTable()

  await userEvent.click(screen.getByRole('button', { name: 'Remove Grace Hopper' }))
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(fetchMock.mock.calls.some(([request]) => request.method === 'DELETE')).toBe(false)

  await userEvent.click(screen.getByRole('button', { name: 'Remove Grace Hopper' }))
  await userEvent.click(screen.getByRole('button', { name: 'Yes, remove' }))

  await waitFor(() => expect(within(table).queryByText('grace@example.com')).not.toBeInTheDocument())
  expect(within(table).getByText('ada@example.com')).toBeInTheDocument()
})

test('leaving goes to another organization', async () => {
  mockApi({
    ...routes('member'),
    [`DELETE /api/orgs/${ACME.id}/members/${ADA_MEMBER.user_id}`]: new Response(null, { status: 204 }),
  })
  renderApp('/o/acme/settings')
  await membersTable()

  await userEvent.click(screen.getByRole('button', { name: 'Leave organization' }))
  await userEvent.click(screen.getByRole('button', { name: 'Yes, leave' }))

  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/o/beta-works'))
  expect(await screen.findByRole('button', { name: 'Organization: Beta Works' })).toBeInTheDocument()
})

test('an admin cannot change or remove an owner', async () => {
  mockApi(routes('admin', [LINUS, ADA_MEMBER, GRACE]))
  renderApp('/o/acme/settings')
  const table = await membersTable()

  expect(within(table).queryByRole('combobox', { name: 'Role of Linus Owner' })).not.toBeInTheDocument()
  expect(within(table).queryByRole('button', { name: 'Remove Linus Owner' })).not.toBeInTheDocument()
  const own = within(table).getByRole('combobox', { name: 'Role of Ada Lovelace' })
  expect(within(own).getAllByRole('option').map((option) => option.textContent)).toEqual(['Admin', 'Member'])
  expect(within(table).getByRole('button', { name: 'Remove Grace Hopper' })).toBeInTheDocument()
  expect(screen.getByLabelText('Organization name')).toBeInTheDocument()
})

test('inviting shows the note about the next sign-in and the pending invitation', async () => {
  const pending = [INVITATION]
  const invited = { ...INVITATION, id: '0190a000-0000-7000-8000-0000000000c2', email: 'kay@example.com', role: 'member' }
  let sent: unknown
  mockApi({
    ...routes(),
    [`GET /api/orgs/${ACME.id}/invitations`]: () => json(pending),
    [`POST /api/orgs/${ACME.id}/invitations`]: async (request) => {
      sent = await request.json()
      pending.push(invited as Schemas['InvitationOut'])
      return json(
        {
          status: 'invited',
          message: 'No email is sent. kay@example.com joins Acme the next time they sign in.',
          member: null,
          invitation: invited,
        },
        201,
      )
    },
  })
  renderApp('/o/acme/settings')

  const list = await screen.findByRole('list', { name: 'Pending invitations' })
  expect(within(list).getByText('new@example.com')).toBeInTheDocument()

  await userEvent.type(screen.getByLabelText('Email address'), 'kay@example.com')
  await userEvent.click(screen.getByRole('button', { name: 'Invite' }))

  expect(await screen.findByText(/kay@example.com joins Acme the next time they sign in/)).toBeInTheDocument()
  expect(sent).toEqual({ email: 'kay@example.com', role: 'member' })
  expect(await within(list).findByText('kay@example.com')).toBeInTheDocument()
  expect(screen.getByLabelText('Email address')).toHaveValue('')
})

test('an invitation error is shown', async () => {
  mockApi({
    ...routes(),
    [`POST /api/orgs/${ACME.id}/invitations`]: apiError(409, 'already_invited', 'new@example.com has already been invited'),
  })
  renderApp('/o/acme/settings')

  await userEvent.type(await screen.findByLabelText('Email address'), 'new@example.com')
  await userEvent.click(screen.getByRole('button', { name: 'Invite' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('new@example.com has already been invited')
})

test('revoking an invitation takes it out of the list', async () => {
  mockApi({
    ...routes(),
    [`DELETE /api/orgs/${ACME.id}/invitations/${INVITATION.id}`]: new Response(null, { status: 204 }),
  })
  renderApp('/o/acme/settings')

  await userEvent.click(await screen.findByRole('button', { name: 'Revoke invitation for new@example.com' }))

  expect(await screen.findByText('No pending invitations.')).toBeInTheDocument()
})

test('a plain member sees the page read-only', async () => {
  // No invitations route: a member must not ask for them (the API answers 403).
  const { [`GET /api/orgs/${ACME.id}/invitations`]: _unused, ...memberRoutes } = routes('member')
  void _unused
  mockApi(memberRoutes)
  renderApp('/o/acme/settings')
  const table = await membersTable()

  expect(screen.getByText('Only owners and admins can change these settings.')).toBeInTheDocument()
  expect(screen.getByText('Acme', { selector: 'p' })).toBeInTheDocument()
  expect(screen.queryByLabelText('Organization name')).not.toBeInTheDocument()
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  expect(within(table).getAllByText('Member', { selector: 'td' })).toHaveLength(2)
  expect(screen.queryByRole('button', { name: /^Remove/ })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Leave organization' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Invitations' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Email address')).not.toBeInTheDocument()
})
