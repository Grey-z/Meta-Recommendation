import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { DashboardPage } from '../ui/DashboardPage'
import {
  fetchOpenApiSpec,
  generateDebugApiPlaygroundInput,
  generateDebugUnitInput,
  getBehaviorDebugRun,
  getDebugConfig,
  listDebugRuns,
  listDebugUnits,
  runDebugUnit,
  startBehaviorDebugRun,
  trackBehaviorDebugTask,
  explainBehaviorDebugRun,
} from '../utils/debugApi'
import { getAdminSession, getAdminStats, listUsers } from '../utils/adminApi'
import { login, logout } from '../utils/api'

vi.mock('../utils/debugApi', () => ({
  DEBUG_BASE_URL: 'http://localhost:8000',
  explainBehaviorDebugRun: vi.fn(),
  fetchOpenApiSpec: vi.fn(),
  generateDebugApiPlaygroundInput: vi.fn(),
  generateDebugUnitInput: vi.fn(),
  getBehaviorDebugRun: vi.fn(),
  getDebugConfig: vi.fn(),
  listDebugRuns: vi.fn(),
  listDebugUnits: vi.fn(),
  runDebugUnit: vi.fn(),
  startBehaviorDebugRun: vi.fn(),
  trackBehaviorDebugTask: vi.fn(),
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

const defaultConfig = {
  enabled: true,
  llm_explain_enabled: true,
  auth_mode: 'user_role',
  cookie_name: 'metarec_session',
}

const defaultSession = {
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

const adminAuthResponse = {
  user: { id: 'user-1', kind: 'registered', role: 'admin', email: 'admin@example.com', display_name: 'Admin', status: 'active' },
  session: { id: 'sess-1', user_id: 'user-1', anonymous_device_id: null, status: 'active', expires_at: '2026-01-01T12:00:00Z' },
}

const defaultRunSummary = {
  runs: [
    {
      id: 'run-1',
      kind: 'behavior',
      status: 'completed',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:01Z',
      event_count: 2,
      error: null,
    },
  ],
}

const defaultRunDetail = {
  id: 'run-1',
  kind: 'behavior',
  status: 'completed',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:01Z',
  config: {},
  events: [],
  artifacts: {},
  explanation: null,
  error: null,
  job_running: false,
}

const defaultUnitSpec = {
  units: [
    {
      name: 'intent_parser',
      description: 'Parse intent',
      function_name: 'parse_intent',
      input_schema: { type: 'object', properties: { query: { type: 'string' } } },
      expected_io: { type: 'object' },
      sample_input: { query: 'hello' },
    },
  ],
}

const defaultOpenApi = {
  openapi: '3.0.0',
  paths: {
    '/health': {
      get: {
        summary: 'Health check',
        operationId: 'health_check',
        responses: { '200': { description: 'ok' } },
      },
    },
  },
}

function renderDashboard() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>
  )
}

describe('frontend page: DashboardPage debug arena', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('fetch', vi.fn())

    vi.mocked(getDebugConfig).mockResolvedValue(defaultConfig)
    vi.mocked(getAdminSession).mockResolvedValue(defaultSession)
    vi.mocked(getAdminStats).mockResolvedValue(defaultStats)
    vi.mocked(listUsers).mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
    vi.mocked(login).mockResolvedValue(adminAuthResponse)
    vi.mocked(logout).mockResolvedValue({ success: true } as any)
    vi.mocked(listDebugRuns).mockResolvedValue(defaultRunSummary)
    vi.mocked(listDebugUnits).mockResolvedValue(defaultUnitSpec)
    vi.mocked(getBehaviorDebugRun).mockResolvedValue(defaultRunDetail)
    vi.mocked(startBehaviorDebugRun).mockResolvedValue({ ok: true, run_id: 'run-2', status: 'queued' })
    vi.mocked(trackBehaviorDebugTask).mockResolvedValue({ ok: true, run_id: 'run-track', status: 'queued' })
    vi.mocked(explainBehaviorDebugRun).mockResolvedValue({ ok: true, mode: 'nl_explain', explanation: {} })
    vi.mocked(generateDebugUnitInput).mockResolvedValue({ input_data: { query: 'generated' }, validation_errors: [] })
    vi.mocked(runDebugUnit).mockResolvedValue({
      ok: true,
      unit: { name: 'intent_parser', function_name: 'parse_intent' },
      input_source: 'manual',
      input_data: { query: 'hello' },
      validation_errors: [],
      result: { ok: true, output: { intent: 'query', confidence: 0.9 }, duration_ms: 5 },
    })
    vi.mocked(generateDebugApiPlaygroundInput).mockResolvedValue({
      ok: true,
      mode: 'schema',
      input_data: { path_params: {}, query_params: {}, body: {} },
      validation_errors: [],
    })
    vi.mocked(fetchOpenApiSpec).mockResolvedValue(defaultOpenApi)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('supports admin login flow and can create a behavior trace run', async () => {
    vi.mocked(getAdminSession).mockRejectedValueOnce(new Error('HTTP 401 Authentication required'))

    renderDashboard()

    expect(await screen.findByRole('heading', { name: 'Admin sign in' })).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'admin@example.com' } })
    fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'sup3rsecret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Login' }))

    await waitFor(() => expect(login).toHaveBeenCalledWith('admin@example.com', 'sup3rsecret'))

    // Debug tabs are top-level dashboard tabs; open the arena via the tab.
    fireEvent.click(await screen.findByRole('tab', { name: 'Task Process Tracker' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Create Trace Run' }))
    await waitFor(() => expect(startBehaviorDebugRun).toHaveBeenCalledTimes(1))
    expect(vi.mocked(startBehaviorDebugRun).mock.calls[0][0]).toEqual(
      expect.objectContaining({ use_online_agent: false, auto_confirm: true })
    )
  })

  it('shows access denied when a non-admin session reaches the dashboard', async () => {
    vi.mocked(getAdminSession).mockRejectedValue(new Error('HTTP 403 Admin role required'))

    renderDashboard()

    expect(await screen.findByRole('heading', { name: 'Access denied' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Task Process Tracker' })).not.toBeInTheDocument()
  })

  it('hides the debug tabs when DEBUG_UI_ENABLED is off but keeps Dashboard + CMS', async () => {
    vi.mocked(getDebugConfig).mockResolvedValue({ ...defaultConfig, enabled: false })

    renderDashboard()

    expect(await screen.findByRole('tab', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'User Management' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Task Process Tracker' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'API Playground' })).not.toBeInTheDocument()
  })

  it('runs unit test bench and renders execution output', async () => {
    renderDashboard()

    fireEvent.click(await screen.findByRole('tab', { name: 'Unit Test Bench' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Run Unit' }))

    await waitFor(() => expect(runDebugUnit).toHaveBeenCalledTimes(1))
    expect(vi.mocked(runDebugUnit).mock.calls[0][0]).toEqual(
      expect.objectContaining({ unit_name: 'intent_parser', input_mode: 'manual' })
    )
    expect(await screen.findByText('Function Output (raw JSON)')).toBeInTheDocument()
    expect(screen.getByText('Execution Time')).toBeInTheDocument()
  })

  it('runs API playground request and renders API output summary', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: {
        forEach: (cb: (value: string, key: string) => void) => cb('application/json', 'content-type'),
        get: (key: string) => (key.toLowerCase() === 'content-type' ? 'application/json' : null),
      },
      text: async () => '{"status":"ok"}',
    })

    renderDashboard()

    fireEvent.click(await screen.findByRole('tab', { name: 'API Playground' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Run API' }))

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1))
    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:8000/health')
    expect(await screen.findByText('Request succeeded')).toBeInTheDocument()
    expect(screen.getByText('HTTP Status')).toBeInTheDocument()
  })
})
