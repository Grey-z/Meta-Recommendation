import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { Chat } from '../ui/Chat'

import {
  addMessage,
  getConversation,
  getTaskStatus,
  recommend,
  setActiveConversationBranch,
} from '../utils/api'

vi.mock('../utils/api', () => ({
  recommend: vi.fn(),
  getTaskStatus: vi.fn(),
  getConversation: vi.fn(),
  addMessage: vi.fn(),
  setActiveConversationBranch: vi.fn(),
}))

vi.mock('../ui/MapModal', () => ({
  MapModal: ({ isOpen, placeName, placeLabel, coordinates }: any) => isOpen ? (
    <div role="dialog" aria-label="Map preview">
      {placeLabel}:{placeName}:{coordinates?.latitude},{coordinates?.longitude}
    </div>
  ) : null,
}))

vi.mock('../ui/ItineraryRouteMap', () => ({
  ItineraryMap: ({ snapshot }: any) => (
    <div aria-label="Provisional itinerary route map">
      snapshot-{snapshot?.revision}:{snapshot?.confirmed_nodes?.length}:{snapshot?.frontier_nodes?.length}
    </div>
  ),
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

  it('opens the composer mode dropup and toggles itinerary mode', () => {
    const onItineraryModeChange = vi.fn()
    const { rerender } = render(
      <Chat selectedTypes={[]} selectedFlavors={[]} itineraryMode={false} onItineraryModeChange={onItineraryModeChange} />
    )

    fireEvent.click(screen.getByRole('button', { name: 'Conversation modes' }))
    const option = screen.getByRole('menuitemcheckbox', { name: /Itinerary mode/i })
    expect(option).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(option)
    expect(onItineraryModeChange).toHaveBeenCalledWith(true)

    rerender(<Chat selectedTypes={[]} selectedFlavors={[]} itineraryMode onItineraryModeChange={onItineraryModeChange} />)
    expect(screen.getByPlaceholderText(/Describe the day to plan/i)).toBeInTheDocument()
    expect(screen.getByTitle('Itinerary mode is on')).toHaveClass('active')
  })

  it('closes the composer mode menu with Escape', () => {
    render(<Chat selectedTypes={[]} selectedFlavors={[]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Conversation modes' }))
    expect(screen.getByRole('menu', { name: 'Conversation modes' })).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('menu', { name: 'Conversation modes' })).not.toBeInTheDocument()
  })

  it('closes the composer mode menu when clicking outside the composer', () => {
    render(<Chat selectedTypes={[]} selectedFlavors={[]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Conversation modes' }))
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole('menu', { name: 'Conversation modes' })).not.toBeInTheDocument()
  })

  it('renders welcome state for an empty loaded conversation', async () => {
    render(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-empty"
        userId="u-1"
      />
    )

    await waitFor(() => expect(getConversation).toHaveBeenCalledWith('u-1', 'conv-empty'))
    expect(await screen.findByText('Welcome to MetaRec.')).toBeInTheDocument()
    expect(
      screen.getByText(/How can I help you today/i)
    ).toBeInTheDocument()
  })

  it('opens Mapbox integration for a generic attraction item with public coordinates', async () => {
    vi.mocked(getConversation).mockResolvedValue({
      id: 'conv-attraction-map',
      user_id: 'u-1',
      title: 'Attractions',
      model: 'AttractionRec',
      last_message: '',
      timestamp: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      active_branch_id: 'branch-main',
      branches: {},
      messages: [
        {
          id: 'a-attraction',
          role: 'assistant',
          content: 'Found an attraction',
          branch_id: 'branch-main',
          metadata: {
            message_id: 'a-attraction',
            branch_id: 'branch-main',
            type: 'recommendation',
            recommendation_data: {
              restaurants: [],
              items: [{
                id: 'attraction-1',
                domain: 'attraction',
                title: 'ArtScience Museum',
                subtitle: '6 Bayfront Ave',
                source: 'Google Maps',
                gps_coordinates: { latitude: 1.2863, longitude: 103.8593 },
              }],
            },
          },
        },
      ],
    })

    render(<Chat selectedTypes={[]} selectedFlavors={[]} conversationId="conv-attraction-map" userId="u-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'View on map' }))
    expect(screen.getByRole('dialog', { name: 'Map preview' })).toHaveTextContent(
      'Attraction:ArtScience Museum:1.2863,103.8593'
    )
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

  it('shows copy buttons for text/recommendation messages but not forms, copying results as Markdown', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })

    vi.mocked(getConversation).mockResolvedValue({
      id: 'conv-copy',
      user_id: 'u-1',
      title: 'Copy Chat',
      model: 'RestRec',
      last_message: '',
      timestamp: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      active_branch_id: 'branch-main',
      branches: {},
      messages: [
        {
          id: 'u-1',
          role: 'user',
          content: 'Find me food',
          branch_id: 'branch-main',
          metadata: { message_id: 'u-1', branch_id: 'branch-main' },
        },
        {
          id: 'a-rec',
          role: 'assistant',
          content: 'Found 1 restaurant recommendations: Markdown Bistro',
          branch_id: 'branch-main',
          metadata: {
            message_id: 'a-rec',
            branch_id: 'branch-main',
            type: 'recommendation',
            recommendation_data: {
              restaurants: [
                {
                  id: 'r-1',
                  name: 'Markdown Bistro',
                  cuisine: 'Thai',
                  area: 'Bugis',
                  price_per_person_sgd: '25-35',
                  rating: 4.5,
                  reviews_count: 120,
                  why: 'Great spicy fare',
                },
              ],
            },
          },
        },
        {
          id: 'a-generic-rec',
          role: 'assistant',
          content: 'Found 1 recommendations: Moonrise Film',
          branch_id: 'branch-main',
          metadata: {
            message_id: 'a-generic-rec',
            branch_id: 'branch-main',
            type: 'recommendation',
            recommendation_data: {
              restaurants: [],
              items: [
                {
                  id: 'movie-1',
                  domain: 'movie',
                  title: 'Moonrise Film',
                  subtitle: '2026',
                  description: 'A quiet science fiction story.',
                  rating: 8.1,
                  reviews_count: 1000,
                  source: 'TMDB',
                  tags: ['movie'],
                  why: 'Matches the requested mood.',
                },
              ],
            },
          },
        },
        {
          id: 'a-form',
          role: 'assistant',
          content: 'Please confirm your preferences',
          branch_id: 'branch-main',
          metadata: {
            message_id: 'a-form',
            branch_id: 'branch-main',
            type: 'confirmation',
            confirmation_request: {
              message: 'Please confirm your preferences',
              preferences: {},
              needs_confirmation: true,
            },
          },
        },
      ],
    })

    render(<Chat selectedTypes={[]} selectedFlavors={[]} conversationId="conv-copy" userId="u-1" />)

    expect(await screen.findByText('Find me food')).toBeInTheDocument()
    expect(screen.getByText('Moonrise Film')).toBeInTheDocument()
    expect(screen.getByText('TMDB')).toBeInTheDocument()

    // Three copyable messages (user text + two recommendations); the form has no button.
    const copyButtons = screen.getAllByLabelText('Copy message')
    expect(copyButtons).toHaveLength(3)

    // The recommendation copies as Markdown-ish text.
    fireEvent.click(copyButtons[1])
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1))
    const copied = writeText.mock.calls[0][0] as string
    expect(copied).toContain('**Markdown Bistro**')
    expect(copied).toContain('Cuisine: Thai')
    expect(copied).toContain('Rating: 4.5 (120 reviews)')

    fireEvent.click(copyButtons[2])
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2))
    const copiedGeneric = writeText.mock.calls[1][0] as string
    expect(copiedGeneric).toContain('Found 1 item:')
    expect(copiedGeneric).toContain('**Moonrise Film**')
    expect(copiedGeneric).toContain('Domain: movie')
    expect(copiedGeneric).toContain('Source: TMDB')
  })

  it('does not show feedback for client-generated result ids without a task target', async () => {
    vi.mocked(getConversation).mockResolvedValue({
      id: 'conv-client-result',
      user_id: 'u-1',
      title: 'Client result',
      model: 'RestRec',
      last_message: '',
      timestamp: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      active_branch_id: 'branch-main',
      branches: {},
      messages: [
        {
          id: 'a-client-result',
          role: 'assistant',
          content: 'Found 1 restaurant recommendations: Client Only Bistro',
          branch_id: 'branch-main',
          metadata: {
            message_id: 'a-client-result',
            branch_id: 'branch-main',
            type: 'recommendation',
            result_id: '33333333-3333-4333-8333-333333333333',
            client_generated_result_id: true,
            recommendation_data: {
              result_id: '33333333-3333-4333-8333-333333333333',
              restaurants: [
                {
                  id: 'r-client',
                  name: 'Client Only Bistro',
                  cuisine: 'Thai',
                  area: 'Bugis',
                  why: 'Generated before a backend result existed',
                },
              ],
              metadata: {
                result_id: '33333333-3333-4333-8333-333333333333',
                client_generated_result_id: true,
              },
            },
          },
        },
      ],
    })

    render(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-client-result"
        userId="u-1"
        isRegistered
      />,
    )

    expect(await screen.findByText('Client Only Bistro')).toBeInTheDocument()
    expect(screen.queryByText('Was this helpful?')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Helpful')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Not helpful')).not.toBeInTheDocument()
  })

  it('shows feedback for a non-restaurant result that has items and a result id', async () => {
    vi.mocked(getConversation).mockResolvedValue({
      id: 'conv-generic-feedback',
      user_id: 'u-1',
      title: 'Generic feedback',
      model: 'RestRec',
      last_message: '',
      timestamp: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      active_branch_id: 'branch-main',
      branches: {},
      messages: [
        {
          id: 'a-movie-result',
          role: 'assistant',
          content: 'Found 1 recommendations: Moonrise Film',
          branch_id: 'branch-main',
          metadata: {
            message_id: 'a-movie-result',
            branch_id: 'branch-main',
            type: 'recommendation',
            result_id: '44444444-4444-4444-8444-444444444444',
            recommendation_data: {
              result_id: '44444444-4444-4444-8444-444444444444',
              domain: 'movie',
              restaurants: [],
              items: [
                {
                  id: 'movie-1',
                  domain: 'movie',
                  title: 'Moonrise Film',
                  subtitle: '2026',
                  why: 'Matches the requested mood.',
                },
              ],
            },
          },
        },
      ],
    })

    render(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-generic-feedback"
        userId="u-1"
        isRegistered
      />,
    )

    // The gate now counts `.items`, not just `.restaurants`, so movie/music/book
    // results are feedback-eligible too.
    expect(await screen.findByText('Moonrise Film')).toBeInTheDocument()
    expect(screen.getByText('Was this helpful?')).toBeInTheDocument()
    expect(screen.getByLabelText('Helpful')).toBeInTheDocument()
    expect(screen.getByLabelText('Not helpful')).toBeInTheDocument()
  })


  it('threads request-time form selections into the confirm preferences', async () => {
    const hitlState = {
      node: 'collect_confirm_preferences',
      status: 'awaiting_confirmation',
      intent: 'query',
      query: 'recommend a movie',
      preferences: { domain: 'movie', query: 'recommend a movie' },
      needs_confirmation: true,
    }
    vi.mocked(getConversation).mockResolvedValue({
      id: 'conv-form',
      user_id: 'u-1',
      title: 'Movie',
      model: 'RestRec',
      last_message: '',
      timestamp: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      active_branch_id: 'branch-main',
      branches: {},
      messages: [
        {
          id: 'u-m',
          role: 'user',
          content: 'recommend a movie',
          branch_id: 'branch-main',
          metadata: { message_id: 'u-m', branch_id: 'branch-main' },
        },
        {
          id: 'a-conf',
          role: 'assistant',
          content: 'I detected this as a movie recommendation request. Is that correct?',
          branch_id: 'branch-main',
          metadata: {
            message_id: 'a-conf',
            branch_id: 'branch-main',
            type: 'confirmation',
            // Refine round: the dynamic form renders only when show_preferences is set.
            show_preferences: true,
            hitl_state: { ...hitlState },
            confirmation_request: {
              message: 'I detected this as a movie recommendation request. Is that correct?',
              preferences: { domain: 'movie', query: 'recommend a movie' },
              needs_confirmation: true,
              preference_form: {
                domain: 'movie',
                fields: [
                  { key: 'genres', label: 'Genres', type: 'multiselect', options: ['comedy', 'drama', 'science fiction'], required: true, placeholder: '' },
                ],
                missing_required: ['genres'],
                complete: false,
              },
            },
          },
        },
      ],
    } as any)
    vi.mocked(recommend).mockResolvedValue({ restaurants: [], llm_reply: 'ok', intent: 'chat' } as any)

    render(<Chat selectedTypes={[]} selectedFlavors={[]} conversationId="conv-form" userId="u-1" />)

    // The request-time form renders as genre chips.
    const comedy = await screen.findByRole('button', { name: 'comedy' })
    fireEvent.click(comedy)
    expect(comedy.getAttribute('aria-pressed')).toBe('true')

    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() => expect(recommend).toHaveBeenCalledTimes(1))
    const options = vi.mocked(recommend).mock.calls[0][5] as any
    expect(options.hitlState.preferences.genres).toEqual(['comedy'])
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

  it('does not dedupe distinct recommendation results with identical restaurants', async () => {
    const repeatedRestaurant = {
      id: 'r-repeat',
      name: 'Repeat Bistro',
      area: 'Bugis',
      cuisine: 'Thai',
      price_per_person_sgd: '20-30',
      why: 'Matches the request',
    }
    vi.mocked(recommend)
      .mockResolvedValueOnce({
        restaurants: [repeatedRestaurant],
        result_id: '11111111-1111-4111-8111-111111111111',
      })
      .mockResolvedValueOnce({
        restaurants: [repeatedRestaurant],
        result_id: '22222222-2222-4222-8222-222222222222',
      })

    render(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-repeat"
        userId="u-1"
        onMessageAdded={vi.fn()}
      />
    )
    await waitFor(() => expect(getConversation).toHaveBeenCalledWith('u-1', 'conv-repeat'))

    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'Need Thai food' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(addMessage).toHaveBeenCalledTimes(2))

    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'Try again with the same restaurant' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(addMessage).toHaveBeenCalledTimes(4))

    const assistantMetadatas = vi.mocked(addMessage).mock.calls
      .filter(call => call[2] === 'assistant')
      .map(call => call[4] as Record<string, any>)
    expect(assistantMetadatas).toHaveLength(2)
    expect(assistantMetadatas.map(metadata => metadata.result_id)).toEqual([
      '11111111-1111-4111-8111-111111111111',
      '22222222-2222-4222-8222-222222222222',
    ])
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

  it('renders live itinerary snapshots and ignores out-of-order revisions', async () => {
    const makeSnapshot = (revision: number) => ({
      schema_version: 'itinerary-planning-snapshot/v1',
      revision,
      phase: revision === 1 ? 'seed_retrieval' : 'provisional_solve',
      round: revision,
      planning_status: 'processing',
      confirmed_nodes: [{ id: 'a', title: 'Museum', status: 'confirmed', day_index: 0, lat: 1.3, lng: 103.8 }],
      frontier_nodes: [{ id: 'b', title: 'Park', status: 'candidate', lat: 1.31, lng: 103.81 }],
      retired_ids: [],
      edges: [{ from_id: 'a', to_id: 'b', status: 'estimated', mode: 'pt', duration_min: 12 }],
      days: [{ day_index: 0, date: '2026-08-03', start_time: '09:00', end_time_constraint: '17:00', current_end_time: '13:00', activity_min: 120, travel_min: 12, wait_min: 0 }],
      cost: { min: 20, max: 30, currency: 'SGD', budget_limit: 100, remaining: { min: 70, max: 80 } },
      uncertainty_count: 1,
      provider_calls: 2,
      provider_call_limit: 8,
    })
    const task = (revision: number) => ({
      taskId: 'task-live', userId: 'u-1', conversationId: 'conv-live', branchId: 'branch-main',
      createdAt: new Date().toISOString(),
      status: {
        task_id: 'task-live', status: 'processing', progress: 60, message: 'Building route',
        metadata: { planning_snapshot: makeSnapshot(revision) },
      },
    })
    const { container, rerender } = render(
      <Chat selectedTypes={[]} selectedFlavors={[]} conversationId="conv-live" userId="u-1" backgroundTasks={[task(2) as any]} />
    )

    expect(await screen.findByText('snapshot-2:1:1')).toBeInTheDocument()
    expect(screen.getByText('70–80 SGD')).toBeInTheDocument()
    expect(container.querySelector('.progress-bar')).not.toBeInTheDocument()

    rerender(
      <Chat selectedTypes={[]} selectedFlavors={[]} conversationId="conv-live" userId="u-1" backgroundTasks={[task(1) as any]} />
    )
    expect(screen.getByText('snapshot-2:1:1')).toBeInTheDocument()
    expect(screen.queryByText('snapshot-1:1:1')).not.toBeInTheDocument()
  })

  it('keeps the generic progress bar when a task has no itinerary snapshot', async () => {
    const { container } = render(
      <Chat
        selectedTypes={[]} selectedFlavors={[]} conversationId="conv-generic" userId="u-1"
        backgroundTasks={[{
          taskId: 'task-generic', userId: 'u-1', conversationId: 'conv-generic', branchId: 'branch-main',
          createdAt: new Date().toISOString(),
          status: { task_id: 'task-generic', status: 'processing', progress: 40, message: 'Ranking movies' },
        } as any]}
      />
    )
    expect(await screen.findByText('Processing your request...')).toBeInTheDocument()
    expect(container.querySelector('.progress-bar')).toBeInTheDocument()
    expect(screen.queryByLabelText('Provisional itinerary route map')).not.toBeInTheDocument()
  })

  it('guards confirmation against duplicate clicks before React state updates', async () => {
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
            details: 'Task ID: task-once',
          },
        ],
      })

    const onTaskCreated = vi.fn()

    render(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-confirm-once"
        userId="u-1"
        onTaskCreated={onTaskCreated}
      />,
    )

    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'Need spicy dinner for friends' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Please confirm your preferences.')).toBeInTheDocument()
    const confirmButton = screen.getByRole('button', { name: 'Confirm' })
    fireEvent.click(confirmButton)
    fireEvent.click(confirmButton)

    await waitFor(() => expect(recommend).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(onTaskCreated).toHaveBeenCalledTimes(1))
    expect(onTaskCreated.mock.calls[0][0].taskId).toBe('task-once')
  }, 10000)

  it('renders quick confirmation actions and submits the selected preference patch once', async () => {
    const confirmationRequest = {
      message: 'I can find a laptop under 2000 SGD. What will you mainly use it for?',
      preferences: { domain: 'product', query: 'Recommend a laptop under 2000 SGD' },
      needs_confirmation: true,
      preference_form: {
        domain: 'product',
        fields: [
          {
            key: 'query',
            label: 'What are you shopping for?',
            type: 'text',
            options: [],
            required: true,
            placeholder: 'e.g. laptop',
            value: 'Recommend a laptop under 2000 SGD',
          },
        ],
        missing_required: [],
        complete: true,
      },
      quick_actions: [
        {
          id: 'use_case_work',
          label: 'Work',
          value: 'work',
          preference_patch: { use_case: 'work' },
          clear_preference_keys: ['legacy_use_case'],
        },
        {
          id: 'use_case_study',
          label: 'Study',
          value: 'study',
          preference_patch: { use_case: 'study' },
        },
        {
          id: 'use_case_gaming',
          label: 'Gaming',
          value: 'gaming',
          preference_patch: { use_case: 'gaming' },
        },
      ],
    }
    vi.mocked(recommend)
      .mockResolvedValueOnce({
        restaurants: [],
        domain: 'product',
        confirmation_request: confirmationRequest,
        hitl_state: {
          node: 'collect_confirm_preferences',
          status: 'awaiting_confirmation',
          preferences: confirmationRequest.preferences,
          confirmation_request: confirmationRequest,
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
            details: 'Task ID: task-quick',
          },
        ],
      })

    const onTaskCreated = vi.fn()
    render(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-quick"
        userId="u-1"
        onTaskCreated={onTaskCreated}
      />,
    )

    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'Recommend a laptop under 2000 SGD' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText(confirmationRequest.message)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Work' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Study' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Gaming' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument()
    expect(screen.queryByText('What are you shopping for?')).not.toBeInTheDocument()

    const workButton = screen.getByRole('button', { name: 'Work' })
    fireEvent.click(workButton)
    fireEvent.click(workButton)

    await waitFor(() => expect(recommend).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(onTaskCreated).toHaveBeenCalledTimes(1))
    const selectedQuery = vi.mocked(recommend).mock.calls[1][0]
    const options = vi.mocked(recommend).mock.calls[1][5] as any
    expect(selectedQuery).toBe('Work')
    expect(options.hitlState.action).toBe('confirm')
    expect(options.hitlState.preferences.use_case).toBe('work')
    expect(options.hitlState.clear_preference_keys).toEqual(['legacy_use_case'])
    expect(options.hitlState.selected_quick_action).toMatchObject({
      id: 'use_case_work',
      value: 'work',
    })
  }, 10000)

  it('sends a backend reject on Not Satisfied and renders the domain refine form', async () => {
    // Round 1 is light: a message + quick actions, no dynamic form.
    const round1 = {
      message: 'I can find a laptop under 2000 SGD. What will you mainly use it for?',
      preferences: { domain: 'product', query: 'Recommend a laptop under 2000 SGD' },
      needs_confirmation: true,
      quick_actions: [
        { id: 'use_case_work', label: 'Work', value: 'work', preference_patch: { use_case: 'work' } },
        { id: 'use_case_study', label: 'Study', value: 'study', preference_patch: { use_case: 'study' } },
      ],
    }
    // Round 2 (backend reject): the domain-aware refine form, pre-filled.
    const round2 = {
      message: 'No problem — adjust the details below and confirm.',
      preferences: { domain: 'product', query: 'Recommend a laptop under 2000 SGD' },
      needs_confirmation: true,
      preference_form: {
        domain: 'product',
        fields: [
          { key: 'use_case', label: 'Use case', type: 'text', options: [], required: false, placeholder: 'e.g. work', value: '' },
        ],
        missing_required: [],
        complete: true,
      },
    }
    vi.mocked(recommend)
      .mockResolvedValueOnce({
        restaurants: [], domain: 'product', intent: 'query',
        confirmation_request: round1,
        hitl_state: {
          node: 'collect_confirm_preferences', status: 'awaiting_confirmation',
          preferences: round1.preferences, confirmation_request: round1, needs_confirmation: true,
        },
      } as any)
      .mockResolvedValueOnce({
        restaurants: [], domain: 'product', intent: 'confirmation_no',
        confirmation_request: round2,
        hitl_state: {
          node: 'collect_confirm_preferences', status: 'awaiting_clarification',
          preferences: round2.preferences, confirmation_request: round2, needs_confirmation: true,
        },
      } as any)
      .mockResolvedValueOnce({
        restaurants: [],
        domain: 'product',
        intent: 'confirmation_yes',
        llm_reply: 'Confirmed refinement',
      } as any)

    render(
      <Chat selectedTypes={[]} selectedFlavors={[]} conversationId="conv-quick-reject" userId="u-1" />,
    )

    fireEvent.change(screen.getByPlaceholderText(/Ask for recommendations/i), {
      target: { value: 'Recommend a laptop under 2000 SGD' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    // Round 1: quick action buttons render; the dynamic form does not.
    expect(await screen.findByText(round1.message)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Work' })).toBeInTheDocument()
    expect(screen.queryByText('Use case')).not.toBeInTheDocument()

    // Not Satisfied issues a backend reject (a second recommend call) and renders
    // the returned domain form — no legacy restaurant panel.
    fireEvent.click(screen.getByRole('button', { name: 'Not Satisfied' }))
    await waitFor(() => expect(recommend).toHaveBeenCalledTimes(2))
    expect(await screen.findByText(round2.message)).toBeInTheDocument()
    expect(await screen.findByText('Use case')).toBeInTheDocument()
    expect(screen.queryByText('Current Preferences')).not.toBeInTheDocument()

    const rejectOptions = vi.mocked(recommend).mock.calls[1][5] as any
    expect(rejectOptions.hitlState.action).toBe('reject')

    fireEvent.change(screen.getByLabelText('Use case'), {
      target: { value: 'video editing' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(recommend).toHaveBeenCalledTimes(3))
    const confirmOptions = vi.mocked(recommend).mock.calls[2][5] as any
    expect(confirmOptions.hitlState.action).toBe('confirm')
    expect(confirmOptions.hitlState.preferences.use_case).toBe('video editing')
  }, 10000)

  it('regenerates an unchanged edited message on a new branch', async () => {
    const now = new Date().toISOString()
    vi.mocked(getConversation).mockResolvedValue({
      id: 'conv-edit-same',
      user_id: 'u-1',
      title: 'Edit Same',
      model: 'RestRec',
      last_message: 'Original assistant',
      timestamp: now,
      updated_at: now,
      active_branch_id: 'branch-main',
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
      ],
    })
    vi.mocked(recommend).mockResolvedValue({
      restaurants: [],
      llm_reply: 'Regenerated assistant',
      intent: 'chat',
    })

    render(
      <Chat
        selectedTypes={[]}
        selectedFlavors={[]}
        conversationId="conv-edit-same"
        userId="u-1"
        onMessageAdded={vi.fn()}
      />
    )

    expect(await screen.findByText('Original request')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Edit message' }))
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate from edited message' }))

    await waitFor(() => expect(recommend).toHaveBeenCalledTimes(1))
    const userMetadata = vi.mocked(addMessage).mock.calls.find(call => call[2] === 'user')?.[4] as Record<string, any>
    expect(userMetadata.branch_id).toEqual(expect.stringMatching(/^branch-client-/))
    expect(userMetadata.fork_from_message_id).toBe('u-main')
    expect(userMetadata.revision_of_message_id).toBe('u-main')
    expect(userMetadata.parent_message_id).toBeNull()

    const recommendOptions = vi.mocked(recommend).mock.calls[0][5] as Record<string, any>
    expect(recommendOptions.timeTravel).toMatchObject({
      replayFromMessageId: 'u-main',
      branchId: userMetadata.branch_id,
      timeTravelMode: 'branch_fork',
    })
    expect(await screen.findByText('Regenerated assistant')).toBeInTheDocument()
  })


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

})
