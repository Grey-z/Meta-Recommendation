import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { FeedbackControls } from '../ui/FeedbackControls'
import { getFeedbackOptions, submitFeedback } from '../utils/api'

vi.mock('../utils/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../utils/api')>()),
  getFeedbackOptions: vi.fn(),
  submitFeedback: vi.fn(),
}))

const mockedOptions = getFeedbackOptions as unknown as ReturnType<typeof vi.fn>
const mockedSubmit = submitFeedback as unknown as ReturnType<typeof vi.fn>

describe('FeedbackControls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedOptions.mockResolvedValue([
      { code: 'too_far', label: 'Too far' },
      { code: 'not_related', label: 'Not related' },
      { code: 'others', label: 'Others' },
    ])
    mockedSubmit.mockResolvedValue({
      feedback_id: 'f1',
      result_id: 'r1',
      sentiment: 'up',
      rating: 5,
      reason: null,
    })
  })

  it('submits an up vote and shows a thanks line', async () => {
    render(<FeedbackControls resultId="r1" />)
    fireEvent.click(screen.getByLabelText('Helpful'))
    await waitFor(() =>
      expect(mockedSubmit).toHaveBeenCalledWith(
        expect.objectContaining({ sentiment: 'up', result_id: 'r1' }),
      ),
    )
    expect(await screen.findByText('Thanks for your feedback!')).toBeInTheDocument()
  })

  it('reveals single-select reason chips on a down vote and submits the tapped reason', async () => {
    render(<FeedbackControls resultId="r1" />)
    fireEvent.click(screen.getByLabelText('Not helpful'))

    const chip = await screen.findByRole('button', { name: 'Too far' })
    fireEvent.click(chip)

    await waitFor(() =>
      expect(mockedSubmit).toHaveBeenCalledWith(
        expect.objectContaining({ sentiment: 'down', reason: 'too_far', result_id: 'r1' }),
      ),
    )
    expect(await screen.findByText('Thanks for your feedback!')).toBeInTheDocument()
  })

  it('renders as already-submitted (no prompt) when a vote is on record', () => {
    render(<FeedbackControls resultId="r1" existingFeedback={{ sentiment: 'down', reason: 'too_far' }} />)

    // The prompt/buttons never appear, so the vote cannot be re-submitted.
    expect(screen.getByText('Thanks for your feedback!')).toBeInTheDocument()
    expect(screen.queryByLabelText('Helpful')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Not helpful')).not.toBeInTheDocument()
    expect(screen.queryByText('Was this helpful?')).not.toBeInTheDocument()
    expect(mockedSubmit).not.toHaveBeenCalled()
  })

  it('moves to submitted when persisted feedback arrives after mount', async () => {
    const { rerender } = render(<FeedbackControls resultId="r1" />)
    expect(screen.getByText('Was this helpful?')).toBeInTheDocument()

    rerender(<FeedbackControls resultId="r1" existingFeedback={{ sentiment: 'up', reason: null }} />)

    expect(await screen.findByText('Thanks for your feedback!')).toBeInTheDocument()
    expect(screen.queryByLabelText('Helpful')).not.toBeInTheDocument()
    expect(mockedSubmit).not.toHaveBeenCalled()
  })

  it('requests domain-scoped reason options on a down vote', async () => {
    render(<FeedbackControls resultId="r-movie" domain="movie" />)
    fireEvent.click(screen.getByLabelText('Not helpful'))

    // The domain is threaded to the options endpoint so the chips are tailored
    // (backend per-domain logic is covered separately; here we only assert threading).
    await waitFor(() => expect(mockedOptions).toHaveBeenCalledWith('movie'))
    expect(await screen.findByRole('button', { name: 'Not related' })).toBeInTheDocument()
  })

  it('resets to idle when reused for another unrated recommendation', async () => {
    const { rerender } = render(
      <FeedbackControls resultId="r1" existingFeedback={{ sentiment: 'down', reason: 'too_far' }} />,
    )
    expect(screen.getByText('Thanks for your feedback!')).toBeInTheDocument()

    rerender(<FeedbackControls resultId="r2" />)

    await waitFor(() => expect(screen.getByText('Was this helpful?')).toBeInTheDocument())
    expect(screen.getByLabelText('Helpful')).toBeInTheDocument()
    expect(screen.getByLabelText('Not helpful')).toBeInTheDocument()
  })
})
