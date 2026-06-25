import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import ProfilePanel from '../ui/ProfilePanel'
import { getUserProfile, updateUserProfile } from '../utils/api'

vi.mock('../utils/api', () => ({
  getUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
}))

describe('ProfilePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getUserProfile).mockResolvedValue({
      user_id: 'u-1',
      demographics: { occupation: 'engineer' },
      constraints: { language: 'en' },
      taste_persona: 'into hard sci-fi',
      domains: { movie: { genres: ['science fiction', 'drama'] } },
    })
    vi.mocked(updateUserProfile).mockResolvedValue({
      user_id: 'u-1',
      demographics: {},
      constraints: {},
      taste_persona: '',
      domains: {},
    })
  })

  it('loads the three-layer profile and prefills fields', async () => {
    render(<ProfilePanel userId="u-1" onClose={() => {}} />)

    expect(getUserProfile).toHaveBeenCalledWith('u-1')
    expect(await screen.findByDisplayValue('engineer')).toBeTruthy()
    expect(screen.getByDisplayValue('into hard sci-fi')).toBeTruthy()
    // movie genres array rendered as a comma-joined string
    expect(screen.getByDisplayValue('science fiction, drama')).toBeTruthy()
  })

  it('saves edited persona and parses movie genres into an array', async () => {
    const onClose = vi.fn()
    render(<ProfilePanel userId="u-1" onClose={onClose} />)
    await screen.findByDisplayValue('into hard sci-fi')

    fireEvent.change(screen.getByLabelText('Taste persona'), {
      target: { value: 'loves cozy mysteries' },
    })
    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(updateUserProfile).toHaveBeenCalled())
    const [, payload] = vi.mocked(updateUserProfile).mock.calls[0]
    expect(payload.taste_persona).toBe('loves cozy mysteries')
    expect(payload.domains.movie.genres).toEqual(['science fiction', 'drama'])
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })
})
