import { render, waitFor } from '@testing-library/react'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Itinerary } from '../contracts/api-types'
import { ItineraryMap } from '../ui/ItineraryRouteMap'

// The map only needs a public token to initialise; stub it so init proceeds.
vi.mock('../utils/api', () => ({
  getPublicMapboxToken: vi.fn().mockResolvedValue('pk.test'),
}))

// Minimal mapbox-gl stand-in. The crucial detail is isStyleLoaded() === false:
// installLayers calls syncMapData immediately after addSource/addLayer, when the
// freshly-mutated style still reports "not loaded". Markers are DOM overlays that
// must render regardless, so this reproduces the regression where they were dropped.
const markerInstances: FakeMarker[] = []
const sourceSetData = vi.fn()

class FakeMarker {
  constructor(_opts: unknown) { markerInstances.push(this) }
  setLngLat() { return this }
  setPopup() { return this }
  addTo() { return this }
  remove() { return this }
}
class FakePopup { setText() { return this } }
class FakeLngLatBounds { extend() { return this } }
class FakeNavigationControl {}
class FakeMap {
  private sources: Record<string, { setData: typeof sourceSetData }> = {}
  constructor(_opts: unknown) {}
  addControl() {}
  on(event: string, handler: () => void) {
    // Fire style.load synchronously, mirroring how installLayers runs on load.
    if (event === 'style.load') handler()
  }
  isStyleLoaded() { return false }
  getSource(id: string) { return this.sources[id] }
  addSource(id: string) { this.sources[id] = { setData: sourceSetData } }
  addLayer() {}
  addImage() {}
  hasImage() { return true }
  setStyle() {}
  fitBounds() {}
  easeTo() {}
  resize() {}
  remove() {}
}

vi.mock('mapbox-gl', () => ({
  default: {
    accessToken: '',
    Map: FakeMap,
    Marker: FakeMarker,
    Popup: FakePopup,
    LngLatBounds: FakeLngLatBounds,
    NavigationControl: FakeNavigationControl,
  },
}))

const itinerary: Itinerary = {
  location: 'Singapore', start_time: '10:00', revision: 1,
  slots: [
    { slot_index: 0, label: 'A', domain: 'attraction', chosen: { id: 'a', title: 'A', lng: 103.8, lat: 1.3 }, alternates: [] },
    { slot_index: 1, label: 'B', domain: 'restaurant', chosen: { id: 'b', title: 'B', lng: 103.9, lat: 1.31 }, alternates: [] },
  ],
  legs: [{ from_index: 0, to_index: 1, mode: 'walk', duration_min: 10, distance_km: 1, source: 'estimate' }],
  totals: { total_travel_min: 10 },
}

describe('ItineraryMap marker lifecycle', () => {
  beforeAll(() => { (globalThis as any).WebGL2RenderingContext = class {} })
  afterAll(() => { delete (globalThis as any).WebGL2RenderingContext })
  beforeEach(() => { markerInstances.length = 0; sourceSetData.mockClear() })

  it('paints a marker per stop on the install pass even while the mutated style reports not-loaded', async () => {
    // Reproduces "after restart": the itinerary is present synchronously at mount, so
    // the only syncMapData that fires is the install-time one, when isStyleLoaded() is
    // still false. Markers (points) must render alongside the route line, not vanish.
    render(<ItineraryMap itinerary={itinerary} />)
    await waitFor(() => expect(markerInstances.length).toBe(2))
    expect(sourceSetData).toHaveBeenCalled()
  })
})
