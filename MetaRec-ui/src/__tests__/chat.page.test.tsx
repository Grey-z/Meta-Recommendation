import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

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

  it('does not leak pending request UI into another conversation after switching', async () => {
    let resolveRecommend: (value: any) => void = () => {}
    const pendingRecommend = new Promise<any>(resolve => {
      resolveRecommend = resolve
    })
    vi.mocked(recommend).mockReturnValue(pendingRecommend)
    vi.mocked(getConversation).mockImplementation(async (_userId, conversationId) => ({
      id: conversationId,
      user_id: 'u-1',
      title: conversationId,
      model: 'RestRec',
      last_message: '',
      timestamp: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      active_branch_id: 'branch-main',
      branches: {},
      messages: [],
    }))

    const { rerender } = render(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-a"
        userId="u-1"
      />
    )
    await waitFor(() => expect(getConversation).toHaveBeenCalledWith('u-1', 'conv-a'))

    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'Need dinner' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('Thinking…')).toBeInTheDocument()

    rerender(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-b"
        userId="u-1"
      />
    )
    await waitFor(() => expect(getConversation).toHaveBeenCalledWith('u-1', 'conv-b'))
    expect(screen.queryByText('Thinking…')).not.toBeInTheDocument()

    await act(async () => {
      resolveRecommend({
        restaurants: [],
        confirmation_request: {
          message: 'Please confirm A preferences.',
          preferences: {},
          needs_confirmation: true,
        },
      })
      await pendingRecommend
    })

    expect(screen.queryByText('Please confirm A preferences.')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument()
  })

  it('restores full main-branch history when persisted messages have no parent links', async () => {
    vi.mocked(getConversation).mockResolvedValue({
      id: 'conv-unlinked',
      user_id: 'u-1',
      title: 'Unlinked Chat',
      model: 'RestRec',
      last_message: 'Second answer',
      timestamp: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      active_branch_id: 'branch-main',
      branches: {
        'branch-main': {
          id: 'branch-main',
          parent_branch_id: null,
          fork_from_message_id: null,
          root_message_id: 'u-1',
          head_message_id: 'a-2',
          title: 'Main',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      },
      messages: [
        {
          id: 'u-1',
          role: 'user',
          content: 'First request',
          branch_id: 'branch-main',
          parent_message_id: null,
          metadata: { message_id: 'u-1', branch_id: 'branch-main' },
        },
        {
          id: 'a-1',
          role: 'assistant',
          content: 'First answer',
          branch_id: 'branch-main',
          parent_message_id: null,
          metadata: { message_id: 'a-1', branch_id: 'branch-main' },
        },
        {
          id: 'u-2',
          role: 'user',
          content: 'Second request',
          branch_id: 'branch-main',
          parent_message_id: null,
          metadata: { message_id: 'u-2', branch_id: 'branch-main' },
        },
        {
          id: 'a-2',
          role: 'assistant',
          content: 'Second answer',
          branch_id: 'branch-main',
          parent_message_id: null,
          metadata: { message_id: 'a-2', branch_id: 'branch-main' },
        },
      ],
    })

    render(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-unlinked"
        userId="u-1"
      />
    )

    expect(await screen.findByText('First request')).toBeInTheDocument()
    expect(screen.getByText('First answer')).toBeInTheDocument()
    expect(screen.getByText('Second request')).toBeInTheDocument()
    expect(screen.getByText('Second answer')).toBeInTheDocument()
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

    const completedStatus = {
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
    }
    const onTaskCreated = vi.fn()

    const { rerender } = render(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-task"
        userId="u-1"
        onTaskCreated={onTaskCreated}
      />
    )

    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'Need spicy dinner for friends' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Please confirm your preferences.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() => expect(recommend).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(onTaskCreated).toHaveBeenCalledTimes(1))

    const task = onTaskCreated.mock.calls[0][0]
    expect(task).toMatchObject({
      taskId: 'task-123',
      userId: 'u-1',
      conversationId: 'conv-task',
      branchId: 'branch-main',
      source: 'confirmation_yes',
    })

    rerender(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-task"
        userId="u-1"
        onTaskCreated={onTaskCreated}
        backgroundTasks={[{ ...task, status: completedStatus }]}
      />
    )
    expect(await screen.findByText('Mock Bistro')).toBeInTheDocument()
    expect(getTaskStatus).not.toHaveBeenCalled()
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
      expect(setActiveConversationBranch).toHaveBeenCalledWith('u-1', 'conv-branch', 'branch-main', 'u-main')
    )
    expect(await screen.findByText('Original request')).toBeInTheDocument()
    expect(screen.getByText('Original assistant')).toBeInTheDocument()
    expect(screen.queryByText('Edited assistant')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous branch' })).toBeDisabled()
    expect(recommend).not.toHaveBeenCalled()
  })

  it('can switch back to the main branch when branch metadata is missing locally', async () => {
    const now = new Date().toISOString()
    vi.mocked(getConversation).mockResolvedValue({
      id: 'conv-missing-main-branch',
      user_id: 'u-1',
      title: 'Branch Chat',
      model: 'RestRec',
      last_message: 'Edited assistant',
      timestamp: now,
      updated_at: now,
      active_branch_id: 'branch-edit',
      branches: {
        'branch-edit': {
          id: 'branch-edit',
          parent_branch_id: 'branch-main',
          fork_from_message_id: 'u-main',
          root_message_id: 'u-edit',
          head_message_id: 'a-edit',
          title: 'Edit',
          created_at: now,
          updated_at: now,
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
        conversationId="conv-missing-main-branch"
        userId="u-1"
      />
    )

    expect(await screen.findByText('Edited request')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Previous branch' }))

    await waitFor(() =>
      expect(setActiveConversationBranch).toHaveBeenCalledWith(
        'u-1',
        'conv-missing-main-branch',
        'branch-main',
        'u-main'
      )
    )
    expect(await screen.findByText('Original request')).toBeInTheDocument()
    expect(screen.getByText('Original assistant')).toBeInTheDocument()
  })

  it('restores the selected branch for a conversation node from persisted branch state', async () => {
    const now = new Date().toISOString()
    vi.mocked(getConversation).mockResolvedValue({
      id: 'conv-selection',
      user_id: 'u-1',
      title: 'Branch Selection',
      model: 'RestRec',
      last_message: 'Original assistant',
      timestamp: now,
      updated_at: now,
      active_branch_id: 'branch-main',
      branch_selection_state: { 'u-main': 'branch-edit' },
      branches: {
        'branch-main': {
          id: 'branch-main',
          parent_branch_id: null,
          fork_from_message_id: null,
          root_message_id: 'u-main',
          head_message_id: 'a-main',
          title: 'Main',
          created_at: now,
          updated_at: now,
        },
        'branch-edit': {
          id: 'branch-edit',
          parent_branch_id: 'branch-main',
          fork_from_message_id: 'u-main',
          root_message_id: 'u-edit',
          head_message_id: 'a-edit',
          title: 'Edit',
          created_at: now,
          updated_at: now,
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
          content: 'Restored edited request',
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
          content: 'Restored edited assistant',
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
        conversationId="conv-selection"
        userId="u-1"
      />
    )

    expect(await screen.findByText('Restored edited request')).toBeInTheDocument()
    expect(screen.getByText('Restored edited assistant')).toBeInTheDocument()
    expect(screen.queryByText('Original assistant')).not.toBeInTheDocument()
  })

  it('restores nested selected branch state after switching into a parent branch', async () => {
    const now = new Date().toISOString()
    vi.mocked(getConversation).mockResolvedValue({
      id: 'conv-nested-selection',
      user_id: 'u-1',
      title: 'Nested Branch Selection',
      model: 'RestRec',
      last_message: 'Main assistant',
      timestamp: now,
      updated_at: now,
      active_branch_id: 'branch-main',
      branch_selection_state: { 'u-nested-main': 'branch-nested-edit' },
      branches: {
        'branch-main': {
          id: 'branch-main',
          parent_branch_id: null,
          fork_from_message_id: null,
          root_message_id: 'u-main',
          head_message_id: 'a-main',
          title: 'Main',
          created_at: now,
          updated_at: now,
        },
        'branch-alt': {
          id: 'branch-alt',
          parent_branch_id: 'branch-main',
          fork_from_message_id: 'u-main',
          root_message_id: 'u-alt',
          head_message_id: 'a-nested-main',
          title: 'Alt',
          created_at: now,
          updated_at: now,
        },
        'branch-nested-edit': {
          id: 'branch-nested-edit',
          parent_branch_id: 'branch-alt',
          fork_from_message_id: null,
          root_message_id: 'u-nested-edit',
          head_message_id: 'a-nested-edit',
          title: 'Nested Edit',
          created_at: now,
          updated_at: now,
        },
      },
      messages: [
        {
          id: 'u-main',
          role: 'user',
          content: 'Main request',
          branch_id: 'branch-main',
          parent_message_id: null,
          metadata: { message_id: 'u-main', branch_id: 'branch-main' },
        },
        {
          id: 'a-main',
          role: 'assistant',
          content: 'Main assistant',
          branch_id: 'branch-main',
          parent_message_id: 'u-main',
          metadata: { message_id: 'a-main', branch_id: 'branch-main', parent_message_id: 'u-main' },
        },
        {
          id: 'u-alt',
          role: 'user',
          content: 'Parent branch request',
          branch_id: 'branch-alt',
          parent_message_id: null,
          fork_from_message_id: 'u-main',
          revision_of_message_id: 'u-main',
          metadata: {
            message_id: 'u-alt',
            branch_id: 'branch-alt',
            fork_from_message_id: 'u-main',
            revision_of_message_id: 'u-main',
          },
        },
        {
          id: 'a-alt',
          role: 'assistant',
          content: 'Parent branch assistant',
          branch_id: 'branch-alt',
          parent_message_id: 'u-alt',
          metadata: { message_id: 'a-alt', branch_id: 'branch-alt', parent_message_id: 'u-alt' },
        },
        {
          id: 'u-nested-main',
          role: 'user',
          content: 'Nested original request',
          branch_id: 'branch-alt',
          parent_message_id: 'a-alt',
          metadata: { message_id: 'u-nested-main', branch_id: 'branch-alt', parent_message_id: 'a-alt' },
        },
        {
          id: 'a-nested-main',
          role: 'assistant',
          content: 'Nested original assistant',
          branch_id: 'branch-alt',
          parent_message_id: 'u-nested-main',
          metadata: { message_id: 'a-nested-main', branch_id: 'branch-alt', parent_message_id: 'u-nested-main' },
        },
        {
          id: 'u-nested-edit',
          role: 'user',
          content: 'Nested edited request',
          branch_id: 'branch-nested-edit',
          parent_message_id: 'a-alt',
          metadata: {
            message_id: 'u-nested-edit',
            branch_id: 'branch-nested-edit',
            parent_message_id: 'a-alt',
            time_travel: {
              mode: 'branch_fork',
              replay_from_message_id: 'u-nested-main',
              branch_id: 'branch-nested-edit',
            },
          },
        },
        {
          id: 'a-nested-edit',
          role: 'assistant',
          content: 'Nested edited assistant',
          branch_id: 'branch-nested-edit',
          parent_message_id: 'u-nested-edit',
          metadata: { message_id: 'a-nested-edit', branch_id: 'branch-nested-edit', parent_message_id: 'u-nested-edit' },
        },
      ],
    })

    render(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-nested-selection"
        userId="u-1"
      />
    )

    expect(await screen.findByText('Main request')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next branch' }))

    await waitFor(() =>
      expect(setActiveConversationBranch).toHaveBeenCalledWith('u-1', 'conv-nested-selection', 'branch-alt', 'u-main')
    )
    expect(await screen.findByText('Parent branch request')).toBeInTheDocument()
    expect(screen.getByText('Nested edited request')).toBeInTheDocument()
    expect(screen.getByText('Nested edited assistant')).toBeInTheDocument()
    expect(screen.queryByText('Nested original request')).not.toBeInTheDocument()

    const nestedBubble = screen.getByText('Nested edited request').closest('.bubble')
    if (!nestedBubble) {
      throw new Error('Expected nested edited request to render inside a message bubble')
    }
    expect(within(nestedBubble as HTMLElement).getByTitle('Branch versions')).toHaveTextContent('2/2')
    expect(within(nestedBubble as HTMLElement).getByRole('button', { name: 'Next branch' })).toBeDisabled()
  })

  it('keeps later edited branches available after switching to an older revision', async () => {
    const now = new Date().toISOString()
    vi.mocked(getConversation).mockResolvedValue({
      id: 'conv-branch-chain',
      user_id: 'u-1',
      title: 'Branch Chain',
      model: 'RestRec',
      last_message: 'Assistant 4',
      timestamp: now,
      updated_at: now,
      active_branch_id: 'branch-edit-4',
      branches: {
        'branch-main': {
          id: 'branch-main',
          parent_branch_id: null,
          fork_from_message_id: null,
          root_message_id: 'u-main',
          head_message_id: 'a-main',
          title: 'Main',
          created_at: now,
          updated_at: now,
        },
        'branch-edit-1': {
          id: 'branch-edit-1',
          parent_branch_id: 'branch-main',
          fork_from_message_id: 'u-main',
          root_message_id: 'u-edit-1',
          head_message_id: 'a-edit-1',
          title: 'Edit 1',
          created_at: now,
          updated_at: now,
        },
        'branch-edit-2': {
          id: 'branch-edit-2',
          parent_branch_id: 'branch-edit-1',
          fork_from_message_id: 'u-edit-1',
          root_message_id: 'u-edit-2',
          head_message_id: 'a-edit-2',
          title: 'Edit 2',
          created_at: now,
          updated_at: now,
        },
        'branch-edit-3': {
          id: 'branch-edit-3',
          parent_branch_id: 'branch-edit-2',
          fork_from_message_id: 'u-edit-2',
          root_message_id: 'u-edit-3',
          head_message_id: 'a-edit-3',
          title: 'Edit 3',
          created_at: now,
          updated_at: now,
        },
        'branch-edit-4': {
          id: 'branch-edit-4',
          parent_branch_id: 'branch-edit-3',
          fork_from_message_id: 'u-edit-3',
          root_message_id: 'u-edit-4',
          head_message_id: 'a-edit-4',
          title: 'Edit 4',
          created_at: now,
          updated_at: now,
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
          content: 'Assistant 0',
          branch_id: 'branch-main',
          parent_message_id: 'u-main',
          metadata: { message_id: 'a-main', branch_id: 'branch-main', parent_message_id: 'u-main' },
        },
        {
          id: 'u-edit-1',
          role: 'user',
          content: 'Edited request 1',
          branch_id: 'branch-edit-1',
          parent_message_id: null,
          fork_from_message_id: 'u-main',
          revision_of_message_id: 'u-main',
          metadata: {
            message_id: 'u-edit-1',
            branch_id: 'branch-edit-1',
            fork_from_message_id: 'u-main',
            revision_of_message_id: 'u-main',
          },
        },
        {
          id: 'a-edit-1',
          role: 'assistant',
          content: 'Assistant 1',
          branch_id: 'branch-edit-1',
          parent_message_id: 'u-edit-1',
          metadata: { message_id: 'a-edit-1', branch_id: 'branch-edit-1', parent_message_id: 'u-edit-1' },
        },
        {
          id: 'u-edit-2',
          role: 'user',
          content: 'Edited request 2',
          branch_id: 'branch-edit-2',
          parent_message_id: null,
          fork_from_message_id: 'u-edit-1',
          revision_of_message_id: 'u-edit-1',
          metadata: {
            message_id: 'u-edit-2',
            branch_id: 'branch-edit-2',
            fork_from_message_id: 'u-edit-1',
            revision_of_message_id: 'u-edit-1',
          },
        },
        {
          id: 'a-edit-2',
          role: 'assistant',
          content: 'Assistant 2',
          branch_id: 'branch-edit-2',
          parent_message_id: 'u-edit-2',
          metadata: { message_id: 'a-edit-2', branch_id: 'branch-edit-2', parent_message_id: 'u-edit-2' },
        },
        {
          id: 'u-edit-3',
          role: 'user',
          content: 'Edited request 3',
          branch_id: 'branch-edit-3',
          parent_message_id: null,
          fork_from_message_id: 'u-edit-2',
          revision_of_message_id: 'u-edit-2',
          metadata: {
            message_id: 'u-edit-3',
            branch_id: 'branch-edit-3',
            fork_from_message_id: 'u-edit-2',
            revision_of_message_id: 'u-edit-2',
          },
        },
        {
          id: 'a-edit-3',
          role: 'assistant',
          content: 'Assistant 3',
          branch_id: 'branch-edit-3',
          parent_message_id: 'u-edit-3',
          metadata: { message_id: 'a-edit-3', branch_id: 'branch-edit-3', parent_message_id: 'u-edit-3' },
        },
        {
          id: 'u-edit-4',
          role: 'user',
          content: 'Edited request 4',
          branch_id: 'branch-edit-4',
          parent_message_id: null,
          fork_from_message_id: 'u-edit-3',
          revision_of_message_id: 'u-edit-3',
          metadata: {
            message_id: 'u-edit-4',
            branch_id: 'branch-edit-4',
            fork_from_message_id: 'u-edit-3',
            revision_of_message_id: 'u-edit-3',
          },
        },
        {
          id: 'a-edit-4',
          role: 'assistant',
          content: 'Assistant 4',
          branch_id: 'branch-edit-4',
          parent_message_id: 'u-edit-4',
          metadata: { message_id: 'a-edit-4', branch_id: 'branch-edit-4', parent_message_id: 'u-edit-4' },
        },
      ],
    })

    render(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-branch-chain"
        userId="u-1"
      />
    )

    expect(await screen.findByText('Edited request 4')).toBeInTheDocument()
    expect(screen.getByTitle('Branch versions')).toHaveTextContent('5/5')
    expect(screen.getByRole('button', { name: 'Next branch' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Previous branch' }))

    await waitFor(() =>
      expect(setActiveConversationBranch).toHaveBeenCalledWith('u-1', 'conv-branch-chain', 'branch-edit-3', 'u-main')
    )
    expect(await screen.findByText('Edited request 3')).toBeInTheDocument()
    expect(screen.getByTitle('Branch versions')).toHaveTextContent('4/5')
    expect(screen.getByRole('button', { name: 'Next branch' })).not.toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Next branch' }))

    await waitFor(() =>
      expect(setActiveConversationBranch).toHaveBeenCalledWith('u-1', 'conv-branch-chain', 'branch-edit-4', 'u-main')
    )
    expect(await screen.findByText('Edited request 4')).toBeInTheDocument()
    expect(screen.getByTitle('Branch versions')).toHaveTextContent('5/5')
    expect(recommend).not.toHaveBeenCalled()
  })
})
