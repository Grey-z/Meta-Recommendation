import type { Itinerary, PlanningSnapshot } from '../contracts/api-types'
import { stepColor } from './transitColors'

export type RouteFeature = {
  type: 'Feature'
  properties: {
    source: string
    estimated: boolean
    dashed: boolean
    mode: string
    color: string
    day_index?: number | null
  }
  geometry: { type: 'LineString'; coordinates: number[][] }
}

function routeFeature(coordinates: number[][], properties: RouteFeature['properties']): RouteFeature {
  return { type: 'Feature', properties, geometry: { type: 'LineString', coordinates } }
}

export function buildSnapshotRouteFeatures(snapshot: PlanningSnapshot): RouteFeature[] {
  const nodes = new Map(
    [...snapshot.confirmed_nodes, ...snapshot.frontier_nodes]
      .filter(node => validLngLat([node.lng, node.lat]))
      .map(node => [node.id, [node.lng!, node.lat!] as [number, number]]),
  )
  return snapshot.edges.flatMap(edge => {
    const providerCoords = (edge.coords || []).filter(validLngLat)
    const fallback = [nodes.get(edge.from_id), nodes.get(edge.to_id)].filter(validLngLat)
    const coordinates = providerCoords.length >= 2 ? providerCoords : fallback
    if (coordinates.length < 2) return []
    const estimated = edge.status !== 'provider' || providerCoords.length < 2
    const mode = edge.mode || 'pt'
    return [routeFeature(coordinates, {
      source: edge.status,
      estimated,
      dashed: estimated || mode === 'walk',
      mode,
      color: stepColor(mode),
      day_index: edge.day_index,
    })]
  })
}

export function snapshotBounds(snapshot: PlanningSnapshot, features: RouteFeature[]): [number, number][] {
  const points = [...snapshot.confirmed_nodes, ...snapshot.frontier_nodes].flatMap(node => {
    const point = [node.lng, node.lat]
    return validLngLat(point) ? [point] : []
  })
  features.forEach(feature => points.push(...feature.geometry.coordinates.filter(validLngLat)))
  return points
}

export function buildMapboxStreetsStyle(token: string) {
  return {
    version: 8 as const,
    sources: {
      'mapbox-streets': {
        type: 'raster' as const,
        tiles: [
          `https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/512/{z}/{x}/{y}?access_token=${encodeURIComponent(token)}`,
        ],
        tileSize: 512,
        attribution: '&copy; Mapbox &copy; OpenStreetMap',
      },
    },
    layers: [
      { id: 'map-background', type: 'background' as const, paint: { 'background-color': '#EDF0EB' } },
      { id: 'mapbox-streets', type: 'raster' as const, source: 'mapbox-streets' },
    ],
  }
}

export function buildOpenStreetMapStyle() {
  return {
    version: 8 as const,
    sources: {
      openstreetmap: {
        type: 'raster' as const,
        tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
        tileSize: 256,
        attribution: '&copy; OpenStreetMap contributors',
      },
    },
    layers: [
      { id: 'map-background', type: 'background' as const, paint: { 'background-color': '#EDF0EB' } },
      { id: 'openstreetmap', type: 'raster' as const, source: 'openstreetmap' },
    ],
  }
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
  const anchorPoint = (key: string | null | undefined) => {
    if (key !== 'start' && key !== 'end' && key !== 'lodging') return undefined
    const anchor = itinerary.anchors?.[key]
    const point = [anchor?.lng, anchor?.lat]
    return validLngLat(point) ? point : undefined
  }
  return itinerary.legs.flatMap(leg => {
    // Live OneMap transit legs carry per-sub-leg steps: draw each as its own
    // coloured segment (MRT line colour, bus cyan, walk dashed green) instead
    // of one opaque transit line.
    const stepFeatures = (leg.steps || []).flatMap(step => {
      const coords = (step.coords || []).filter(validLngLat)
      if (coords.length < 2) return []
      return [routeFeature(coords, {
        source: leg.source,
        estimated: false,
        dashed: step.mode === 'walk',
        mode: step.mode,
        color: stepColor(step.mode, step.service),
        day_index: leg.day_index,
      })]
    })
    if (stepFeatures.length > 0) return stepFeatures

    const providerCoords = (leg.coords || []).filter(validLngLat)
    const fromPoint = leg.from_anchor
      ? anchorPoint(leg.from_anchor)
      : (typeof leg.from_index === 'number' ? byIndex.get(leg.from_index) : undefined)
    const toPoint = leg.to_anchor
      ? anchorPoint(leg.to_anchor)
      : (typeof leg.to_index === 'number' ? byIndex.get(leg.to_index) : undefined)
    const fallback = [fromPoint, toPoint].filter(validLngLat)
    const coordinates = providerCoords.length >= 2 ? providerCoords : fallback
    if (coordinates.length < 2) return []
    const estimated = leg.source === 'estimate' || providerCoords.length < 2
    return [routeFeature(coordinates, {
      source: leg.source,
      estimated,
      dashed: estimated || leg.mode === 'walk',
      mode: leg.mode,
      color: stepColor(leg.mode),
      day_index: leg.day_index,
    })]
  })
}

export function routeBounds(itinerary: Itinerary, features: RouteFeature[]): [number, number][] {
  const points = itinerary.slots.flatMap(slot => {
    const point = [slot.chosen?.lng, slot.chosen?.lat]
    return validLngLat(point) ? [point] : []
  })
  for (const anchor of [itinerary.anchors?.start, itinerary.anchors?.end, itinerary.anchors?.lodging]) {
    const point = [anchor?.lng, anchor?.lat]
    if (validLngLat(point)) points.push(point)
  }
  features.forEach(feature => points.push(...feature.geometry.coordinates.filter(validLngLat)))
  return points
}
