import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import 'mapbox-gl/dist/mapbox-gl.css'

import type { Itinerary, PlanningSnapshot } from '../contracts/api-types'
import { getPublicMapboxToken } from '../utils/api'
import {
  buildMapboxStreetsStyle,
  buildOpenStreetMapStyle,
  buildRouteFeatures,
  buildSnapshotRouteFeatures,
  routeBounds,
  snapshotBounds,
  type RouteFeature,
} from './itineraryMap'

type MapStatus = 'loading' | 'ready' | 'error'

type MapNode = {
  id: string
  title: string
  label: string
  status: 'confirmed' | 'candidate' | 'anchor'
  dayIndex?: number | null
  time?: string | null
  lat: number
  lng: number
}

function directionArrowImage(): ImageData | null {
  const canvas = document.createElement('canvas')
  canvas.width = 24
  canvas.height = 24
  const context = canvas.getContext('2d')
  if (!context) return null
  context.fillStyle = '#FFFFFF'
  context.beginPath()
  context.moveTo(2, 3)
  context.lineTo(22, 12)
  context.lineTo(2, 21)
  context.lineTo(7, 12)
  context.closePath()
  context.fill()
  context.fillStyle = '#4B4642'
  context.beginPath()
  context.moveTo(6, 7)
  context.lineTo(18, 12)
  context.lineTo(6, 17)
  context.lineTo(10, 12)
  context.closePath()
  context.fill()
  return context.getImageData(0, 0, 24, 24)
}

function finalNodes(itinerary: Itinerary): MapNode[] {
  const nodes: MapNode[] = itinerary.slots.flatMap((slot, position): MapNode[] => {
    if (typeof slot.chosen?.lng !== 'number' || typeof slot.chosen?.lat !== 'number') return []
    return [{
      id: slot.chosen.id || `slot-${slot.slot_index}`,
      title: slot.chosen.title,
      label: typeof slot.day_index === 'number' && (itinerary.days?.length || 0) > 1
        ? `D${slot.day_index + 1}.${position + 1}` : String(position + 1),
      status: 'confirmed',
      dayIndex: slot.day_index,
      time: slot.time,
      lat: slot.chosen.lat,
      lng: slot.chosen.lng,
    }]
  })
  const anchors = [
    ['S', itinerary.anchors?.start],
    ['E', itinerary.anchors?.end],
    ['H', itinerary.anchors?.lodging],
  ] as const
  const seen = new Set<string>()
  for (const [label, anchor] of anchors) {
    if (!anchor || seen.has(anchor.id)) continue
    seen.add(anchor.id)
    nodes.push({
      id: anchor.id, title: anchor.title, label, status: 'anchor',
      lat: anchor.lat, lng: anchor.lng,
    })
  }
  return nodes
}

function snapshotNodes(snapshot: PlanningSnapshot): MapNode[] {
  const confirmedByDay = new Map<number, number>()
  return [...snapshot.confirmed_nodes, ...snapshot.frontier_nodes].flatMap(node => {
    if (typeof node.lat !== 'number' || typeof node.lng !== 'number') return []
    const isCandidate = node.status === 'candidate'
    const dayIndex = typeof node.day_index === 'number' ? node.day_index : null
    let label = '?'
    if (!isCandidate) {
      if (node.role === 'lodging') label = 'H'
      else if (dayIndex !== null) {
        const position = (confirmedByDay.get(dayIndex) || 0) + 1
        confirmedByDay.set(dayIndex, position)
        label = `D${dayIndex + 1}.${position}`
      } else label = 'P'
    }
    return [{
      id: node.id,
      title: node.title || node.id,
      label,
      status: isCandidate ? 'candidate' as const : 'confirmed' as const,
      dayIndex,
      time: node.time,
      lat: node.lat,
      lng: node.lng,
    }]
  })
}

type Props = {
  itinerary?: Itinerary
  snapshot?: PlanningSnapshot
}

export function ItineraryMap({ itinerary, snapshot }: Props) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const mapRef = useRef<any>(null)
  const mapboxRef = useRef<any>(null)
  const markerRefs = useRef<any[]>([])
  const resizeObserver = useRef<ResizeObserver | null>(null)
  const latestData = useRef<{ features: RouteFeature[]; nodes: MapNode[]; bounds: [number, number][] }>({
    features: [], nodes: [], bounds: [],
  })
  const [status, setStatus] = useState<MapStatus>('loading')
  const [error, setError] = useState<string | null>(null)

  const features = useMemo(
    () => snapshot ? buildSnapshotRouteFeatures(snapshot) : (itinerary ? buildRouteFeatures(itinerary) : []),
    [itinerary, snapshot],
  )
  const nodes = useMemo(
    () => snapshot ? snapshotNodes(snapshot) : (itinerary ? finalNodes(itinerary) : []),
    [itinerary, snapshot],
  )
  const boundsPoints = useMemo(
    () => snapshot ? snapshotBounds(snapshot, features) : (itinerary ? routeBounds(itinerary, features) : []),
    [features, itinerary, snapshot],
  )
  latestData.current = { features, nodes, bounds: boundsPoints }

  const syncMapData = useCallback(() => {
    const map = mapRef.current
    const mapboxgl = mapboxRef.current
    if (!map || !mapboxgl) return
    const data = latestData.current
    // Do NOT gate this on map.isStyleLoaded(): the first run arrives via the
    // ready-status effect on the very commit installLayers flipped it, before
    // Mapbox's next render tick — the addSource/addLayer/addImage mutations
    // still leave the style "dirty" and isStyleLoaded() reports false. The
    // markers below are DOM overlays that don't need a loaded style, so gating
    // on that flag silently dropped every marker on the install pass — the
    // route line still drew because its data is inlined into the source. It was
    // only ever masked when a later data change re-ran this while the style
    // happened to be idle; on app restart the itinerary is present synchronously
    // and no later change fires, so the points stayed gone while the transit
    // trails rendered. Update the source only once it exists (optional chaining
    // handles the pre-install case).
    const source = map.getSource('itinerary-route')
    source?.setData({ type: 'FeatureCollection', features: data.features })
    markerRefs.current.forEach(marker => marker.remove())
    markerRefs.current = data.nodes.map(node => {
      const element = document.createElement('button')
      element.type = 'button'
      element.className = [
        'itinerary-map-marker',
        node.status === 'candidate' ? 'itinerary-map-candidate-marker' : '',
        node.status === 'anchor' ? 'itinerary-map-anchor-marker' : '',
      ].filter(Boolean).join(' ')
      element.textContent = node.label
      element.setAttribute(
        'aria-label',
        `${node.status === 'candidate' ? 'Candidate' : 'Selected'}: ${node.title}`,
      )
      return new mapboxgl.Marker({ element })
        .setLngLat([node.lng, node.lat])
        .setPopup(new mapboxgl.Popup({ offset: 24 }).setText(`${node.time || ''} ${node.title}`.trim()))
        .addTo(map)
    })
    if (data.bounds.length > 1) {
      const bounds = data.bounds.reduce(
        (current: any, point) => current.extend(point),
        new mapboxgl.LngLatBounds(data.bounds[0], data.bounds[0]),
      )
      map.fitBounds(bounds, { padding: 48, maxZoom: 15, duration: 0 })
    } else if (data.bounds.length === 1) {
      map.easeTo({ center: data.bounds[0], zoom: 14, duration: 0 })
    }
  }, [])

  useEffect(() => {
    if (!mapContainer.current) return
    if (typeof WebGL2RenderingContext === 'undefined') {
      setStatus('error')
      setError('The interactive map is unavailable in this browser.')
      return
    }
    let cancelled = false
    let usingOpenStreetMap = false
    const start = async () => {
      let token = ''
      try {
        token = await getPublicMapboxToken()
      } catch (reason) {
        console.warn('Failed to load public Mapbox config:', reason)
      }
      if (cancelled) return
      if (!token) {
        setStatus('error')
        setError('Map is unavailable because the public Mapbox token is not configured.')
        return
      }
      try {
        const mapboxgl = (await import('mapbox-gl')).default
        if (cancelled || !mapContainer.current) return
        mapboxgl.accessToken = token
        mapboxRef.current = mapboxgl
        const first = latestData.current.bounds[0] || [103.8198, 1.3521]
        const map = new mapboxgl.Map({
          container: mapContainer.current,
          style: buildMapboxStreetsStyle(token),
          center: first,
          zoom: 11,
        })
        mapRef.current = map
        map.addControl(new mapboxgl.NavigationControl(), 'top-right')
        const installLayers = () => {
          if (cancelled || map.getSource('itinerary-route')) return
          map.addSource('itinerary-route', {
            type: 'geojson', data: { type: 'FeatureCollection', features: latestData.current.features },
          })
          map.addLayer({
            id: 'itinerary-route-outline', type: 'line', source: 'itinerary-route',
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: { 'line-color': '#ffffff', 'line-width': 8, 'line-opacity': 0.9 },
          })
          // Each segment carries its own colour (MRT line / bus cyan / drive gold);
          // solid vs dashed is driven by the `dashed` flag (walk + estimates dashed).
          map.addLayer({
            id: 'itinerary-route-solid', type: 'line', source: 'itinerary-route',
            filter: ['==', ['get', 'dashed'], false],
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: { 'line-color': ['get', 'color'], 'line-width': 5, 'line-opacity': 0.92 },
          })
          map.addLayer({
            id: 'itinerary-route-dashed', type: 'line', source: 'itinerary-route',
            filter: ['==', ['get', 'dashed'], true],
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: { 'line-color': ['get', 'color'], 'line-width': 4, 'line-opacity': 0.8, 'line-dasharray': [2, 2] },
          })
          const arrow = directionArrowImage()
          if (arrow && !map.hasImage('itinerary-route-arrow')) map.addImage('itinerary-route-arrow', arrow)
          if (map.hasImage('itinerary-route-arrow')) {
            map.addLayer({
              id: 'itinerary-route-direction', type: 'symbol', source: 'itinerary-route',
              layout: {
                'symbol-placement': 'line', 'symbol-spacing': 90,
                'icon-image': 'itinerary-route-arrow', 'icon-size': 0.65,
                'icon-allow-overlap': true, 'icon-rotation-alignment': 'map',
              },
            })
          }
          // No direct syncMapData() here: flipping status to 'ready' runs the
          // sync effect on this same commit, and it reads latestData.current so
          // nothing staged between mount and style.load is lost. Calling it
          // here as well made every mount build its markers twice (tear down +
          // recreate) and fit bounds twice — and made the style.load re-fire on
          // the OpenStreetMap fallback churn markers that were still valid.
          setStatus('ready')
          map.resize()
        }
        map.on('style.load', installLayers)
        map.on('error', (event: any) => {
          if (cancelled) return
          if (event?.sourceId === 'mapbox-streets' && !usingOpenStreetMap) {
            usingOpenStreetMap = true
            setError('Mapbox background is unavailable. Showing the OpenStreetMap fallback.')
            map.setStyle(buildOpenStreetMapStyle())
          } else if (event?.sourceId === 'openstreetmap') {
            setError('The map background could not be loaded. Route and stop data remain available.')
          }
        })
        if (typeof ResizeObserver !== 'undefined' && mapContainer.current) {
          resizeObserver.current = new ResizeObserver(() => map.resize())
          resizeObserver.current.observe(mapContainer.current)
        }
      } catch (reason) {
        console.error('Failed to initialize itinerary map:', reason)
        setStatus('error')
        setError('The interactive map could not be loaded. Route stops remain available below.')
      }
    }
    void start()
    return () => {
      cancelled = true
      resizeObserver.current?.disconnect()
      markerRefs.current.forEach(marker => marker.remove())
      markerRefs.current = []
      mapRef.current?.remove()
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    if (status === 'ready') syncMapData()
  }, [boundsPoints, features, nodes, status, syncMapData])

  const travelMin = snapshot
    ? snapshot.days.reduce((sum, day) => sum + day.travel_min, 0)
    : itinerary?.totals.total_travel_min || 0

  return (
    <section className={`itinerary-map-panel${snapshot ? ' itinerary-map-provisional' : ''}`} aria-label={snapshot ? 'Provisional itinerary route map' : 'Itinerary route map'}>
      <header>
        <div>
          <strong>{snapshot ? 'Provisional route' : 'Route map'}</strong>
          <span>{travelMin} min travel{snapshot ? ` · revision ${snapshot.revision}` : ''}</span>
        </div>
        <div className="itinerary-map-legend" aria-label="Transport modes">
          {snapshot && <><span data-mode="selected">Selected</span><span data-mode="candidate">Candidate</span></>}
          <span data-mode="walk">Walk</span>
          {snapshot
            ? <span data-mode="pt">Transit</span>
            : <><span data-mode="mrt">MRT</span><span data-mode="bus">Bus</span></>}
          <span data-mode="drive">Drive</span>
        </div>
      </header>
      <div className="itinerary-map-body">
        <div className="itinerary-map-canvas-wrap">
          <div ref={mapContainer} className="itinerary-map-canvas" />
          {status === 'loading' && <div className="itinerary-map-status" role="status">Loading map...</div>}
        </div>
      </div>
      {error && <div className="itinerary-map-error" role="status">{error}</div>}
    </section>
  )
}
