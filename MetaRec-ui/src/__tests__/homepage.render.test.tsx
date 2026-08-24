import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { HomePage } from '../ui/HomePage'


describe('frontend render: HomePage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders core hero content and footer email from fetched content', async () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      json: async () => ({
        footer: {
          contactEmail: 'test@example.com',
          copyright: 'Copyright Test',
        },
      }),
    })

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    )

    expect(screen.getByText('Collective Intelligence')).toBeInTheDocument()
    expect(screen.getByText('Intelligent Brain for Embodied Robots')).toBeInTheDocument()
    expect(await screen.findByText('test@example.com')).toBeInTheDocument()
  })

  it('navigates to /MetaRec when clicking Try MetaRec', () => {
    const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mockFetch.mockResolvedValue({
      json: async () => ({
        footer: {
          contactEmail: 'test@example.com',
          copyright: 'Copyright Test',
        },
      }),
    })

    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/MetaRec" element={<div>MetaRec Destination</div>} />
        </Routes>
      </MemoryRouter>
    )

    fireEvent.click(screen.getByRole('button', { name: /try metarec/i }))
    expect(screen.getByText('MetaRec Destination')).toBeInTheDocument()
  })
})
