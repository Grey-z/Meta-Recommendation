import React, { useEffect, useRef, useState } from 'react'

interface MapModalProps {
  isOpen: boolean
  onClose: () => void
  address: string
  restaurantName: string
  coordinates?: {
    latitude: number
    longitude: number
  }
}

export function MapModal({ isOpen, onClose, address, restaurantName, coordinates }: MapModalProps) {
  const mapRef = useRef<HTMLDivElement>(null)
  const mapInstanceRef = useRef<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [geocodedLocation, setGeocodedLocation] = useState<{ lat: number; lng: number } | null>(null)
  const [isGeocoding, setIsGeocoding] = useState(false)
  const [userLocation, setUserLocation] = useState<{ lat: number; lng: number } | null>(null)

  // Geocode address to get coordinates
  useEffect(() => {
    if (!isOpen || !address) return
    
    // If coordinates are provided, use them directly
    if (coordinates) {
      setGeocodedLocation({ lat: coordinates.latitude, lng: coordinates.longitude })
      setIsGeocoding(false)
      return
    }

    // Otherwise, geocode the address
    const geocodeAddress = async () => {
      setIsGeocoding(true)
      setError(null)
      
      try {
        // Use OpenStreetMap Nominatim API for geocoding
        const encodedAddress = encodeURIComponent(address)
        const response = await fetch(
          `https://nominatim.openstreetmap.org/search?q=${encodedAddress}&format=json&limit=1&addressdetails=1`,
          {
            headers: {
              'User-Agent': 'MetaRecommendation/1.0' // Required by Nominatim
            }
          }
        )
        
        if (!response.ok) {
          throw new Error('Geocoding request failed')
        }
        
        const data = await response.json()
        
        if (data && data.length > 0) {
          const result = data[0]
          setGeocodedLocation({
            lat: parseFloat(result.lat),
            lng: parseFloat(result.lon)
          })
          setError(null)
        } else {
          throw new Error('Address not found')
        }
      } catch (err) {
        console.error('Geocoding error:', err)
        setError('Unable to locate address on map')
        setGeocodedLocation(null)
      } finally {
        setIsGeocoding(false)
      }
    }

    geocodeAddress()
  }, [isOpen, address, coordinates])

  // Get user's current location
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
          // Don't set error state, just silently fail - user location is optional
        }
      )
    }
  }, [isOpen])

  // Initialize map
  useEffect(() => {
    if (!isOpen || !mapRef.current) return
    // Wait for geocoding to complete if needed
    if (!coordinates && !geocodedLocation && isGeocoding) return

    // Get the final restaurant location
    const finalLocation = coordinates 
      ? { lat: coordinates.latitude, lng: coordinates.longitude }
      : geocodedLocation

    // Don't initialize map if we don't have restaurant location
    if (!finalLocation) return

    // Dynamically load Leaflet
    const loadLeaflet = async () => {
      try {
        // Check if already loaded
        if ((window as any).L) {
          initMap()
          return
        }

        // Load CSS
        const link = document.createElement('link')
        link.rel = 'stylesheet'
        link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'
        link.integrity = 'sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY='
        link.crossOrigin = ''
        document.head.appendChild(link)

        // Load JS
        const script = document.createElement('script')
        script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'
        script.integrity = 'sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo='
        script.crossOrigin = ''
        script.onload = initMap
        document.head.appendChild(script)
      } catch (err) {
        console.error('Failed to load Leaflet:', err)
        setError('Failed to load map')
      }
    }

    const initMap = () => {
      const L = (window as any).L
      if (!L || !mapRef.current) return

      // Get the final restaurant location
      const finalLocation = coordinates 
        ? { lat: coordinates.latitude, lng: coordinates.longitude }
        : geocodedLocation

      if (!finalLocation) return

      // Determine center point and zoom
      let centerLat = finalLocation.lat
      let centerLng = finalLocation.lng
      let zoom = 15

      // If we have both locations, center between them
      if (userLocation) {
        centerLat = (finalLocation.lat + userLocation.lat) / 2
        centerLng = (finalLocation.lng + userLocation.lng) / 2
        zoom = 13
      }

      // Create map
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove()
      }

      const map = L.map(mapRef.current, {
        center: [centerLat, centerLng],
        zoom: zoom
      })

      // Add OpenStreetMap layer
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19
      }).addTo(map)

      // Add restaurant marker
      const restaurantMarker = L.marker([finalLocation.lat, finalLocation.lng], {
        icon: L.divIcon({
          className: 'restaurant-marker',
          html: '<div style="background-color: #B37A4C; color: white; width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 20px; border: 3px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.3);">📍</div>',
          iconSize: [32, 32],
          iconAnchor: [16, 32]
        })
      }).addTo(map)
      restaurantMarker.bindPopup(`<strong>${restaurantName}</strong><br>${address}`).openPopup()

      // Add user location marker if available
      if (userLocation) {
        const userMarker = L.marker([userLocation.lat, userLocation.lng], {
          icon: L.divIcon({
            className: 'user-marker',
            html: '<div style="background-color: #A4C639; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 16px; border: 3px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.3);">👤</div>',
            iconSize: [28, 28],
            iconAnchor: [14, 28]
          })
        }).addTo(map)
        userMarker.bindPopup('<strong>Your Location</strong>')

        // Draw route between user and restaurant
        const route = L.polyline(
          [
            [userLocation.lat, userLocation.lng],
            [finalLocation.lat, finalLocation.lng]
          ],
          {
            color: '#B37A4C',
            weight: 3,
            opacity: 0.6,
            dashArray: '10, 10'
          }
        ).addTo(map)

        // Adjust map bounds to fit both markers
        map.fitBounds([
          [userLocation.lat, userLocation.lng],
          [finalLocation.lat, finalLocation.lng]
        ], { padding: [50, 50] })
      } else {
        // If no user location, just center on restaurant
        map.setView([finalLocation.lat, finalLocation.lng], 15)
      }

      mapInstanceRef.current = map
    }

    loadLeaflet()

    // Cleanup function
    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove()
        mapInstanceRef.current = null
      }
    }
  }, [isOpen, coordinates, geocodedLocation, isGeocoding, userLocation, address, restaurantName])

  // Function to zoom to restaurant location
  const zoomToRestaurant = () => {
    if (!mapInstanceRef.current) return
    
    const finalLocation = coordinates 
      ? { lat: coordinates.latitude, lng: coordinates.longitude }
      : geocodedLocation

    if (finalLocation) {
      mapInstanceRef.current.setView([finalLocation.lat, finalLocation.lng], 15, {
        animate: true,
        duration: 0.5
      })
    }
  }

  // Function to zoom to user location
  const zoomToUser = () => {
    if (!mapInstanceRef.current || !userLocation) return
    
    mapInstanceRef.current.setView([userLocation.lat, userLocation.lng], 15, {
      animate: true,
      duration: 0.5
    })
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
              {restaurantName}
            </h3>
            <p style={{ margin: '4px 0 0 0', color: 'var(--fg-secondary)', fontSize: '0.875em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {address}
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginLeft: '16px' }}>
            {/* Legend */}
            <div style={{ display: 'flex', gap: '12px', alignItems: 'center', fontSize: '0.8em', color: 'var(--fg-secondary)' }}>
              <div 
                onClick={zoomToRestaurant}
                style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: '4px',
                  cursor: 'pointer',
                  padding: '4px 8px',
                  borderRadius: 'var(--radius-sm)',
                  transition: 'all 0.2s'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--hover-bg)'
                  e.currentTarget.style.color = 'var(--fg)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent'
                  e.currentTarget.style.color = 'var(--fg-secondary)'
                }}
                title="Click to zoom to restaurant"
              >
                <div
                  style={{
                    width: '12px',
                    height: '12px',
                    borderRadius: '50%',
                    backgroundColor: '#B37A4C',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '8px'
                  }}
                >
                  📍
                </div>
                <span>Restaurant</span>
              </div>
              {userLocation && (
                <div 
                  onClick={zoomToUser}
                  style={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    gap: '4px',
                    cursor: 'pointer',
                    padding: '4px 8px',
                    borderRadius: 'var(--radius-sm)',
                    transition: 'all 0.2s'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = 'var(--hover-bg)'
                    e.currentTarget.style.color = 'var(--fg)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'transparent'
                    e.currentTarget.style.color = 'var(--fg-secondary)'
                  }}
                  title="Click to zoom to your location"
                >
                  <div
                    style={{
                      width: '12px',
                      height: '12px',
                      borderRadius: '50%',
                      backgroundColor: '#A4C639',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '8px'
                    }}
                  >
                    👤
                  </div>
                  <span>You</span>
                </div>
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

