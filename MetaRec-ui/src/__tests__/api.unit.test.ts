import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import { ensureAuthSession, getTaskStatus, guestLogin, recommend, register, updatePreferences } from '../utils/api'


describe('frontend unit: api utils', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('recommend should send expected payload and return parsed response', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        restaurants: [],
        llm_reply: 'hello',
        intent: 'chat',
      }),
    })

    const response = await recommend(
      'need spicy food',
      'u-1',
      [{ role: 'user', content: 'history' }],
      'conv-1',
      true
    )

    expect(response.intent).toBe('chat')
    expect(mockFetch).toHaveBeenCalledTimes(1)

    const [url, init] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/api/process')
    const body = JSON.parse((init as RequestInit).body as string)
    expect(body).toEqual({
      query: 'need spicy food',
      user_id: 'u-1',
      conversation_history: [{ role: 'user', content: 'history' }],
      conversation_id: 'conv-1',
      use_online_agent: true,
    })
  })

  it('recommend should throw friendly network error when fetch fails', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockRejectedValue(new TypeError('Failed to fetch'))

    await expect(recommend('hi')).rejects.toThrow('Network error: Cannot connect to backend')
  })

  it('recommend should include optional time travel payload', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        restaurants: [],
        llm_reply: 'regenerated',
        intent: 'chat',
        domain: 'restaurant',
      }),
    })

    await recommend(
      'edited request',
      'u-1',
      [{ role: 'user', content: 'edited request' }],
      'conv-1',
      false,
      {
        sourceMessageId: 'm-new',
        replayFromMessageId: 'm-old',
        branchId: 'b-new',
        timeTravelMode: 'linear_regenerate',
      }
    )

    const [, init] = mockFetch.mock.calls[0]
    const body = JSON.parse((init as RequestInit).body as string)
    expect(body).toMatchObject({
      source_message_id: 'm-new',
      replay_from_message_id: 'm-old',
      branch_id: 'b-new',
      time_travel_mode: 'linear_regenerate',
    })
  })

  it('recommend should throw contract error when response shape is invalid', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        restaurants: 'not-an-array',
      }),
    })

    await expect(recommend('invalid shape')).rejects.toThrow(
      'API contract validation failed for /api/process'
    )
  })

  it('getTaskStatus should include user and conversation query parameters', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        task_id: 't-1',
        status: 'processing',
        progress: 30,
        message: 'running',
      }),
    })

    const status = await getTaskStatus('t-1', 'u-2', 'c-2')
    expect(status.status).toBe('processing')

    const [url] = mockFetch.mock.calls[0]
    const calledUrl = String(url)
    expect(calledUrl).toContain('/api/status/t-1')
    expect(calledUrl).toContain('user_id=u-2')
    expect(calledUrl).toContain('conversation_id=c-2')
  })

  it('updatePreferences should normalize profile preference payload for the API', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        message: 'Preferences updated successfully',
        preferences: {
          restaurant_types: ['casual'],
          flavor_profiles: ['spicy'],
          dining_purpose: 'friends',
          budget_range: { min: 25, max: 70, currency: 'SGD', per: 'person' },
          location: 'Chinatown',
        },
      }),
    })

    await updatePreferences({
      restaurant_types: ['casual'],
      flavor_profiles: ['spicy'],
      dining_purpose: 'friends',
      budget_range: { min: 25, max: 70, currency: 'SGD', per: 'person' },
      location: 'Chinatown',
    }, 'u-3')

    const [url, init] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/api/update-preferences')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      user_id: 'u-3',
      restaurantTypes: ['casual'],
      flavorProfiles: ['spicy'],
      diningPurpose: 'friends',
      budgetRange: { min: 25, max: 70, currency: 'SGD', per: 'person' },
      location: 'Chinatown',
    })
  })

  it('guestLogin should send device id with credentials included', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        user: {
          id: 'u-session',
          kind: 'guest',
          status: 'active',
        },
        session: {
          id: 's-session',
          user_id: 'u-session',
          anonymous_device_id: 'd-session',
          status: 'active',
          expires_at: '2026-06-30T00:00:00Z',
        },
      }),
    })

    const auth = await guestLogin('browser-device')
    expect(auth.user.id).toBe('u-session')

    const [url, init] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/api/auth/guest')
    expect((init as RequestInit).credentials).toBe('include')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ device_id: 'browser-device' })
  })

  it('ensureAuthSession should fall back to guest login when no cookie session exists', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        text: async () => 'missing session',
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          user: {
            id: 'u-new-guest',
            kind: 'guest',
            status: 'active',
          },
          session: {
            id: 's-new-guest',
            user_id: 'u-new-guest',
            status: 'active',
            expires_at: '2026-06-30T00:00:00Z',
          },
        }),
      })

    const auth = await ensureAuthSession('browser-device')

    expect(auth.user.id).toBe('u-new-guest')
    expect(mockFetch).toHaveBeenCalledTimes(2)
    expect(String(mockFetch.mock.calls[0][0])).toContain('/api/auth/session')
    expect((mockFetch.mock.calls[0][1] as RequestInit).credentials).toBe('include')
    expect(String(mockFetch.mock.calls[1][0])).toContain('/api/auth/guest')
  })

  it('register should expose only the backend detail message on auth errors', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      ok: false,
      status: 400,
      statusText: 'Bad Request',
      text: async () => JSON.stringify({ detail: 'password must be at least 8 characters' }),
    })

    let error: Error | null = null
    try {
      await register('test@example.com', 'short')
    } catch (caught) {
      error = caught as Error
    }

    expect(error?.message).toBe('password must be at least 8 characters')
  })
})
