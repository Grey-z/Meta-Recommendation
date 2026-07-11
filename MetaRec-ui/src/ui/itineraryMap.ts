import type { Itinerary } from '../contracts/api-types'

export type RouteFeature = {
  type: 'Feature'
  properties: { source: string; estimated: boolean }
  geometry: { type: 'LineString'; coordinates: number[][] }
}

export function validLngLat(value: unknown): value is [number, number] {
  return Array.isArray(value)
    && value.length >= 2
    && typeof value[0] === 'number'
    && typeof value[1] === 'number'
    && value[0] >= -180 && value[0] <= 180
    && value[1] >= -90 && value[1] <= 90
}

export function buildRouteFeatures(itinerary: Itinerary): RouteFeature[] {
  const byIndex = new Map(
    itinerary.slots
      .filter(slot => typeof slot.chosen?.lng === 'number' && typeof slot.chosen?.lat === 'number')
      .map(slot => [slot.slot_index, [slot.chosen!.lng!, slot.chosen!.lat!] as [number, number]]),
  )
  return itinerary.legs.flatMap(leg => {
    const providerCoords = (leg.coords || []).filter(validLngLat)
    const fallback = [byIndex.get(leg.from_index), byIndex.get(leg.to_index)].filter(validLngLat)
    const coordinates = providerCoords.length >= 2 ? providerCoords : fallback
    if (coordinates.length < 2) return []
    return [{
      type: 'Feature' as const,
      properties: { source: leg.source, estimated: leg.source === 'estimate' || providerCoords.length < 2 },
      geometry: { type: 'LineString' as const, coordinates },
    }]
  })
}

export function routeBounds(itinerary: Itinerary, features: RouteFeature[]): [number, number][] {
  const points = itinerary.slots.flatMap(slot => {
    const point = [slot.chosen?.lng, slot.chosen?.lat]
    return validLngLat(point) ? [point] : []
  })
  features.forEach(feature => points.push(...feature.geometry.coordinates.filter(validLngLat)))
  return points
}

