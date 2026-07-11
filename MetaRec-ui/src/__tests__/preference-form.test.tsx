import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import PreferenceForm from '../ui/PreferenceForm'
import type { DomainPreferenceForm } from '../utils/api'

const FORM: DomainPreferenceForm = {
  domain: 'movie',
  fields: [
    { key: 'genres', label: 'Genres', type: 'multiselect', options: ['science fiction', 'comedy'], required: true, placeholder: '' },
    { key: 'note', label: 'Note', type: 'text', options: [], required: false, placeholder: 'free text' },
  ],
  missing_required: ['genres'],
  complete: false,
}

const ITINERARY_FORM: DomainPreferenceForm = {
  domain: 'itinerary',
  fields: [
    { key: 'date', label: 'Travel date', type: 'date', options: [], required: true, placeholder: '' },
    { key: 'start_time', label: 'Start time', type: 'time', options: [], required: true, placeholder: '' },
    { key: 'budget_mode', label: 'Budget', type: 'select', options: ['limited', 'unlimited'], required: true, placeholder: '' },
    { key: 'budget_amount', label: 'Budget per person', type: 'number', options: [], required: false, required_when: { key: 'budget_mode', equals: 'limited' }, placeholder: '' },
  ],
  missing_required: [],
  complete: true,
}

function Harness({ initial }: { initial: Record<string, any> }) {
  const [values, setValues] = useState<Record<string, any>>(initial)
  return (
    <div>
      <PreferenceForm form={FORM} values={values} onChange={setValues} />
      <span data-testid="state">{JSON.stringify(values)}</span>
    </div>
  )
}

describe('PreferenceForm', () => {
  it('toggles multiselect chips and edits text fields', () => {
    render(<Harness initial={{ genres: ['science fiction'] }} />)

    expect(screen.getByRole('button', { name: 'science fiction' }).getAttribute('aria-pressed')).toBe('true')

    // add comedy
    fireEvent.click(screen.getByRole('button', { name: 'comedy' }))
    expect(JSON.parse(screen.getByTestId('state').textContent || '{}').genres).toEqual(['science fiction', 'comedy'])

    // remove science fiction
    fireEvent.click(screen.getByRole('button', { name: 'science fiction' }))
    expect(JSON.parse(screen.getByTestId('state').textContent || '{}').genres).toEqual(['comedy'])

    // text field
    fireEvent.change(screen.getByLabelText('Note'), { target: { value: 'hello' } })
    expect(JSON.parse(screen.getByTestId('state').textContent || '{}').note).toBe('hello')
  })

  it('renders structured itinerary inputs and conditional required state', () => {
    function ItineraryHarness() {
      const [values, setValues] = useState<Record<string, any>>({ budget_mode: 'limited' })
      return <PreferenceForm form={ITINERARY_FORM} values={values} onChange={setValues} />
    }
    render(<ItineraryHarness />)

    expect(screen.getByLabelText('Travel date')).toHaveAttribute('type', 'date')
    expect(screen.getByLabelText('Start time')).toHaveAttribute('type', 'time')
    expect(screen.getByLabelText('Budget per person')).toHaveAttribute('type', 'number')
    expect(screen.getByText('Budget per person').parentElement?.textContent).toContain('*')
  })
})
