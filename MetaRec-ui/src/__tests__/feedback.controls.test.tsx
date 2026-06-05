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
})
