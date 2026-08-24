import { describe, expect, it } from 'vitest'

import type { Itinerary, PlanningSnapshot } from '../contracts/api-types'
import {
  buildMapboxStreetsStyle,
  buildOpenStreetMapStyle,
  buildRouteFeatures,
  buildSnapshotRouteFeatures,
  routeBounds,
  snapshotBounds,
  validLngLat,
} from '../ui/itineraryMap'

const base: Itinerary = {
  location: 'Singapore', start_time: '10:00', revision: 1,
  slots: [
    { slot_index: 0, label: 'A', domain: 'attraction', chosen: { id: 'a', title: 'A', lng: 103.8, lat: 1.3 }, alternates: [] },
    { slot_index: 1, label: 'B', domain: 'restaurant', chosen: { id: 'b', title: 'B', lng: 103.9, lat: 1.31 }, alternates: [] },
  ],
  legs: [{ from_index: 0, to_index: 1, mode: 'walk', duration_min: 10, distance_km: 1, source: 'estimate' }],
  totals: { total_travel_min: 10 },
}

const snapshot: PlanningSnapshot = {
  schema_version: 'itinerary-planning-snapshot/v1', revision: 2,
  phase: 'provisional_solve', planning_status: 'processing', round: 2,
  confirmed_nodes: [
    { id: 'a', title: 'A', status: 'confirmed', day_index: 0, lat: 1.3, lng: 103.8 },
  ],
  frontier_nodes: [
    { id: 'b', title: 'B', status: 'candidate', lat: 1.31, lng: 103.9 },
  ],
  retired_ids: [],
  edges: [
    { from_id: 'a', to_id: 'b', status: 'estimated', mode: 'pt', duration_min: 12 },
  ],
  days: [{ day_index: 0, date: '2026-08-03', start_time: '09:00', end_time_constraint: '17:00', activity_min: 60, travel_min: 12, wait_min: 0 }],
  cost: { min: 20, max: 30, currency: 'SGD', budget_limit: 100, remaining: { min: 70, max: 80 } },
  uncertainty_count: 1, provider_calls: 2, provider_call_limit: 8,
}

describe('itinerary map projection', () => {
  it('uses a dashed straight fallback for estimate-only legs', () => {
    const features = buildRouteFeatures(base)
    expect(features).toHaveLength(1)
    expect(features[0].properties.estimated).toBe(true)
    expect(features[0].properties.mode).toBe('walk')
    expect(features[0].geometry.coordinates).toEqual([[103.8, 1.3], [103.9, 1.31]])
  })

  it('builds a self-contained Mapbox Streets raster base style', () => {
    const style = buildMapboxStreetsStyle('pk.test/value')
    expect(style.version).toBe(8)
    expect(style.sources['mapbox-streets'].tiles[0]).toContain('/mapbox/streets-v12/tiles/512/')
    expect(style.sources['mapbox-streets'].tiles[0]).toContain('access_token=pk.test%2Fvalue')
    expect(style.layers.map(layer => layer.id)).toEqual(['map-background', 'mapbox-streets'])
  })

  it('provides an attributed road-map fallback independent of Mapbox style loading', () => {
    const style = buildOpenStreetMapStyle()
    expect(style.sources.openstreetmap.tiles).toEqual(['https://tile.openstreetmap.org/{z}/{x}/{y}.png'])
    expect(style.sources.openstreetmap.attribution).toContain('OpenStreetMap contributors')
    expect(style.layers.map(layer => layer.id)).toEqual(['map-background', 'openstreetmap'])
  })

  it('keeps valid provider geometry and ignores invalid coordinate order/ranges', () => {
    const itinerary = { ...base, legs: [{ ...base.legs[0], source: 'onemap', coords: [[103.8, 1.3], [103.85, 1.305], [999, 1]] }] }
    const features = buildRouteFeatures(itinerary)
    expect(features[0].properties.estimated).toBe(false)
    expect(features[0].geometry.coordinates).toEqual([[103.8, 1.3], [103.85, 1.305]])
    expect(routeBounds(itinerary, features)).toContainEqual([103.9, 1.31])
    expect(validLngLat([1.3, 103.8])).toBe(false)
  })

  it('includes fixed anchors in fallback legs and route bounds', () => {
    const anchored: Itinerary = {
      ...base,
      anchors: {
        start: { id: 'anchor:start', title: 'Hotel', lat: 1.29, lng: 103.79 },
        end: { id: 'anchor:end', title: 'Hotel', lat: 1.29, lng: 103.79 },
        shared: true,
      },
      legs: [
        { from_index: null, to_index: 0, from_anchor: 'start', mode: 'walk', duration_min: 8, distance_km: .5, source: 'estimate' },
        ...base.legs,
        { from_index: 1, to_index: null, to_anchor: 'end', mode: 'walk', duration_min: 9, distance_km: .6, source: 'estimate' },
      ],
    }
    const features = buildRouteFeatures(anchored)
    expect(features).toHaveLength(3)
    expect(features[0].geometry.coordinates).toEqual([[103.79, 1.29], [103.8, 1.3]])
    expect(features[2].geometry.coordinates).toEqual([[103.9, 1.31], [103.79, 1.29]])
    expect(routeBounds(anchored, features)).toContainEqual([103.79, 1.29])
  })

  it('draws multi-day lodging boundary legs from the lodging anchor fallback', () => {
    const multiDay: Itinerary = {
      ...base,
      anchors: {
        lodging: { id: 'lodging:h1', title: 'Shared hotel', lat: 1.28, lng: 103.78 },
      },
      legs: [
        { from_index: null, to_index: 0, from_anchor: 'lodging', mode: 'pt', duration_min: 14, distance_km: 2, source: 'estimate' },
        ...base.legs,
        { from_index: 1, to_index: null, to_anchor: 'lodging', mode: 'pt', duration_min: 15, distance_km: 2, source: 'estimate' },
      ],
    }
    const features = buildRouteFeatures(multiDay)
    expect(features).toHaveLength(3)
    expect(features[0].geometry.coordinates).toEqual([[103.78, 1.28], [103.8, 1.3]])
    expect(features[2].geometry.coordinates).toEqual([[103.9, 1.31], [103.78, 1.28]])
    expect(routeBounds(multiDay, features)).toContainEqual([103.78, 1.28])
  })

  it('splits a OneMap transit leg into per-step coloured segments', () => {
    const itinerary: Itinerary = {
      ...base,
      legs: [{
        from_index: 0, to_index: 1, mode: 'pt', duration_min: 20, distance_km: 5, source: 'onemap',
        coords: [[103.80, 1.30], [103.90, 1.31]],
        steps: [
          { mode: 'walk', distance_m: 200, coords: [[103.80, 1.30], [103.81, 1.301]] },
          { mode: 'bus', service: '199', from: 'A', to: 'B', num_stops: 4, coords: [[103.81, 1.301], [103.85, 1.305]] },
          { mode: 'subway', service: 'EW', line_name: 'East West Line', coords: [[103.85, 1.305], [103.90, 1.31]] },
        ],
      }],
    }
    const features = buildRouteFeatures(itinerary)
    expect(features.map(feature => feature.properties.mode)).toEqual(['walk', 'bus', 'subway'])
    // Walk segments are dashed to separate them; transit segments are solid.
    expect(features.map(feature => feature.properties.dashed)).toEqual([true, false, false])
    // Walk green, bus cyan, and the East-West line's official green.
    expect(features.map(feature => feature.properties.color)).toEqual(['#2F7D4A', '#00A5C4', '#009645'])
    expect(features.every(feature => feature.properties.estimated === false)).toBe(true)
    expect(features[1].geometry.coordinates).toEqual([[103.81, 1.301], [103.85, 1.305]])
  })

  it('marks an estimate-only transit leg dashed with a generic transit colour', () => {
    const itinerary = { ...base, legs: [{ ...base.legs[0], mode: 'pt' }] }
    const [feature] = buildRouteFeatures(itinerary)
    expect(feature.properties.dashed).toBe(true)
    expect(feature.properties.color).toBe('#2563A6')
  })

  it('uses endpoint fallback then replaces it with provider geometry for snapshots', () => {
    const estimated = buildSnapshotRouteFeatures(snapshot)
    expect(estimated[0].properties.estimated).toBe(true)
    expect(estimated[0].geometry.coordinates).toEqual([[103.8, 1.3], [103.9, 1.31]])
    expect(snapshotBounds(snapshot, estimated)).toContainEqual([103.9, 1.31])

    const provider = buildSnapshotRouteFeatures({
      ...snapshot,
      edges: [{
        ...snapshot.edges[0], status: 'provider',
        coords: [[103.8, 1.3], [103.85, 1.305], [103.9, 1.31]],
      }],
    })
    expect(provider[0].properties.estimated).toBe(false)
    expect(provider[0].geometry.coordinates).toHaveLength(3)
  })
})
