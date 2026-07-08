import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import ProfilePanel from '../ui/ProfilePanel'
import { getUserProfile, updateUserProfile, getDomainPreferenceForm } from '../utils/api'

vi.mock('../utils/api', () => ({
  getUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
  getDomainPreferenceForm: vi.fn(),
}))

describe('ProfilePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getUserProfile).mockResolvedValue({
      user_id: 'u-1',
      demographics: { occupation: 'engineer' },
      constraints: { language: 'en' },
      taste_persona: 'into hard sci-fi',
      domains: { movie: { genres: ['science fiction'] } },
    })
    vi.mocked(updateUserProfile).mockResolvedValue({
      user_id: 'u-1',
      demographics: {},
      constraints: {},
      taste_persona: '',
      domains: {},
    })
    vi.mocked(getDomainPreferenceForm).mockImplementation((domain: string) =>
      Promise.resolve(
        domain === 'movie'
          ? {
              domain: 'movie',
              fields: [
                {
                  key: 'genres',
                  label: 'Genres',
                  type: 'multiselect',
                  options: ['science fiction', 'comedy', 'drama'],
                  required: true,
                  placeholder: '',
                },
              ],
              missing_required: [],
              complete: true,
            }
          : domain === 'hotel'
            ? {
                domain: 'hotel',
                fields: [
                  { key: 'location', label: 'Destination / area', type: 'text', options: [], required: true, placeholder: 'e.g. Sentosa' },
                  { key: 'stars', label: 'Hotel class (stars)', type: 'select', options: ['2', '3', '4', '5'], required: false, placeholder: '' },
                  { key: 'amenities', label: 'Amenities', type: 'text', options: [], required: false, placeholder: 'e.g. pool, free wifi' },
                  { key: 'budget', label: 'Budget per night', type: 'text', options: [], required: false, placeholder: 'e.g. < 200 SGD' },
                ],
                missing_required: ['location'],
                complete: false,
              }
            : {
                domain,
                fields: [
                  { key: 'location', label: 'Location', type: 'text', options: [], required: domain === 'restaurant', placeholder: 'e.g. Chinatown' },
                ],
                missing_required: domain === 'restaurant' ? ['location'] : [],
                complete: domain !== 'restaurant',
              },
      ),
    )
  })

  it('renders the server-generated domain forms with prefilled values', async () => {
    render(<ProfilePanel userId="u-1" onClose={() => {}} />)

    expect(getUserProfile).toHaveBeenCalledWith('u-1')
    expect(getDomainPreferenceForm).toHaveBeenCalledWith('restaurant')
    expect(getDomainPreferenceForm).toHaveBeenCalledWith('movie')
    expect(await screen.findByDisplayValue('engineer')).toBeTruthy()
    expect(screen.getByDisplayValue('into hard sci-fi')).toBeTruthy()
    expect(screen.getByRole('tab', { name: 'General' })).toHaveAttribute('aria-selected', 'true')

    // movie genres rendered as multiselect chips; the prefilled one is active.
    fireEvent.click(screen.getByRole('tab', { name: 'Movie' }))
    const sciFi = await screen.findByRole('button', { name: 'science fiction' })
    expect(sciFi.getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: 'comedy' }).getAttribute('aria-pressed')).toBe('false')
  })

  it('renders the hotel tab with the server-generated stay preference fields', async () => {
    render(<ProfilePanel userId="u-1" onClose={() => {}} />)
    await screen.findByDisplayValue('engineer')

    expect(getDomainPreferenceForm).toHaveBeenCalledWith('hotel')
    fireEvent.click(screen.getByRole('tab', { name: 'Hotel' }))

    const destination = await screen.findByLabelText('Destination / area')
    expect(destination).toHaveAttribute('placeholder', 'e.g. Sentosa')
    expect(screen.getByLabelText('Hotel class (stars)').tagName).toBe('SELECT')
    expect(screen.getByLabelText('Amenities')).toBeTruthy()
    expect(screen.getByLabelText('Budget per night')).toBeTruthy()
  })

  it('saves an edited hotel slice under domains.hotel', async () => {
    render(<ProfilePanel userId="u-1" onClose={() => {}} />)
    await screen.findByDisplayValue('engineer')
    fireEvent.click(screen.getByRole('tab', { name: 'Hotel' }))

    fireEvent.change(await screen.findByLabelText('Destination / area'), { target: { value: 'Sentosa' } })
    fireEvent.change(screen.getByLabelText('Hotel class (stars)'), { target: { value: '4' } })
    fireEvent.change(screen.getByLabelText('Amenities'), { target: { value: 'pool, free wifi' } })
    fireEvent.change(screen.getByLabelText('Budget per night'), { target: { value: '< 200 SGD' } })
    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(updateUserProfile).toHaveBeenCalled())
    const [, payload] = vi.mocked(updateUserProfile).mock.calls[0]
    expect(payload.domains.hotel).toEqual({
      location: 'Sentosa',
      stars: '4',
      amenities: 'pool, free wifi',
      budget: '< 200 SGD',
    })
  })

  it('toggles a genre chip and saves the merged slice', async () => {
    const onClose = vi.fn()
    render(<ProfilePanel userId="u-1" onClose={onClose} />)
    fireEvent.click(await screen.findByRole('tab', { name: 'Movie' }))
    await screen.findByRole('button', { name: 'comedy' })

    fireEvent.click(screen.getByRole('tab', { name: 'General' }))
    fireEvent.change(screen.getByLabelText('Taste persona'), { target: { value: 'loves cozy mysteries' } })
    fireEvent.click(screen.getByRole('tab', { name: 'Movie' }))
    fireEvent.click(screen.getByRole('button', { name: 'comedy' }))
    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(updateUserProfile).toHaveBeenCalled())
    const [, payload] = vi.mocked(updateUserProfile).mock.calls[0]
    expect(payload.taste_persona).toBe('loves cozy mysteries')
    expect(payload.domains.movie.genres).toEqual(['science fiction', 'comedy'])
  })
})
