import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { MetaRecPage } from '../ui/MetaRecPage'
import {
  addMessage,
  createConversation,
  ensureAuthSession,
  getConversation,
  getConversationPreferences,
  getConversations,
  getTaskStatus,
  getUserPreferences,
  recommend,
  setActiveConversationBranch,
  updateConversation,
  updateConversationPreferences,
  updatePreferences,
} from '../utils/api'

vi.mock('../utils/deviceId', () => ({
  getDeviceId: () => 'device-test',
}))

vi.mock('../utils/api', () => {
  const getTaskStatus = vi.fn()
  // Stand in for the real SSE-backed watcher: bridge to the mocked getTaskStatus
  // so existing lifecycle assertions (polled args, completion persistence) hold.
  const watchTaskStatus = vi.fn((taskId: string, userId: string, conversationId: string, handlers: any) => {
    let cancelled = false
    const run = async () => {
      if (cancelled) return
      try {
        const status = await getTaskStatus(taskId, userId, conversationId)
        if (cancelled) return
        handlers.onStatus(status)
        if (status.status === 'completed' || status.status === 'error') {
          handlers.onSettled?.()
          return
        }
      } catch {
        // ignore and retry on the next tick
      }
      if (!cancelled) setTimeout(run, 50)
    }
    void run()
    return () => { cancelled = true }
  })
  return {
    updateConversationPreferences: vi.fn(),
    getConversationPreferences: vi.fn(),
    getUserPreferences: vi.fn(),
    updatePreferences: vi.fn(),
    getConversations: vi.fn(),
    getConversation: vi.fn(),
    createConversation: vi.fn(),
    deleteConversation: vi.fn(),
    updateConversation: vi.fn(),
    addMessage: vi.fn(),
    getTaskStatus,
    watchTaskStatus,
    ensureAuthSession: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    recommend: vi.fn(),
    setActiveConversationBranch: vi.fn(),
  }
})

describe('frontend page: background recommendation tasks', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.clearAllMocks()
    vi.mocked(ensureAuthSession).mockResolvedValue({
      user: {
        id: 'u-1',
        kind: 'guest',
        role: 'user',
        status: 'active',
      },
      session: {
        id: 's-1',
        user_id: 'u-1',
        status: 'active',
        expires_at: new Date(Date.now() + 86400000).toISOString(),
      },
    })
    vi.mocked(getConversations).mockResolvedValue([
      {
        id: 'conv-a',
        title: 'First chat',
        model: 'RestRec',
        last_message: 'First',
        timestamp: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        message_count: 1,
      },
      {
        id: 'conv-b',
        title: 'Second chat',
        model: 'RestRec',
        last_message: 'Second',
        timestamp: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        message_count: 1,
      },
    ])
    vi.mocked(getConversation).mockImplementation(async (_userId, conversationId) => ({
      id: conversationId,
      user_id: 'u-1',
      title: conversationId === 'conv-a' ? 'First chat' : 'Second chat',
      model: 'RestRec',
      last_message: conversationId === 'conv-a' ? 'First' : 'Second',
      timestamp: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      active_branch_id: 'branch-main',
      branches: {},
      messages: [
        {
          id: `${conversationId}-user`,
          role: 'user',
          content: conversationId === 'conv-a' ? 'First request' : 'Second request',
          branch_id: 'branch-main',
          metadata: { message_id: `${conversationId}-user`, branch_id: 'branch-main' },
        },
      ],
    }))
    vi.mocked(getConversationPreferences).mockResolvedValue({ preferences: {} })
    vi.mocked(getUserPreferences).mockResolvedValue({
      user_id: 'u-1',
      preferences: {},
    })
    vi.mocked(updateConversationPreferences).mockResolvedValue({ preferences: {} })
    vi.mocked(updatePreferences).mockResolvedValue({
      message: 'Preferences updated successfully',
      preferences: {},
    })
    vi.mocked(updateConversation).mockResolvedValue({} as any)
    vi.mocked(addMessage).mockResolvedValue({ success: true, message: 'ok' })
    vi.mocked(setActiveConversationBranch).mockResolvedValue({} as any)
  })

  afterEach(() => {
    window.localStorage.clear()
  })

  it('keeps polling after switching chats and saves the completed result to the original conversation', async () => {
    vi.mocked(recommend).mockResolvedValue({
      restaurants: [],
      thinking_steps: [
        {
          step: 'start_processing',
          description: 'Starting recommendation process...',
          status: 'thinking',
          details: 'Task ID: task-bg-1',
        },
      ],
    })
    vi.mocked(getTaskStatus).mockResolvedValue({
      task_id: 'task-bg-1',
      status: 'completed',
      progress: 100,
      message: 'Recommendations ready!',
      result: {
        restaurants: [
          {
            id: 'r-1',
            name: 'Mock Bistro',
            area: 'Chinatown',
            cuisine: 'Sichuan',
            price_per_person_sgd: '20-30',
            flavor_match: ['Spicy'],
            purpose_match: ['Friends'],
            why: 'Great fit',
          },
        ],
        thinking_steps: [],
      },
    })

    render(<MetaRecPage />)

    expect(await screen.findByText('First chat')).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'Need spicy dinner' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(recommend).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getByText('Second chat'))
    await waitFor(() => expect(getConversation).toHaveBeenCalledWith('u-1', 'conv-b'))

    await waitFor(() => {
      expect(getTaskStatus).toHaveBeenCalledWith('task-bg-1', 'u-1', 'conv-a')
      const savedResultCall = vi.mocked(addMessage).mock.calls.find(call => (
        call[0] === 'u-1'
        && call[1] === 'conv-a'
        && call[2] === 'assistant'
        && String(call[3]).includes('Mock Bistro')
      ))
      expect(savedResultCall?.[4]).toMatchObject({
        type: 'recommendation',
        task_id: 'task-bg-1',
        branch_id: 'branch-main',
      })
    }, { timeout: 3000 })
    // The completion notification is rendered only because we switched chats; under
    // parallel-suite load its render can lag past the default 1000ms (it still lives
    // well within the 5000ms auto-dismiss), so wait with the same budget as above.
    expect(await screen.findByText('Recommendation ready', undefined, { timeout: 3000 })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open' }))
    await waitFor(() => expect(getConversation).toHaveBeenCalledWith('u-1', 'conv-a'))
  })

  it('shows a completed generic recommendation in the active conversation without reloading or switching', async () => {
    vi.mocked(recommend).mockResolvedValue({
      restaurants: [],
      thinking_steps: [
        {
          step: 'start_processing',
          description: 'Starting recommendation process...',
          status: 'thinking',
          details: 'Task ID: task-bg-2',
        },
      ],
    })
    vi.mocked(getTaskStatus).mockResolvedValue({
      task_id: 'task-bg-2',
      status: 'completed',
      progress: 100,
      message: 'Recommendations ready!',
      result: {
        restaurants: [],
        items: [
          {
            id: 'movie-inline-1',
            domain: 'movie',
            title: 'Inline Movie',
            subtitle: '2026',
            rating: 8.4,
            reviews_count: 900,
            source: 'TMDB',
            why: 'Great fit',
          },
        ],
        thinking_steps: [],
      },
    })

    render(<MetaRecPage />)

    expect(await screen.findByText('First chat')).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'Need spicy dinner' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(recommend).toHaveBeenCalledTimes(1))

    // Stay in the same conversation: the polled result must surface inline,
    // rather than only after a reload / conversation switch re-fetches it.
    await waitFor(
      () => expect(screen.getByText('Inline Movie')).toBeInTheDocument(),
      { timeout: 3000 },
    )

    // And it is persisted to the conversation it belongs to (for reload parity).
    await waitFor(() => {
      const savedResultCall = vi.mocked(addMessage).mock.calls.find(call => (
        call[0] === 'u-1'
        && call[1] === 'conv-a'
        && call[2] === 'assistant'
        && String(call[3]).includes('Inline Movie')
      ))
      expect(savedResultCall?.[4]).toMatchObject({
        type: 'recommendation',
        task_id: 'task-bg-2',
      })
    }, { timeout: 3000 })
  })

  it('keeps a normal pending conversation request running after switching chats', async () => {
    let resolveRecommend: (value: any) => void = () => {}
    const pendingRecommend = new Promise<any>(resolve => {
      resolveRecommend = resolve
    })
    vi.mocked(recommend).mockReturnValue(pendingRecommend)

    render(<MetaRecPage />)

    expect(await screen.findByText('First chat')).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'Can you help me plan dinner?' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(recommend).toHaveBeenCalledTimes(1))
    expect(await screen.findByLabelText('Conversation request running')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Second chat'))
    await waitFor(() => expect(getConversation).toHaveBeenCalledWith('u-1', 'conv-b'))

    resolveRecommend({
      restaurants: [],
      llm_reply: 'Sure, I can help with dinner.',
      intent: 'chat',
    })

    await waitFor(() => {
      const savedReplyCall = vi.mocked(addMessage).mock.calls.find(call => (
        call[0] === 'u-1'
        && call[1] === 'conv-a'
        && call[2] === 'assistant'
        && call[3] === 'Sure, I can help with dinner.'
      ))
      expect(savedReplyCall?.[4]).toMatchObject({
        branch_id: 'branch-main',
        source: 'background_request',
      })
    }, { timeout: 3000 })
    expect(await screen.findByText('Conversation reply ready')).toBeInTheDocument()
  })

  it('shows an actionable note when a strict cuisine/dish finds no match', async () => {
    vi.mocked(recommend).mockResolvedValue({
      restaurants: [],
      thinking_steps: [
        {
          step: 'start_processing',
          description: 'Starting recommendation process...',
          status: 'thinking',
          details: 'Task ID: task-nomatch',
        },
      ],
    })
    vi.mocked(getTaskStatus).mockResolvedValue({
      task_id: 'task-nomatch',
      status: 'completed',
      progress: 100,
      message: 'Recommendations ready!',
      result: {
        restaurants: [],
        thinking_steps: [],
        metadata: {
          food_intent_no_match: true,
          food_intent_widened: false,
          food_intent_terms: ['pho', 'vietnamese'],
          searched_location: 'Pioneer MRT',
        },
      },
    })

    render(<MetaRecPage />)

    expect(await screen.findByText('First chat')).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'Pho near Pioneer MRT' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(recommend).toHaveBeenCalledTimes(1))

    // No bare empty state / hard error: an actionable, location-aware note instead.
    await waitFor(
      () => expect(screen.getByText(/Want me to widen the area/i)).toBeInTheDocument(),
      { timeout: 3000 },
    )
    expect(screen.getByText('Pioneer MRT')).toBeInTheDocument()
  })

  it('labels widened results as nearby when the exact area had no match', async () => {
    vi.mocked(recommend).mockResolvedValue({
      restaurants: [],
      thinking_steps: [
        {
          step: 'start_processing',
          description: 'Starting recommendation process...',
          status: 'thinking',
          details: 'Task ID: task-widen',
        },
      ],
    })
    vi.mocked(getTaskStatus).mockResolvedValue({
      task_id: 'task-widen',
      status: 'completed',
      progress: 100,
      message: 'Recommendations ready!',
      result: {
        restaurants: [
          {
            id: 'r-w1',
            name: 'Pho Street',
            area: 'Jurong Point',
            cuisine: 'Vietnamese',
            price_per_person_sgd: '10-15',
            why: 'Closest pho nearby',
          },
        ],
        thinking_steps: [],
        metadata: {
          food_intent_no_match: false,
          food_intent_widened: true,
          food_intent_terms: ['pho', 'vietnamese'],
          searched_location: 'Pioneer MRT',
        },
      },
    })

    render(<MetaRecPage />)

    expect(await screen.findByText('First chat')).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'Pho near Pioneer MRT' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(recommend).toHaveBeenCalledTimes(1))

    // The nearby results are shown, clearly labeled as widened from the exact area.
    await waitFor(
      () => expect(screen.getByText(/showing the closest/i)).toBeInTheDocument(),
      { timeout: 3000 },
    )
    expect(screen.getByText('Pho Street')).toBeInTheDocument()
  })

  it('loads profile preferences after creating a new conversation', async () => {
    vi.mocked(createConversation).mockResolvedValue({
      id: 'conv-new',
      user_id: 'u-1',
      title: 'New Chat',
      model: 'RestRec',
      last_message: '',
      timestamp: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      active_branch_id: 'branch-main',
      branches: {},
      messages: [],
    })
    vi.mocked(getUserPreferences).mockResolvedValue({
      user_id: 'u-1',
      preferences: {
        restaurant_types: ['casual'],
        flavor_profiles: ['spicy'],
        dining_purpose: 'friends',
        budget_range: { min: 45, max: 90, currency: 'SGD', per: 'person' },
        location: 'Chinatown',
      },
    })

    render(<MetaRecPage />)

    expect(await screen.findByText('First chat')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /\+ New Chat/i }))
    await waitFor(() => expect(createConversation).toHaveBeenCalledWith('u-1', {
      title: 'New Chat',
      model: 'RestRec',
    }))

    fireEvent.click(screen.getByRole('button', { name: /Show Preferences/i }))
    await waitFor(() => expect(getUserPreferences).toHaveBeenCalledWith('u-1'))

    expect((document.getElementById('budget-min') as HTMLInputElement).value).toBe('45')
    expect((document.getElementById('budget-max') as HTMLInputElement).value).toBe('90')
    expect((document.getElementById('purpose-select') as HTMLSelectElement).value).toBe('friends')
    expect((document.getElementById('location-select') as HTMLSelectElement).value).toBe('Chinatown')
  })
})
