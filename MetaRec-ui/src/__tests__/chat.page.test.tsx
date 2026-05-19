import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { Chat } from '../ui/Chat'

import {
  addMessage,
  getConversation,
  getTaskStatus,
  recommend,
  recommendStream,
  setActiveConversationBranch,
} from '../utils/api'

vi.mock('../utils/api', () => ({
  recommend: vi.fn(),
  recommendStream: vi.fn(),
  getTaskStatus: vi.fn(),
  getConversation: vi.fn(),
  addMessage: vi.fn(),
  setActiveConversationBranch: vi.fn(),
}))

describe('frontend page: Chat', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getConversation).mockResolvedValue({
      id: 'conv-1',
      user_id: 'u-1',
      title: 'Chat',
      model: 'RestRec',
      last_message: '',
      timestamp: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      messages: [],
    })
    vi.mocked(addMessage).mockResolvedValue({ success: true, message: 'ok' })
    vi.mocked(setActiveConversationBranch).mockResolvedValue({
      id: 'conv-1',
      user_id: 'u-1',
      title: 'Chat',
      model: 'RestRec',
      last_message: '',
      timestamp: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      messages: [],
      active_branch_id: 'branch-main',
      branches: {},
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders welcome state and composer', () => {
    render(<Chat selectedTypes={[]} selectedFlavors={[]} />)

    expect(screen.getByText('Welcome to MetaRec.')).toBeInTheDocument()
    expect(
      screen.getByPlaceholderText(/Ask for recommendations/i)
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
  })

  it('renders graph-aware llm reply returned by process endpoint', async () => {
    vi.mocked(recommend).mockResolvedValue({
      restaurants: [],
      llm_reply: 'Sure, let me help.',
      intent: 'chat',
    })

    render(<Chat selectedTypes={[]} selectedFlavors={[]} />)
    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'hi there' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(recommend).toHaveBeenCalledTimes(1))
    expect(recommendStream).not.toHaveBeenCalled()
    expect(await screen.findByText('Sure, let me help.')).toBeInTheDocument()
  })

  it('persists assistant messages with the same parent ids used by the visible branch', async () => {
    vi.mocked(getConversation).mockResolvedValue({
      id: 'conv-ids',
      user_id: 'u-1',
      title: 'Chat',
      model: 'RestRec',
      last_message: '',
      timestamp: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      messages: [],
      active_branch_id: 'branch-main',
      branches: {},
    })
    vi.mocked(recommend).mockResolvedValue({
      restaurants: [],
      llm_reply: 'Sure, let me help.',
      intent: 'chat',
    })

    render(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-ids"
        userId="u-1"
        onMessageAdded={vi.fn()}
      />
    )
    await waitFor(() => expect(getConversation).toHaveBeenCalledWith('u-1', 'conv-ids'))

    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'hi there' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(addMessage).toHaveBeenCalledTimes(2))
    const userMetadata = vi.mocked(addMessage).mock.calls[0][4] as Record<string, any>
    const assistantMetadata = vi.mocked(addMessage).mock.calls[1][4] as Record<string, any>

    expect(userMetadata.message_id).toEqual(expect.stringMatching(/^client-/))
    expect(userMetadata.branch_id).toBe('branch-main')
    expect(assistantMetadata.message_id).toEqual(expect.stringMatching(/^client-/))
    expect(assistantMetadata.parent_message_id).toBe(userMetadata.message_id)
  })

  it('handles confirmation to task polling and renders recommendation result', async () => {
    vi.mocked(recommend)
      .mockResolvedValueOnce({
        restaurants: [],
        confirmation_request: {
          message: 'Please confirm your preferences.',
          preferences: {
            restaurant_types: ['casual'],
            flavor_profiles: ['spicy'],
            dining_purpose: 'friends',
            budget_range: { min: 20, max: 60, currency: 'SGD', per: 'person' },
            location: 'Chinatown',
          },
          needs_confirmation: true,
        },
      })
      .mockResolvedValueOnce({
        restaurants: [],
        thinking_steps: [
          {
            step: 'start_processing',
            description: 'Starting recommendation process...',
            status: 'thinking',
            details: 'Task ID: task-123',
          },
        ],
      })

    vi.mocked(getTaskStatus).mockResolvedValue({
      task_id: 'task-123',
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
            why: 'Great fit for spicy group dining',
          },
        ],
        thinking_steps: [],
      },
    })

    render(<Chat selectedTypes={[]} selectedFlavors={[]} />)

    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'Need spicy dinner for friends' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Please confirm your preferences.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() => expect(recommend).toHaveBeenCalledTimes(2))

    await new Promise((resolve) => setTimeout(resolve, 1200))

    await waitFor(() =>
      expect(getTaskStatus).toHaveBeenCalledWith('task-123', 'default', 'default')
    )
    expect(await screen.findByText('Mock Bistro')).toBeInTheDocument()
    await new Promise((resolve) => setTimeout(resolve, 2200))
    expect(getTaskStatus).toHaveBeenCalledTimes(1)
  }, 10000)

  it('rebuilds visible history from the selected conversation branch', async () => {
    vi.mocked(getConversation).mockResolvedValue({
      id: 'conv-branch',
      user_id: 'u-1',
      title: 'Branch Chat',
      model: 'RestRec',
      last_message: 'Edited assistant',
      timestamp: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      active_branch_id: 'branch-edit',
      branches: {
        'branch-main': {
          id: 'branch-main',
          parent_branch_id: null,
          fork_from_message_id: null,
          root_message_id: 'u-main',
          head_message_id: 'a-main',
          title: 'Main',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        'branch-edit': {
          id: 'branch-edit',
          parent_branch_id: 'branch-main',
          fork_from_message_id: 'u-main',
          root_message_id: 'u-edit',
          head_message_id: 'a-edit',
          title: 'Edit',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      },
      messages: [
        {
          id: 'u-main',
          role: 'user',
          content: 'Original request',
          branch_id: 'branch-main',
          parent_message_id: null,
          metadata: { message_id: 'u-main', branch_id: 'branch-main' },
        },
        {
          id: 'a-main',
          role: 'assistant',
          content: 'Original assistant',
          branch_id: 'branch-main',
          parent_message_id: 'u-main',
          metadata: { message_id: 'a-main', branch_id: 'branch-main', parent_message_id: 'u-main' },
        },
        {
          id: 'u-edit',
          role: 'user',
          content: 'Edited request',
          branch_id: 'branch-edit',
          parent_message_id: null,
          fork_from_message_id: 'u-main',
          revision_of_message_id: 'u-main',
          metadata: {
            message_id: 'u-edit',
            branch_id: 'branch-edit',
            fork_from_message_id: 'u-main',
            revision_of_message_id: 'u-main',
          },
        },
        {
          id: 'a-edit',
          role: 'assistant',
          content: 'Edited assistant',
          branch_id: 'branch-edit',
          parent_message_id: 'u-edit',
          metadata: { message_id: 'a-edit', branch_id: 'branch-edit', parent_message_id: 'u-edit' },
        },
      ],
    })

    render(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-branch"
        userId="u-1"
      />
    )

    expect(await screen.findByText('Edited request')).toBeInTheDocument()
    expect(screen.getByText('Edited assistant')).toBeInTheDocument()
    expect(screen.queryByText('Original assistant')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next branch' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Previous branch' }))

    await waitFor(() =>
      expect(setActiveConversationBranch).toHaveBeenCalledWith('u-1', 'conv-branch', 'branch-main')
    )
    expect(await screen.findByText('Original request')).toBeInTheDocument()
    expect(screen.getByText('Original assistant')).toBeInTheDocument()
    expect(screen.queryByText('Edited assistant')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous branch' })).toBeDisabled()
    expect(recommend).not.toHaveBeenCalled()
  })
})
