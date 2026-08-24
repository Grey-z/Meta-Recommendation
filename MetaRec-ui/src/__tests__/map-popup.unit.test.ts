import { describe, expect, it } from 'vitest'

import { buildPopupHtml, googleMapsDirectionsUrl, googleMapsSearchUrl } from '../ui/mapPopup'

describe('buildPopupHtml', () => {
  it('renders name, address, and the Google Maps deep links without details', () => {
    const html = buildPopupHtml('Lau Pa Sat', '18 Raffles Quay')

    expect(html).toContain('Lau Pa Sat')
    expect(html).toContain('18 Raffles Quay')
    expect(html).toContain('https://www.google.com/maps/dir/?api=1&destination=18%20Raffles%20Quay')
    expect(html).toContain('https://www.google.com/maps/search/?api=1&query=Lau%20Pa%20Sat%2C%2018%20Raffles%20Quay')
    // No details block leaks placeholder text.
    expect(html).not.toContain('undefined')
    expect(html).not.toContain('null')
    expect(html).not.toContain('Price:')
  })

  it('renders backend-provided details: rating, reviews, price, cuisine, hours, phone, highlights', () => {
    const html = buildPopupHtml('Grand Palace Hotel', '1 Beach Rd', {
      rating: 4.5,
      reviews_count: 1200,
      price: '$$$',
      cuisine: 'Cantonese',
      open_hours_note: 'Daily 10:00-22:00',
      phone: '+65 6123 4567',
      highlights: ['rooftop bar', 'sea view', 'late night', 'fourth ignored'],
    })

    expect(html).toContain('4.5')
    expect(html).toContain('★★★★★') // 4.5 rounds to 5 stars
    expect(html).toContain('(1,200 reviews)')
    expect(html).toContain('$$$')
    expect(html).toContain('Cantonese')
    expect(html).toContain('Daily 10:00-22:00')
    expect(html).toContain('+65 6123 4567')
    expect(html).toContain('rooftop bar · sea view · late night')
    expect(html).not.toContain('fourth ignored') // capped at 3 highlights
  })

  it('falls back to price_per_person_sgd when no price string exists and omits empty fields', () => {
    const html = buildPopupHtml('Kopi Corner', 'Blk 5 Toa Payoh', {
      price_per_person_sgd: 12,
      rating: null,
      highlights: [],
    })

    expect(html).toContain('~12 SGD / person')
    expect(html).not.toContain('★')
    expect(html).not.toContain('Hours:')
    expect(html).not.toContain('Phone:')
  })

  it('escapes HTML in provider-sourced text', () => {
    const html = buildPopupHtml('<script>alert(1)</script>', '5 "Quoted" St & Co', {
      cuisine: '<b>bold</b>',
    })

    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
    expect(html).toContain('&quot;Quoted&quot;')
    expect(html).toContain('&lt;b&gt;bold&lt;/b&gt;')
  })
})

describe('deep link builders', () => {
  it('encode their query parts', () => {
    expect(googleMapsDirectionsUrl('a b&c')).toBe('https://www.google.com/maps/dir/?api=1&destination=a%20b%26c')
    expect(googleMapsSearchUrl('N', 'A')).toBe('https://www.google.com/maps/search/?api=1&query=N%2C%20A')
  })
})
