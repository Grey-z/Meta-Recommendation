import { useEffect, useRef, useState } from 'react'
import 'mapbox-gl/dist/mapbox-gl.css'

import { buildPopupHtml, type MapDetails } from './mapPopup'

export type { MapDetails }

interface MapModalProps {
  isOpen: boolean
  onClose: () => void
  address: string
  placeName: string
  placeLabel?: string
  coordinates?: {
    latitude: number
    longitude: number
  }
  // Structured fields from the recommendation item the backend returned;
  // rendered in the popup instead of any client-side place-details lookup.
  details?: MapDetails
}

type LngLat = { lat: number; lng: number }

export function MapModal({ isOpen, onClose, address, placeName, placeLabel = 'Place', coordinates, details }: MapModalProps) {
  const mapRef = useRef<HTMLDivElement>(null)
  const mapInstanceRef = useRef<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [geocodedLocation, setGeocodedLocation] = useState<LngLat | null>(null)
  const [isGeocoding, setIsGeocoding] = useState(false)
  const [userLocation, setUserLocation] = useState<LngLat | null>(null)
  const [token, setToken] = useState<string | null>(null)

  // Resolve the Mapbox access token: build-time env first, backend /api/config
  // as the runtime fallback (same dual pattern the Google key used).
  useEffect(() => {
    if (!isOpen) return

    const loadToken = async () => {
      let value = import.meta.env.VITE_MAPBOX_TOKEN || ''
      if (!value) {
        try {
          const BASE_URL = import.meta.env.VITE_API_BASE_URL ||
                           (import.meta.env.PROD ? '' : 'http://localhost:8000')
          const response = await fetch(`${BASE_URL}/api/config`)
          if (response.ok) {
            const config = await response.json()
            value = config.mapboxToken || ''
          }
        } catch (err) {
          console.warn('Failed to load config from backend:', err)
        }
      }
      if (!value) {
        setError('Mapbox token is not configured. Please set VITE_MAPBOX_TOKEN environment variable.')
        return
      }
      setToken(value)
    }

    loadToken()
  }, [isOpen])

  // Geocode the address via the Mapbox Geocoding API only when the item carries
  // no coordinates (backend items usually include gps_coordinates already).
  useEffect(() => {
    if (!isOpen || !address || coordinates || !token) return

    let active = true
    const geocodeAddress = async () => {
      setIsGeocoding(true)
      setError(null)
      try {
        const url = `https://api.mapbox.com/search/geocode/v6/forward?q=${encodeURIComponent(address)}&limit=1&access_token=${token}`
        const response = await fetch(url)
        if (!response.ok) throw new Error(`Geocoding failed: ${response.status}`)
        const data = await response.json()
        const feature = data?.features?.[0]
        if (!feature?.geometry?.coordinates) throw new Error('Address not found')
        // Mapbox returns [lng, lat].
        const [lng, lat] = feature.geometry.coordinates
        if (active) setGeocodedLocation({ lat, lng })
      } catch (err) {
        console.error('Geocoding error:', err)
        if (active) {
          setError('Unable to locate address on map')
          setGeocodedLocation(null)
        }
      } finally {
        if (active) setIsGeocoding(false)
      }
    }

    geocodeAddress()
    return () => {
      active = false
    }
  }, [isOpen, address, coordinates, token])

  // Get user's current location (optional; silently unavailable when denied).
  useEffect(() => {
    if (!isOpen) return

    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          setUserLocation({
            lat: position.coords.latitude,
            lng: position.coords.longitude
          })
        },
        (err) => {
          console.warn('Geolocation error:', err)
        }
      )
    }
  }, [isOpen])

  // Initialize the Mapbox map. mapbox-gl is imported dynamically so it never
  // loads in jsdom test runs (no WebGL) and stays out of the main bundle.
  useEffect(() => {
    if (!isOpen || !mapRef.current || !token) return

    const finalLocation: LngLat | null = coordinates
      ? { lat: coordinates.latitude, lng: coordinates.longitude }
      : geocodedLocation
    if (!finalLocation) return

    let cancelled = false

    const initMap = async () => {
      let mapboxgl: any
      try {
        mapboxgl = (await import('mapbox-gl')).default
      } catch (err) {
        console.error('Failed to load Mapbox GL:', err)
        setError('Failed to load the map library')
        return
      }
      if (cancelled || !mapRef.current) return

      mapboxgl.accessToken = token
      const map = new mapboxgl.Map({
        container: mapRef.current,
        style: 'mapbox://styles/mapbox/streets-v12',
        center: [finalLocation.lng, finalLocation.lat],
        zoom: 15,
      })
      map.addControl(new mapboxgl.NavigationControl(), 'top-right')
      mapInstanceRef.current = map

      const popup = new mapboxgl.Popup({ offset: 32, maxWidth: '320px' })
        .setHTML(buildPopupHtml(placeName, address, details))
      new mapboxgl.Marker({ color: '#b37a4c' })
        .setLngLat([finalLocation.lng, finalLocation.lat])
        .setPopup(popup)
        .addTo(map)
        .togglePopup()

      if (userLocation) {
        new mapboxgl.Marker({ color: '#4285f4' })
          .setLngLat([userLocation.lng, userLocation.lat])
          .setPopup(new mapboxgl.Popup({ offset: 32 }).setHTML('<div style="padding: 4px 8px; color: #1a1a1a;"><strong>Your Location</strong></div>'))
          .addTo(map)

        // Driving route via the Mapbox Directions API, drawn as a GeoJSON line.
        try {
          const url = `https://api.mapbox.com/directions/v5/mapbox/driving/` +
            `${userLocation.lng},${userLocation.lat};${finalLocation.lng},${finalLocation.lat}` +
            `?geometries=geojson&overview=full&access_token=${token}`
          const response = await fetch(url)
          const data = response.ok ? await response.json() : null
          const geometry = data?.routes?.[0]?.geometry
          if (!cancelled && geometry) {
            const drawRoute = () => {
              if (map.getSource('route')) return
              map.addSource('route', { type: 'geojson', data: { type: 'Feature', properties: {}, geometry } })
              map.addLayer({
                id: 'route',
                type: 'line',
                source: 'route',
                layout: { 'line-join': 'round', 'line-cap': 'round' },
                paint: { 'line-color': '#4285f4', 'line-width': 5, 'line-opacity': 0.8 },
              })
            }
            if (map.isStyleLoaded()) drawRoute()
            else map.once('load', drawRoute)

            const bounds = geometry.coordinates.reduce(
              (acc: any, coord: [number, number]) => acc.extend(coord),
              new mapboxgl.LngLatBounds(geometry.coordinates[0], geometry.coordinates[0])
            )
            map.fitBounds(bounds, { padding: 50 })
          } else if (!cancelled) {
            const bounds = new mapboxgl.LngLatBounds()
            bounds.extend([userLocation.lng, userLocation.lat])
            bounds.extend([finalLocation.lng, finalLocation.lat])
            map.fitBounds(bounds, { padding: 50 })
          }
        } catch (err) {
          console.error('Directions request failed:', err)
        }
      }
    }

    initMap()

    return () => {
      cancelled = true
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove()
        mapInstanceRef.current = null
      }
    }
  }, [isOpen, coordinates, geocodedLocation, userLocation, address, placeName, details, token])

  const zoomToPlace = () => {
    if (!mapInstanceRef.current) return
    const finalLocation = coordinates
      ? { lat: coordinates.latitude, lng: coordinates.longitude }
      : geocodedLocation
    if (finalLocation) {
      mapInstanceRef.current.flyTo({ center: [finalLocation.lng, finalLocation.lat], zoom: 15 })
    }
  }

  const zoomToUser = () => {
    if (!mapInstanceRef.current || !userLocation) return
    mapInstanceRef.current.flyTo({ center: [userLocation.lng, userLocation.lat], zoom: 15 })
  }

  if (!isOpen) return null

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.5)',
          zIndex: 9998,
          backdropFilter: 'blur(2px)'
        }}
      />
      {/* Modal Container - Floating Window */}
      <div
        style={{
          position: 'fixed',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: '90%',
          maxWidth: '800px',
          height: '70vh',
          maxHeight: '600px',
          backgroundColor: 'var(--card-bg)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: '0 10px 40px rgba(0, 0, 0, 0.2)',
          zIndex: 9999,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          border: '1px solid var(--border)'
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '16px 20px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            backgroundColor: 'var(--card-bg)',
            flexShrink: 0
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <h3 style={{ margin: 0, color: 'var(--fg)', fontSize: '1.1em', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {placeName}
            </h3>
            <p style={{ margin: '4px 0 0 0', color: 'var(--fg-secondary)', fontSize: '0.875em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {address}
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginLeft: '16px' }}>
            <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
              <button
                onClick={zoomToPlace}
                style={{
                  background: 'linear-gradient(135deg, rgba(179, 122, 76, 0.95) 0%, rgba(157, 107, 66, 0.95) 100%)',
                  backdropFilter: 'blur(10px)',
                  border: '1px solid rgba(179, 122, 76, 0.3)',
                  cursor: 'pointer',
                  padding: '10px 16px',
                  borderRadius: '12px',
                  transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                  color: 'white',
                  fontSize: '0.875em',
                  fontWeight: 600,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  boxShadow: '0 4px 12px rgba(179, 122, 76, 0.25), 0 2px 4px rgba(0, 0, 0, 0.1)',
                  position: 'relative',
                  overflow: 'hidden'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'linear-gradient(135deg, rgba(179, 122, 76, 1) 0%, rgba(157, 107, 66, 1) 100%)'
                  e.currentTarget.style.transform = 'translateY(-2px) scale(1.02)'
                  e.currentTarget.style.boxShadow = '0 6px 20px rgba(179, 122, 76, 0.35), 0 4px 8px rgba(0, 0, 0, 0.15)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'linear-gradient(135deg, rgba(179, 122, 76, 0.95) 0%, rgba(157, 107, 66, 0.95) 100%)'
                  e.currentTarget.style.transform = 'translateY(0) scale(1)'
                  e.currentTarget.style.boxShadow = '0 4px 12px rgba(179, 122, 76, 0.25), 0 2px 4px rgba(0, 0, 0, 0.1)'
                }}
                title={`Click to zoom to ${placeLabel.toLowerCase()}`}
              >
                <span style={{ fontSize: '1.2em', lineHeight: 1, filter: 'drop-shadow(0 1px 2px rgba(0, 0, 0, 0.2))' }}>🍽️</span>
                <span style={{ letterSpacing: '0.3px' }}>{placeLabel}</span>
              </button>
              {userLocation && (
                <button
                  onClick={zoomToUser}
                  style={{
                    background: 'linear-gradient(135deg, rgba(66, 133, 244, 0.95) 0%, rgba(53, 122, 232, 0.95) 100%)',
                    backdropFilter: 'blur(10px)',
                    border: '1px solid rgba(66, 133, 244, 0.3)',
                    cursor: 'pointer',
                    padding: '10px 16px',
                    borderRadius: '12px',
                    transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                    color: 'white',
                    fontSize: '0.875em',
                    fontWeight: 600,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    boxShadow: '0 4px 12px rgba(66, 133, 244, 0.25), 0 2px 4px rgba(0, 0, 0, 0.1)',
                    position: 'relative',
                    overflow: 'hidden'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'linear-gradient(135deg, rgba(66, 133, 244, 1) 0%, rgba(53, 122, 232, 1) 100%)'
                    e.currentTarget.style.transform = 'translateY(-2px) scale(1.02)'
                    e.currentTarget.style.boxShadow = '0 6px 20px rgba(66, 133, 244, 0.35), 0 4px 8px rgba(0, 0, 0, 0.15)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'linear-gradient(135deg, rgba(66, 133, 244, 0.95) 0%, rgba(53, 122, 232, 0.95) 100%)'
                    e.currentTarget.style.transform = 'translateY(0) scale(1)'
                    e.currentTarget.style.boxShadow = '0 4px 12px rgba(66, 133, 244, 0.25), 0 2px 4px rgba(0, 0, 0, 0.1)'
                  }}
                  title="Click to zoom to your location"
                >
                  <span style={{ fontSize: '1.2em', lineHeight: 1, filter: 'drop-shadow(0 1px 2px rgba(0, 0, 0, 0.2))' }}>📍</span>
                  <span style={{ letterSpacing: '0.3px' }}>You</span>
                </button>
              )}
            </div>
            {/* Close Button */}
            <button
              onClick={onClose}
              style={{
                background: 'transparent',
                border: 'none',
                fontSize: '24px',
                cursor: 'pointer',
                color: 'var(--fg-secondary)',
                padding: '4px 8px',
                borderRadius: 'var(--radius-sm)',
                transition: 'all 0.2s',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: '32px',
                height: '32px',
                lineHeight: 1
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--hover-bg)'
                e.currentTarget.style.color = 'var(--fg)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent'
                e.currentTarget.style.color = 'var(--fg-secondary)'
              }}
              title="Close"
            >
              ×
            </button>
          </div>
        </div>

        {/* Map Container */}
        <div
          ref={mapRef}
          style={{
            width: '100%',
            flex: 1,
            minHeight: 0,
            position: 'relative'
          }}
        />
        {isGeocoding && (
          <div style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            padding: '12px 20px',
            backgroundColor: 'var(--card-bg)',
            borderRadius: 'var(--radius-md)',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
            color: 'var(--fg)',
            fontSize: '0.9em',
            zIndex: 1000,
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <span>Loading location...</span>
          </div>
        )}
        {error && (
          <div style={{
            padding: '8px 20px',
            backgroundColor: 'var(--hover-bg)',
            color: 'var(--muted)',
            fontSize: '0.8em',
            textAlign: 'center',
            borderTop: '1px solid var(--border)'
          }}>
            {error}
          </div>
        )}
      </div>
    </>
  )
}
