import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import {
  ensureAuthSession,
  getDomainPreferenceForm,
  getPublicMapboxToken,
  getTaskStatus,
  guestLogin,
  recommend,
  register,
  updatePreferences,
  watchTaskStatus,
} from '../utils/api'


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
        items: [
          {
            id: 'movie-1',
            domain: 'movie',
            title: 'Quiet Signal',
            rating: 8.2,
            source: 'TMDB',
          },
        ],
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
    expect(response.items?.[0]?.title).toBe('Quiet Signal')
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

  it('uses the bundled public Mapbox token without a config request', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>

    await expect(getPublicMapboxToken(' pk.bundled ')).resolves.toBe('pk.bundled')
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('loads the public Mapbox token from backend runtime config', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ mapboxToken: ' pk.runtime ' }),
    })

    await expect(getPublicMapboxToken('')).resolves.toBe('pk.runtime')
    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/config',
      { credentials: 'include' },
    )
  })

  it('recommend should send the explicit itinerary mode flag', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ restaurants: [], items: [], intent: 'query' }),
    })

    await recommend('somewhere scenic', 'u-1', [], 'conv-1', false, { itineraryMode: true })

    const [, init] = mockFetch.mock.calls[0]
    const body = JSON.parse((init as RequestInit).body as string)
    expect(body.itinerary_mode).toBe(true)
  })

  it('recommend should include a non-time-travel branch scope when provided', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        restaurants: [],
        llm_reply: 'scoped',
        intent: 'chat',
      }),
    })

    await recommend(
      'same branch request',
      'u-1',
      [{ role: 'user', content: 'same branch request' }],
      'conv-1',
      false,
      { scopeBranchId: 'branch-main' },
    )

    const [, init] = mockFetch.mock.calls[0]
    const body = JSON.parse((init as RequestInit).body as string)
    expect(body).toMatchObject({
      branch_id: 'branch-main',
    })
    expect(body).not.toHaveProperty('time_travel_mode')
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

  it('getDomainPreferenceForm should encode the domain path segment', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        domain: 'movie/tv picks',
        fields: [],
        missing_required: [],
        complete: true,
      }),
    })

    await getDomainPreferenceForm('movie/tv picks')

    const [url, init] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/api/domains/movie%2Ftv%20picks/preference-form')
    expect((init as RequestInit).credentials).toBe('include')
  })

  it('guestLogin should send device id with credentials included', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        user: {
          id: 'u-session',
          kind: 'guest',
          role: 'user',
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
            role: 'user',
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

  it('watchTaskStatus streams status frames over SSE and settles on completion', () => {
    const instances: FakeEventSource[] = []
    class FakeEventSource {
      static readonly CONNECTING = 0
      static readonly OPEN = 1
      static readonly CLOSED = 2
      url: string
      withCredentials: boolean
      readyState = FakeEventSource.OPEN
      onmessage: ((event: { data: string }) => void) | null = null
      onerror: (() => void) | null = null
      constructor(url: string, init?: { withCredentials?: boolean }) {
        this.url = url
        this.withCredentials = Boolean(init?.withCredentials)
        instances.push(this)
      }
      emit(payload: unknown) {
        this.onmessage?.({ data: JSON.stringify(payload) })
      }
      close() {
        this.readyState = FakeEventSource.CLOSED
      }
    }
    vi.stubGlobal('EventSource', FakeEventSource)

    const onStatus = vi.fn()
    const onSettled = vi.fn()
    const stop = watchTaskStatus('t-7', 'u-1', 'c-1', { onStatus, onSettled })

    const es = instances[0]
    expect(es.url).toContain('/api/status/t-7/stream')
    expect(es.url).toContain('user_id=u-1')
    expect(es.url).toContain('conversation_id=c-1')
    expect(es.withCredentials).toBe(true)

    es.emit({ task_id: 't-7', status: 'processing', progress: 40, message: 'searching' })
    expect(onStatus).toHaveBeenCalledWith(expect.objectContaining({ status: 'processing', progress: 40 }))
    expect(onSettled).not.toHaveBeenCalled()

    es.emit({
      task_id: 't-7',
      status: 'completed',
      progress: 100,
      message: 'ready',
      result: { restaurants: [], thinking_steps: [] },
    })
    expect(onStatus).toHaveBeenCalledWith(expect.objectContaining({ status: 'completed' }))
    expect(onSettled).toHaveBeenCalledTimes(1)
    // The stream is torn down once the task settles.
    expect(es.readyState).toBe(FakeEventSource.CLOSED)

    stop()
  })

  it('watchTaskStatus falls back to polling when EventSource is unavailable', async () => {
    // jsdom provides no EventSource, so the watcher must keep working via getTaskStatus.
    expect(typeof EventSource).toBe('undefined')
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        task_id: 't-8',
        status: 'completed',
        progress: 100,
        message: 'ready',
        result: { restaurants: [], thinking_steps: [] },
      }),
    })

    const onStatus = vi.fn()
    const onSettled = vi.fn()
    const stop = watchTaskStatus('t-8', 'u-1', 'c-1', { onStatus, onSettled })

    // Allow the immediate poll's promise chain to resolve.
    await new Promise(resolve => setTimeout(resolve, 0))
    await new Promise(resolve => setTimeout(resolve, 0))

    expect(onStatus).toHaveBeenCalledWith(expect.objectContaining({ status: 'completed' }))
    expect(onSettled).toHaveBeenCalledTimes(1)
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/api/status/t-8')
    stop()
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
