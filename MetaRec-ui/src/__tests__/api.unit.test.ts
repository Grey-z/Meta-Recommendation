import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import { getTaskStatus, recommend } from '../utils/api'


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
})
