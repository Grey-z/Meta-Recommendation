import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Itinerary } from '../contracts/api-types'
import { ItineraryView } from '../ui/ItineraryView'
import { getTaskResult, refineItinerary } from '../utils/api'

vi.mock('../utils/api', () => ({
  ApiConflictError: class ApiConflictError extends Error {},
  getTaskResult: vi.fn(),
  refineItinerary: vi.fn(),
}))

const itinerary = (revision = 1, title = 'National Gallery'): Itinerary => ({
  location: 'Singapore',
  start_time: '10:00',
  service_date: '2026-08-01',
  timezone: 'Asia/Singapore',
  revision,
  slots: [
    {
      slot_index: 0,
      label: 'Morning gallery',
      domain: 'attraction',
      slot_role: 'activity',
      time: '10:00',
      chosen: { id: 'a1', title, subtitle: '1 St Andrew Road', rating: 4.7, lat: 1.29, lng: 103.85 },
      alternates: [{ id: 'a2', title: 'Asian Civilisations Museum', lat: 1.288, lng: 103.851 }],
    },
    {
      slot_index: 1,
      label: 'Lunch',
      domain: 'restaurant',
      time: '12:30',
      chosen: { id: 'r1', title: 'The Coconut Club', subtitle: 'Beach Road', lat: 1.3, lng: 103.86 },
      alternates: [],
    },
  ],
  legs: [{ from_index: 0, to_index: 1, mode: 'walk', duration_min: 12, distance_km: 0.8, source: 'onemap', cache: 'hit' }],
  totals: { end_time: '14:00', total_travel_min: 12, budget_note: 'Estimated food spend 25 SGD/person' },
  validation: { status: 'valid', violations: [], warnings: [] },
})

describe('ItineraryView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getTaskResult).mockResolvedValue({ restaurants: [], items: [], metadata: { itinerary: itinerary() } } as any)
  })

  it('embeds the route map at the top without modal controls', () => {
    render(<ItineraryView initialItinerary={itinerary()} />)

    const map = screen.getByLabelText('Itinerary route map')
    const policy = screen.getByLabelText('Planning policy')
    expect(map.compareDocumentPosition(policy) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show route' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Transport modes')).toHaveTextContent('WalkMRTBusDrive')
  })

  it('renders per-leg transit steps with MRT/bus badges and boarding stops', () => {
    const withSteps: Itinerary = {
      ...itinerary(),
      legs: [{
        from_index: 0, to_index: 1, mode: 'pt', duration_min: 22, distance_km: 6, source: 'onemap',
        steps: [
          { mode: 'walk', distance_m: 200 },
          { mode: 'bus', service: '199', from: 'Marina Bay', to: 'Buona Vista', num_stops: 5 },
          { mode: 'subway', service: 'EW', line_name: 'East West Line', from: 'Buona Vista', to: 'Outram Park', num_stops: 4 },
        ],
      }],
    }
    render(<ItineraryView initialItinerary={withSteps} taskId="task-1" userId="user-1" conversationId="conv-1" />)

    expect(screen.getByText('🚌 Bus 199')).toBeInTheDocument()
    expect(screen.getByText('🚇 EW')).toBeInTheDocument()
    expect(screen.getByText('Marina Bay → Buona Vista · 5 stops')).toBeInTheDocument()
    expect(screen.getByText('Buona Vista → Outram Park · 4 stops')).toBeInTheDocument()
    expect(screen.getByText('🚶 Walk 200 m')).toBeInTheDocument()
  })

  it('renders stops, ETA provenance, totals, and refreshes the durable result', async () => {
    vi.mocked(getTaskResult).mockResolvedValue({ restaurants: [], items: [], metadata: { itinerary: itinerary(2, 'Refreshed Gallery') } } as any)
    render(<ItineraryView initialItinerary={itinerary()} taskId="task-1" userId="user-1" conversationId="conv-1" />)

    expect(screen.getByText('12 min')).toBeInTheDocument()
    expect(screen.getByText('OneMap cached')).toBeInTheDocument()
    expect(screen.getByText('14:00')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Refreshed Gallery')).toBeInTheDocument())
    expect(getTaskResult).toHaveBeenCalledWith('task-1', 'user-1', 'conv-1')
  })

  it('submits a swap with the current revision and updates the stop', async () => {
    const updated = itinerary(2, 'Asian Civilisations Museum')
    vi.mocked(refineItinerary).mockResolvedValue({ result: {} as any, itinerary: updated })
    render(<ItineraryView initialItinerary={itinerary()} taskId="task-1" userId="user-1" conversationId="conv-1" />)

    fireEvent.change(screen.getByLabelText('Swap Morning gallery'), { target: { value: 'a2' } })
    await waitFor(() => expect(refineItinerary).toHaveBeenCalledWith('task-1', expect.objectContaining({
      slot_index: 0,
      selected_item_id: 'a2',
      expected_revision: 1,
    })))
    expect(screen.getByRole('heading', { name: 'Asian Civilisations Museum' })).toBeInTheDocument()
  })

  it('submits free-text refinement without affecting other stops', async () => {
    const updated = itinerary(2, 'Quiet Sculpture Garden')
    vi.mocked(refineItinerary).mockResolvedValue({ result: {} as any, itinerary: updated })
    render(<ItineraryView initialItinerary={itinerary()} taskId="task-1" userId="user-1" conversationId="conv-1" />)

    fireEvent.click(screen.getAllByRole('button', { name: /Refine/ })[0])
    fireEvent.change(screen.getByPlaceholderText('e.g. somewhere quieter'), { target: { value: 'somewhere quieter' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))

    await waitFor(() => expect(refineItinerary).toHaveBeenCalledWith('task-1', expect.objectContaining({ prompt: 'somewhere quieter' })))
    expect(screen.getByText('The Coconut Club')).toBeInTheDocument()
  })

  it('shows dynamic cost uncertainty and persists estimate acceptance', async () => {
    const dynamic: Itinerary = {
      ...itinerary(),
      planning_status: 'needs_refinement',
      cost_summary: { min: 25, max: null, currency: 'SGD', budget_limit: 100, budget_status: 'indeterminate' },
      uncertainties: [{ code: 'cost_unknown' }, { code: 'opening_hours_unknown' }],
      totals: { ...itinerary().totals, total_activity_min: 180, total_wait_min: 15 },
    }
    const accepted = { ...dynamic, revision: 2, planning_status: 'accepted_with_uncertainties' }
    vi.mocked(getTaskResult).mockResolvedValue({ restaurants: [], items: [], metadata: { itinerary: dynamic } } as any)
    vi.mocked(refineItinerary).mockResolvedValue({ result: {} as any, itinerary: accepted })
    const onModifyConstraints = vi.fn()
    render(<ItineraryView initialItinerary={dynamic} taskId="task-1" userId="user-1" conversationId="conv-1" onModifyConstraints={onModifyConstraints} />)

    expect(screen.getByText(/Estimated cost: 25\+ SGD per person/)).toBeInTheDocument()
    expect(screen.getByText('cost unknown')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Modify constraints' }))
    expect(onModifyConstraints).toHaveBeenCalledWith(dynamic)
    fireEvent.click(screen.getByRole('button', { name: 'Accept estimates' }))
    await waitFor(() => expect(refineItinerary).toHaveBeenCalledWith('task-1', expect.objectContaining({
      accept_uncertainties: true,
      expected_revision: 1,
    })))
  })

  it('renders a shared hotel anchor once with outbound and return legs', () => {
    const anchored: Itinerary = {
      ...itinerary(),
      problem_summary: { style: 'sightseeing', pace: 'balanced', primary_experience_share: 0.75 },
      anchors: {
        start: { id: 'anchor:start', title: 'Beach Hotel', address: '1 Coast Road', lat: 1.25, lng: 103.82 },
        end: { id: 'anchor:end', title: 'Beach Hotel', address: '1 Coast Road', lat: 1.25, lng: 103.82 },
        shared: true,
        policy: 'round_trip',
      },
      legs: [
        { from_index: null, to_index: 0, from_anchor: 'start', mode: 'pt', duration_min: 15, distance_km: 2, source: 'onemap' },
        ...itinerary().legs,
        { from_index: 1, to_index: null, to_anchor: 'end', mode: 'pt', duration_min: 18, distance_km: 2.3, source: 'onemap' },
      ],
      repair: { attempt_count: 1, success: true },
    }
    vi.mocked(getTaskResult).mockResolvedValue({ restaurants: [], items: [], metadata: { itinerary: anchored } } as any)
    render(<ItineraryView initialItinerary={anchored} taskId="task-1" userId="user-1" conversationId="conv-1" />)

    expect(screen.getAllByText('Beach Hotel')).toHaveLength(1)
    expect(screen.getByText('Start & end')).toBeInTheDocument()
    expect(screen.getByText('From start')).toBeInTheDocument()
    expect(screen.getByText('Return to end')).toBeInTheDocument()
    expect(screen.getByText('Primary experiences: 75%')).toBeInTheDocument()
    expect(screen.getByText('Automatic repair: applied')).toBeInTheDocument()
  })

  it('suppresses an invalid timeline and offers constraint refinement', () => {
    const invalid: Itinerary = {
      ...itinerary(),
      slots: [],
      legs: [],
      suppress_normal_presentation: true,
      planning_status: 'needs_refinement',
      sanity: {
        status: 'invalid',
        violations: [{ code: 'time_window_exceeded' }],
        metrics: {},
      },
      refinement: {
        reasons: [{ code: 'time_window_exceeded' }],
        suggested_fields: ['daily_end_time'],
      },
    }
    vi.mocked(getTaskResult).mockResolvedValue({ restaurants: [], items: [], metadata: { itinerary: invalid } } as any)
    const onModifyConstraints = vi.fn()
    render(<ItineraryView initialItinerary={invalid} taskId="task-1" userId="user-1" conversationId="conv-1" onModifyConstraints={onModifyConstraints} />)

    expect(screen.getByText('time window exceeded')).toBeInTheDocument()
    expect(screen.queryByText('National Gallery')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show route' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Modify constraints' }))
    expect(onModifyConstraints).toHaveBeenCalledWith(invalid)
  })

  it('keeps a warning-only itinerary visible with planner notes', () => {
    const warned: Itinerary = {
      ...itinerary(),
      sanity: {
        status: 'valid',
        violations: [],
        warnings: [{ code: 'missing_primary_experience' }],
        metrics: {},
      },
    }
    vi.mocked(getTaskResult).mockResolvedValue({ restaurants: [], items: [], metadata: { itinerary: warned } } as any)

    render(<ItineraryView initialItinerary={warned} taskId="task-1" userId="user-1" conversationId="conv-1" />)

    expect(screen.getByText('Planner notes')).toBeInTheDocument()
    expect(screen.getByText('missing primary experience')).toBeInTheDocument()
    expect(screen.getByText('National Gallery')).toBeInTheDocument()
  })
})
