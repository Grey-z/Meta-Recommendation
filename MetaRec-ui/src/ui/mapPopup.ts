// Popup content for the map modal. The details come from the recommendation
// item the backend already returned (SerpAPI/OSM fields) — no client-side
// place-details API is involved. Kept as a pure HTML-string builder so it can
// be unit-tested without WebGL or a map library.

export type MapDetails = {
  rating?: number | null
  reviews_count?: number | null
  price?: string | null
  price_per_person_sgd?: number | string | null
  cuisine?: string | null
  open_hours_note?: string | null
  phone?: string | null
  highlights?: string[] | null
}

function esc(value: unknown): string {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export function googleMapsDirectionsUrl(address: string): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(address)}`
}

export function googleMapsSearchUrl(name: string, address: string): string {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${name}, ${address}`)}`
}

export function buildPopupHtml(name: string, address: string, details?: MapDetails): string {
  let content = `<div style="padding: 0; max-width: 300px; color: #1a1a1a;">`

  content += `<div style="padding: 12px 16px; border-bottom: 1px solid #e0e0e0;">
    <div style="font-weight: 600; font-size: 16px; margin-bottom: 4px;">${esc(name)}</div>
    <div style="color: #666; font-size: 14px;">${esc(address)}</div>
  </div>`

  const rows: string[] = []

  const rating = details?.rating
  if (typeof rating === 'number' && rating > 0) {
    const stars = '★'.repeat(Math.max(1, Math.min(5, Math.round(rating))))
    const ratingColor = rating >= 4.0 ? '#0f9d58' : rating >= 3.0 ? '#fbbc04' : '#ea4335'
    const reviews = details?.reviews_count
    rows.push(`<div style="display: flex; align-items: center; gap: 8px;">
      <span style="color: ${ratingColor}; font-size: 16px;">${stars}</span>
      <span style="font-weight: 600; font-size: 14px;">${esc(rating.toFixed(1))}</span>
      ${typeof reviews === 'number' && reviews > 0 ? `<span style="color: #666; font-size: 12px;">(${esc(reviews.toLocaleString())} reviews)</span>` : ''}
    </div>`)
  }

  const price = details?.price || (details?.price_per_person_sgd ? `~${details.price_per_person_sgd} SGD / person` : '')
  if (price) {
    rows.push(`<div style="color: #666; font-size: 14px;">Price: <span style="font-weight: 600;">${esc(price)}</span></div>`)
  }
  if (details?.cuisine) {
    rows.push(`<div style="color: #666; font-size: 14px;">Cuisine: ${esc(details.cuisine)}</div>`)
  }
  if (details?.open_hours_note) {
    rows.push(`<div style="color: #666; font-size: 13px;">Hours: ${esc(details.open_hours_note)}</div>`)
  }
  if (details?.phone) {
    rows.push(`<div style="color: #666; font-size: 13px;">Phone: ${esc(details.phone)}</div>`)
  }
  const highlights = (details?.highlights || []).filter(Boolean)
  if (highlights.length > 0) {
    rows.push(`<div style="color: #666; font-size: 13px;">${esc(highlights.slice(0, 3).join(' · '))}</div>`)
  }

  if (rows.length > 0) {
    content += `<div style="padding: 12px 16px; display: grid; gap: 6px;">${rows.join('')}</div>`
  }

  content += `<div style="padding: 8px 16px; border-top: 1px solid #e0e0e0; display: flex; gap: 8px;">
    <a href="${googleMapsDirectionsUrl(address)}" target="_blank" rel="noopener" style="flex: 1; padding: 8px; background: #4285f4; color: white; text-decoration: none; text-align: center; border-radius: 4px; font-size: 14px; font-weight: 500;">Directions</a>
    <a href="${googleMapsSearchUrl(name, address)}" target="_blank" rel="noopener" style="flex: 1; padding: 8px; background: #f1f3f4; color: #1a1a1a; text-decoration: none; text-align: center; border-radius: 4px; font-size: 14px; font-weight: 500;">View</a>
  </div>`

  content += `</div>`
  return content
}
