import { useEffect, useMemo, useRef, useState } from 'react'
import 'mapbox-gl/dist/mapbox-gl.css'

import type { Itinerary } from '../contracts/api-types'
import { buildRouteFeatures, routeBounds } from './itineraryMap'

type Props = { itinerary: Itinerary; onClose: () => void }

export function ItineraryMapModal({ itinerary, onClose }: Props) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const mapInstance = useRef<any>(null)
  const [error, setError] = useState<string | null>(null)
  const features = useMemo(() => buildRouteFeatures(itinerary), [itinerary])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  useEffect(() => {
    if (!mapContainer.current) return
    let cancelled = false
    let map: any
    const start = async () => {
      const token = import.meta.env.VITE_MAPBOX_TOKEN || ''
      if (!token) {
        setError('Map is unavailable because the public Mapbox token is not configured.')
        return
      }
      try {
        const mapboxgl = (await import('mapbox-gl')).default
        if (cancelled || !mapContainer.current) return
        mapboxgl.accessToken = token
        const boundsPoints = routeBounds(itinerary, features)
        const first = boundsPoints[0] || [103.8198, 1.3521]
        map = new mapboxgl.Map({
          container: mapContainer.current,
          style: 'mapbox://styles/mapbox/streets-v12',
          center: first,
          zoom: 11,
        })
        mapInstance.current = map
        map.addControl(new mapboxgl.NavigationControl(), 'top-right')
        map.once('load', () => {
          if (cancelled) return
          map.addSource('itinerary-route', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features },
          })
          map.addLayer({
            id: 'itinerary-live-route', type: 'line', source: 'itinerary-route',
            filter: ['==', ['get', 'estimated'], false],
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: { 'line-color': '#8A5324', 'line-width': 5, 'line-opacity': 0.82 },
          })
          map.addLayer({
            id: 'itinerary-estimated-route', type: 'line', source: 'itinerary-route',
            filter: ['==', ['get', 'estimated'], true],
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: { 'line-color': '#8A5324', 'line-width': 4, 'line-opacity': 0.58, 'line-dasharray': [2, 2] },
          })
        })
        itinerary.slots.forEach((slot, position) => {
          if (typeof slot.chosen?.lng !== 'number' || typeof slot.chosen?.lat !== 'number') return
          const element = document.createElement('button')
          element.type = 'button'
          element.className = 'itinerary-map-marker'
          element.textContent = slot.slot_role === 'start_anchor' ? 'S' : String(position + 1)
          element.setAttribute('aria-label', `${slot.label}: ${slot.chosen.title}`)
          new mapboxgl.Marker({ element })
            .setLngLat([slot.chosen.lng, slot.chosen.lat])
            .setPopup(new mapboxgl.Popup({ offset: 24 }).setText(`${slot.time || ''} ${slot.chosen.title}`.trim()))
            .addTo(map)
        })
        if (boundsPoints.length > 1) {
          const bounds = boundsPoints.reduce(
            (current: any, point) => current.extend(point),
            new mapboxgl.LngLatBounds(boundsPoints[0], boundsPoints[0]),
          )
          map.fitBounds(bounds, { padding: 64, maxZoom: 15 })
        }
      } catch (reason) {
        console.error('Failed to initialize itinerary map:', reason)
        setError('The interactive map could not be loaded. The itinerary list remains available.')
      }
    }
    void start()
    return () => {
      cancelled = true
      map?.remove()
      mapInstance.current = null
    }
  }, [features, itinerary])

  const focusStop = (lng?: number | null, lat?: number | null) => {
    if (typeof lng === 'number' && typeof lat === 'number') mapInstance.current?.flyTo({ center: [lng, lat], zoom: 15 })
  }

  return (
    <div className="itinerary-map-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
      <section className="itinerary-map-modal" role="dialog" aria-modal="true" aria-label="Itinerary route map">
        <header>
          <div><strong>{itinerary.location || 'Itinerary route'}</strong><span>{itinerary.totals.total_travel_min} min travel · finish {itinerary.totals.end_time || 'unknown'}</span></div>
          <button type="button" onClick={onClose} aria-label="Close route map"><i className="bi bi-x-lg" aria-hidden="true" /></button>
        </header>
        <div className="itinerary-map-body">
          <div ref={mapContainer} className="itinerary-map-canvas" />
          <aside aria-label="Route stops">
            <ol>
              {itinerary.slots.map((slot, position) => (
                <li key={slot.slot_index}>
                  <button type="button" onClick={() => focusStop(slot.chosen?.lng, slot.chosen?.lat)} disabled={!slot.chosen}>
                    <span>{slot.slot_role === 'start_anchor' ? 'S' : position + 1}</span>
                    <span><strong>{slot.chosen?.title || 'Missing stop'}</strong><small>{slot.time || slot.preferred_time || 'Flexible'} · {slot.label}</small></span>
                  </button>
                </li>
              ))}
            </ol>
          </aside>
        </div>
        {error && <div className="itinerary-map-error" role="status">{error}</div>}
      </section>
    </div>
  )
}

