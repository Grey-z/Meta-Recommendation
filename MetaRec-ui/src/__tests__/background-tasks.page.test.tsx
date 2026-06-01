import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { MetaRecPage } from '../ui/MetaRecPage'
import {
  addMessage,
  ensureAuthSession,
  getConversation,
  getConversationPreferences,
  getConversations,
  getTaskStatus,
  recommend,
  setActiveConversationBranch,
  updateConversation,
  updateConversationPreferences,
} from '../utils/api'

vi.mock('../utils/deviceId', () => ({
  getDeviceId: () => 'device-test',
}))

vi.mock('../utils/api', () => ({
  updateConversationPreferences: vi.fn(),
  getConversationPreferences: vi.fn(),
  getConversations: vi.fn(),
  getConversation: vi.fn(),
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
  updateConversation: vi.fn(),
  addMessage: vi.fn(),
  getTaskStatus: vi.fn(),
  ensureAuthSession: vi.fn(),
  login: vi.fn(),
  register: vi.fn(),
  logout: vi.fn(),
  recommend: vi.fn(),
  recommendStream: vi.fn(),
  setActiveConversationBranch: vi.fn(),
}))

describe('frontend page: background recommendation tasks', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.clearAllMocks()
    vi.mocked(ensureAuthSession).mockResolvedValue({
      user: {
        id: 'u-1',
        kind: 'guest',
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
    vi.mocked(updateConversationPreferences).mockResolvedValue({ preferences: {} })
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
    expect(await screen.findByText('Recommendation ready')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open' }))
    await waitFor(() => expect(getConversation).toHaveBeenCalledWith('u-1', 'conv-a'))
  })
})
