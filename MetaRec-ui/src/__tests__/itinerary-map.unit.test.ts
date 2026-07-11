import { describe, expect, it } from 'vitest'

import type { Itinerary } from '../contracts/api-types'
import { buildRouteFeatures, routeBounds, validLngLat } from '../ui/itineraryMap'

const base: Itinerary = {
  location: 'Singapore', start_time: '10:00', revision: 1,
  slots: [
    { slot_index: 0, label: 'A', domain: 'attraction', chosen: { id: 'a', title: 'A', lng: 103.8, lat: 1.3 }, alternates: [] },
    { slot_index: 1, label: 'B', domain: 'restaurant', chosen: { id: 'b', title: 'B', lng: 103.9, lat: 1.31 }, alternates: [] },
  ],
  legs: [{ from_index: 0, to_index: 1, mode: 'walk', duration_min: 10, distance_km: 1, source: 'estimate' }],
  totals: { total_travel_min: 10 },
}

describe('itinerary map projection', () => {
  it('uses a dashed straight fallback for estimate-only legs', () => {
    const features = buildRouteFeatures(base)
    expect(features).toHaveLength(1)
    expect(features[0].properties.estimated).toBe(true)
    expect(features[0].geometry.coordinates).toEqual([[103.8, 1.3], [103.9, 1.31]])
  })

  it('keeps valid provider geometry and ignores invalid coordinate order/ranges', () => {
    const itinerary = { ...base, legs: [{ ...base.legs[0], source: 'onemap', coords: [[103.8, 1.3], [103.85, 1.305], [999, 1]] }] }
    const features = buildRouteFeatures(itinerary)
    expect(features[0].properties.estimated).toBe(false)
    expect(features[0].geometry.coordinates).toEqual([[103.8, 1.3], [103.85, 1.305]])
    expect(routeBounds(itinerary, features)).toContainEqual([103.9, 1.31])
    expect(validLngLat([1.3, 103.8])).toBe(false)
  })
})

