import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { DashboardPage } from '../ui/DashboardPage'
import { getDebugConfig } from '../utils/debugApi'
import {
  getAdminSession,
  getAdminStats,
  listUsers,
  createUser,
  updateUser,
  deleteUser,
  type AdminUser,
} from '../utils/adminApi'
import { login, logout } from '../utils/api'

vi.mock('../utils/debugApi', () => ({
  DEBUG_BASE_URL: 'http://localhost:8000',
  getDebugConfig: vi.fn(),
  fetchOpenApiSpec: vi.fn(),
  listDebugRuns: vi.fn(),
  listDebugUnits: vi.fn(),
  getBehaviorDebugRun: vi.fn(),
  startBehaviorDebugRun: vi.fn(),
  trackBehaviorDebugTask: vi.fn(),
  explainBehaviorDebugRun: vi.fn(),
  generateDebugUnitInput: vi.fn(),
  runDebugUnit: vi.fn(),
  generateDebugApiPlaygroundInput: vi.fn(),
}))

vi.mock('../utils/adminApi', () => ({
  ADMIN_BASE_URL: 'http://localhost:8000',
  getAdminSession: vi.fn(),
  getAdminStats: vi.fn(),
  listUsers: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  deleteUser: vi.fn(),
}))

vi.mock('../utils/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../utils/api')>()),
  login: vi.fn(),
  logout: vi.fn(),
}))

const defaultConfig = { enabled: true, llm_explain_enabled: true, auth_mode: 'user_role', cookie_name: 'metarec_session' }
const adminSession = {
  ok: true,
  user: { id: 'user-1', email: 'admin@example.com', display_name: 'Admin', role: 'admin' },
}
const defaultStats = {
  tasks: { total: 3, completed: 2, errored: 1, success_rate: 0.6667 },
  tokens: { total_tokens: 1000, prompt_tokens: 600, completion_tokens: 400, cost_usd: 0.12, last_7d_total_tokens: 200 },
  users: { total: 5, registered: 3, guests: 2, new_registered_last_7d: 1 },
  conversations: { total_created: 4, active_sessions: 2 },
  feedback: { total: 0, satisfied: 0, unsatisfied: 0, satisfaction_ratio: null, reasons: [], domains: [] },
  generated_at: '2026-06-04T00:00:00Z',
}

function userRow(i: number, over: Partial<AdminUser> = {}): AdminUser {
  return {
    id: `user-${i}`,
    kind: 'registered',
    role: 'user',
    email: `u${i}@example.com`,
    display_name: `User ${i}`,
    status: 'active',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: `2026-01-0${(i % 9) + 1}T00:00:00Z`,
    last_seen_at: null,
    ...over,
  }
}

function renderDashboard() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>
  )
}

describe('frontend page: DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('fetch', vi.fn())
    vi.mocked(getDebugConfig).mockResolvedValue(defaultConfig)
    vi.mocked(getAdminSession).mockResolvedValue(adminSession)
    vi.mocked(getAdminStats).mockResolvedValue(defaultStats)
    vi.mocked(listUsers).mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
    vi.mocked(createUser).mockResolvedValue(userRow(99))
    vi.mocked(updateUser).mockResolvedValue(userRow(2))
    vi.mocked(deleteUser).mockResolvedValue(userRow(2, { status: 'deleted' }))
    vi.mocked(login).mockResolvedValue({} as any)
    vi.mocked(logout).mockResolvedValue({ success: true } as any)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders the Dashboard overview stats for an admin', async () => {
    renderDashboard()

    expect(await screen.findByRole('tab', { name: 'Dashboard' })).toBeInTheDocument()
    expect(await screen.findByText('Total done')).toBeInTheDocument()
    expect(screen.getByText('66.7%')).toBeInTheDocument()
    expect(screen.getByText('Active sessions')).toBeInTheDocument()
    expect(screen.getByText('No feedback collected yet.')).toBeInTheDocument()
  })

  it('switches the feedback card to a per-domain view via the dropdown', async () => {
    vi.mocked(getAdminStats).mockResolvedValue({
      ...defaultStats,
      feedback: {
        total: 5,
        satisfied: 3,
        unsatisfied: 2,
        satisfaction_ratio: 0.6,
        reasons: [
          { reason: 'too_far', label: 'Too far', count: 1 },
          { reason: 'already_known', label: 'Already know these', count: 1 },
        ],
        domains: [
          {
            domain: 'restaurant',
            total: 3,
            satisfied: 2,
            unsatisfied: 1,
            satisfaction_ratio: 0.6667,
            reasons: [{ reason: 'too_far', label: 'Too far', count: 1 }],
          },
          {
            domain: 'movie',
            total: 2,
            satisfied: 1,
            unsatisfied: 1,
            satisfaction_ratio: 0.5,
            reasons: [{ reason: 'already_known', label: 'Already know these', count: 1 }],
          },
        ],
      },
    })

    renderDashboard()

    // Defaults to the all-domains rollup: both reasons visible, options list domains.
    const select = (await screen.findByLabelText('Feedback domain')) as HTMLSelectElement
    expect(select.value).toBe('all')
    expect(screen.getByRole('option', { name: 'Restaurant (3)' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Movie (2)' })).toBeInTheDocument()
    // Histogram shows humanized labels, not raw codes.
    expect(screen.getByText('Too far')).toBeInTheDocument()
    expect(screen.getByText('Already know these')).toBeInTheDocument()
    expect(screen.queryByText('too_far')).not.toBeInTheDocument()

    // Switch to the Movie slice: only its reason remains.
    fireEvent.change(select, { target: { value: 'movie' } })
    expect(screen.getByText('50.0%')).toBeInTheDocument()
    expect(screen.getByText('Already know these')).toBeInTheDocument()
    expect(screen.queryByText('Too far')).not.toBeInTheDocument()
  })

  it('defaults the CMS user-type filter to registered', async () => {
    renderDashboard()
    fireEvent.click(await screen.findByRole('tab', { name: 'User Management' }))

    await waitFor(() => expect(listUsers).toHaveBeenCalled())
    expect(vi.mocked(listUsers).mock.calls.every(([p]) => p?.kind === 'registered')).toBe(true)
    expect((screen.getByLabelText('Filter by user type') as HTMLSelectElement).value).toBe('registered')
  })

  it('paginates the CMS user table (Next advances the offset)', async () => {
    vi.mocked(listUsers).mockImplementation(async (params = {}) => {
      const offset = params.offset ?? 0
      const all = Array.from({ length: 25 }, (_, i) => userRow(i))
      return { items: all.slice(offset, offset + 20), total: 25, limit: 20, offset }
    })

    renderDashboard()
    fireEvent.click(await screen.findByRole('tab', { name: 'User Management' }))

    expect(await screen.findByText(/Page 1 of 2/)).toBeInTheDocument()
    await waitFor(() => expect(listUsers).toHaveBeenCalled())

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))

    await waitFor(() =>
      expect(vi.mocked(listUsers).mock.calls.some(([p]) => p?.offset === 20)).toBe(true)
    )
    expect(await screen.findByText(/Page 2 of 2/)).toBeInTheDocument()
  })

  it('disables self role-downgrade and self-deactivate in the CMS', async () => {
    vi.mocked(listUsers).mockResolvedValue({
      items: [userRow(1, { id: 'user-1', email: 'admin@example.com', role: 'admin' }), userRow(2)],
      total: 2,
      limit: 20,
      offset: 0,
    })

    renderDashboard()
    fireEvent.click(await screen.findByRole('tab', { name: 'User Management' }))

    const selfCell = await screen.findByText('admin@example.com')
    const selfRow = selfCell.closest('tr') as HTMLElement
    expect(within(selfRow).getByRole('button', { name: 'Deactivate' })).toBeDisabled()

    fireEvent.click(within(selfRow).getByRole('button', { name: 'Edit' }))
    expect(await screen.findByRole('dialog', { name: 'Edit user' })).toBeInTheDocument()
    expect(screen.getByLabelText('Role')).toBeDisabled()
    expect(screen.getByLabelText('Status')).toBeDisabled()
  })

  it('sends expected_updated_at as the optimistic-concurrency token on edit', async () => {
    const target = userRow(2, { updated_at: '2026-05-05T10:00:00Z' })
    vi.mocked(listUsers).mockResolvedValue({ items: [target], total: 1, limit: 20, offset: 0 })

    renderDashboard()
    fireEvent.click(await screen.findByRole('tab', { name: 'User Management' }))

    const row = (await screen.findByText('u2@example.com')).closest('tr') as HTMLElement
    fireEvent.click(within(row).getByRole('button', { name: 'Edit' }))

    const dialog = await screen.findByRole('dialog', { name: 'Edit user' })
    fireEvent.change(within(dialog).getByLabelText('Status'), { target: { value: 'suspended' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(updateUser).toHaveBeenCalledTimes(1))
    expect(vi.mocked(updateUser).mock.calls[0]).toEqual([
      'user-2',
      expect.objectContaining({ expected_updated_at: '2026-05-05T10:00:00Z', status: 'suspended' }),
    ])
  })

  it('surfaces a reload notice when the server reports a 409 conflict', async () => {
    const target = userRow(2)
    vi.mocked(listUsers).mockResolvedValue({ items: [target], total: 1, limit: 20, offset: 0 })
    vi.mocked(updateUser).mockRejectedValueOnce(new Error('HTTP 409 Conflict: modified elsewhere'))

    renderDashboard()
    fireEvent.click(await screen.findByRole('tab', { name: 'User Management' }))

    const row = (await screen.findByText('u2@example.com')).closest('tr') as HTMLElement
    fireEvent.click(within(row).getByRole('button', { name: 'Edit' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit user' })
    fireEvent.change(within(dialog).getByLabelText('Display name'), { target: { value: 'Renamed' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(/modified elsewhere/i)).toBeInTheDocument()
  })
})
