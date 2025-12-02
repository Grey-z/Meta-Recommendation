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

// Google Maps types
declare global {
  interface Window {
    google: any
    initGoogleMaps: () => void
  }
}

export function MapModal({ isOpen, onClose, address, restaurantName, coordinates }: MapModalProps) {
  const mapRef = useRef<HTMLDivElement>(null)
  const mapInstanceRef = useRef<any>(null)
  const markersRef = useRef<any[]>([])
  const infoWindowRef = useRef<any>(null)
  const directionsRendererRef = useRef<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [geocodedLocation, setGeocodedLocation] = useState<{ lat: number; lng: number } | null>(null)
  const [isGeocoding, setIsGeocoding] = useState(false)
  const [userLocation, setUserLocation] = useState<{ lat: number; lng: number } | null>(null)
  const [isGoogleMapsLoaded, setIsGoogleMapsLoaded] = useState(false)
  const [placeDetails, setPlaceDetails] = useState<any>(null)
  const [apiKey, setApiKey] = useState<string | null>(null)

  // Geocode address to get coordinates using Google Maps Geocoding API
  useEffect(() => {
    if (!isOpen || !address) return
    
    // If coordinates are provided, use them directly
    if (coordinates) {
      setGeocodedLocation({ lat: coordinates.latitude, lng: coordinates.longitude })
      setIsGeocoding(false)
      return
    }

    // Wait for Google Maps to be loaded
    if (!isGoogleMapsLoaded) return

    // Otherwise, geocode the address using Google Maps Geocoding API
    const geocodeAddress = async () => {
      setIsGeocoding(true)
      setError(null)
      
      try {
        const google = window.google
        if (!google || !google.maps || !google.maps.Geocoder) {
          throw new Error('Google Maps not loaded')
        }

        const geocoder = new google.maps.Geocoder()
        
        geocoder.geocode({ address: address }, (results: any[], status: string) => {
          if (status === 'OK' && results && results.length > 0) {
            const location = results[0].geometry.location
            setGeocodedLocation({
              lat: location.lat(),
              lng: location.lng()
            })
            setError(null)
          } else {
            throw new Error('Address not found')
          }
          setIsGeocoding(false)
        })
      } catch (err) {
        console.error('Geocoding error:', err)
        setError('Unable to locate address on map')
        setGeocodedLocation(null)
        setIsGeocoding(false)
      }
    }

    geocodeAddress()
  }, [isOpen, address, coordinates, isGoogleMapsLoaded])

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

  // Load API key from backend or environment
  useEffect(() => {
    if (!isOpen) return

    const loadApiKey = async () => {
      // First try to get from build-time environment variable
      let key = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || ''
      
      // If not available, try to get from backend API
      if (!key) {
        try {
          const BASE_URL = import.meta.env.VITE_API_BASE_URL || 
                           (import.meta.env.PROD ? '' : 'http://localhost:8000')
          const response = await fetch(`${BASE_URL}/api/config`)
          if (response.ok) {
            const config = await response.json()
            key = config.googleMapsApiKey || ''
          }
        } catch (err) {
          console.warn('Failed to load config from backend:', err)
        }
      }

      if (!key) {
        setError('Google Maps API key is not configured. Please set VITE_GOOGLE_MAPS_API_KEY environment variable.')
        return
      }

      setApiKey(key)
    }

    loadApiKey()
  }, [isOpen])

  // Load Google Maps API
  useEffect(() => {
    if (!isOpen || !apiKey) return

    // Check if Google Maps is already loaded
    if (window.google && window.google.maps) {
      setIsGoogleMapsLoaded(true)
      return
    }

    // Check if script is already being loaded
    if (document.querySelector('script[src*="maps.googleapis.com"]')) {
      // Wait for it to load
      const checkLoaded = setInterval(() => {
        if (window.google && window.google.maps) {
          setIsGoogleMapsLoaded(true)
          clearInterval(checkLoaded)
        }
      }, 100)
      return () => clearInterval(checkLoaded)
    }

    // Load Google Maps JavaScript API with Places library
    const script = document.createElement('script')
    script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&libraries=geometry,places`
    script.async = true
    script.defer = true
    script.onload = () => {
      setIsGoogleMapsLoaded(true)
    }
    script.onerror = () => {
      setError('Failed to load Google Maps')
    }
    document.head.appendChild(script)

    // Cleanup function
    return () => {
      // Don't remove the script, it might be used elsewhere
    }
  }, [isOpen, apiKey])

  // Initialize Google Maps
  useEffect(() => {
    if (!isOpen || !mapRef.current || !isGoogleMapsLoaded) return
    // Wait for geocoding to complete if needed
    if (!coordinates && !geocodedLocation && isGeocoding) return

    // Get the final restaurant location
    const finalLocation = coordinates 
      ? { lat: coordinates.latitude, lng: coordinates.longitude }
      : geocodedLocation

    // Don't initialize map if we don't have restaurant location
    if (!finalLocation) return

    const google = window.google
    if (!google || !google.maps) return

    // Clear existing markers if map instance exists
    if (mapInstanceRef.current) {
      markersRef.current.forEach(marker => marker.setMap(null))
      markersRef.current = []
    }

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
    const map = new google.maps.Map(mapRef.current, {
      center: { lat: centerLat, lng: centerLng },
      zoom: zoom,
      mapTypeControl: true,
      streetViewControl: true,
      fullscreenControl: true
    })

    // Create restaurant marker using Google Maps default marker
    const restaurantMarker = new google.maps.Marker({
      position: { lat: finalLocation.lat, lng: finalLocation.lng },
      map: map,
      title: restaurantName
    })

    // Create InfoWindow with loading content
    const restaurantInfoWindow = new google.maps.InfoWindow({
      content: `<div style="padding: 12px; min-width: 250px;">
        <div style="font-weight: 600; font-size: 16px; margin-bottom: 4px;">${restaurantName}</div>
        <div style="color: #666; font-size: 14px;">${address}</div>
        <div style="margin-top: 8px; color: #666; font-size: 12px;">Loading details...</div>
      </div>`
    })
    
    // Open InfoWindow initially
    restaurantInfoWindow.open(map, restaurantMarker)
    infoWindowRef.current = restaurantInfoWindow

    // Function to search for place details using Google Places API
    const searchPlaceDetails = () => {
      if (!google.maps.places) {
        // Fallback if Places API is not available - show basic info
        updateInfoWindow(null)
        return
      }

      const service = new google.maps.places.PlacesService(map)
      const request = {
        query: `${restaurantName}, ${address}`,
        fields: ['name', 'formatted_address', 'rating', 'user_ratings_total', 'price_level', 
                 'opening_hours', 'photos', 'place_id', 'website', 'formatted_phone_number', 'reviews']
      }

      service.textSearch(request, (results: any[], status: string) => {
        if (status === google.maps.places.PlacesServiceStatus.OK && results && results.length > 0) {
          const place = results[0]
          
          // Get detailed place information
          const placeId = place.place_id
          const detailsRequest = {
            placeId: placeId,
            fields: ['name', 'formatted_address', 'rating', 'user_ratings_total', 'price_level',
                     'opening_hours', 'photos', 'website', 'formatted_phone_number', 'reviews',
                     'geometry', 'url']
          }

          service.getDetails(detailsRequest, (placeDetailsResult: any, detailsStatus: string) => {
            if (detailsStatus === google.maps.places.PlacesServiceStatus.OK && placeDetailsResult) {
              setPlaceDetails(placeDetailsResult)
              updateInfoWindow(placeDetailsResult)
            } else {
              // If detailed search fails, use basic place info
              setPlaceDetails(place)
              updateInfoWindow(place)
            }
          })
        } else {
          // If search fails, show basic info with link to Google Maps
          console.log('Place search failed:', status)
          updateInfoWindow(null)
        }
      })
    }

    // Function to create rich InfoWindow content
    const updateInfoWindow = (place: any) => {
      let content = `<div style="padding: 0; max-width: 300px;">`
      
      // Header with name
      content += `<div style="padding: 12px 16px; border-bottom: 1px solid #e0e0e0;">
        <div style="font-weight: 600; font-size: 16px; margin-bottom: 4px; color: #1a1a1a;">${restaurantName}</div>
        <div style="color: #666; font-size: 14px;">${address}</div>
      </div>`

      // Details section
      if (place) {
        content += `<div style="padding: 12px 16px;">`
        
        // Rating
        if (place.rating) {
          const stars = '★'.repeat(Math.round(place.rating))
          const ratingColor = place.rating >= 4.0 ? '#0f9d58' : place.rating >= 3.0 ? '#fbbc04' : '#ea4335'
          content += `<div style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
            <span style="color: ${ratingColor}; font-size: 18px;">${stars}</span>
            <span style="font-weight: 600; font-size: 14px;">${place.rating.toFixed(1)}</span>
            ${place.user_ratings_total ? `<span style="color: #666; font-size: 12px;">(${place.user_ratings_total.toLocaleString()} reviews)</span>` : ''}
          </div>`
        }

        // Price level
        if (place.price_level !== undefined) {
          const priceSymbols = '$'.repeat(place.price_level)
          content += `<div style="margin-bottom: 8px; color: #666; font-size: 14px;">
            Price: <span style="font-weight: 600;">${priceSymbols}</span>
          </div>`
        }

        // Opening hours
        if (place.opening_hours && place.opening_hours.weekday_text) {
          const isOpen = place.opening_hours.isOpen()
          content += `<div style="margin-bottom: 8px;">
            <div style="font-weight: 600; font-size: 14px; color: ${isOpen ? '#0f9d58' : '#ea4335'};">
              ${isOpen ? '● Open now' : '● Closed'}
            </div>
            <div style="color: #666; font-size: 12px; margin-top: 2px;">
              ${place.opening_hours.weekday_text[new Date().getDay()] || ''}
            </div>
          </div>`
        }

        // Photo
        if (place.photos && place.photos.length > 0) {
          const photoUrl = place.photos[0].getUrl({ maxWidth: 300, maxHeight: 200 })
          content += `<div style="margin-bottom: 8px;">
            <img src="${photoUrl}" alt="${restaurantName}" style="width: 100%; border-radius: 4px; object-fit: cover; height: 120px;" />
          </div>`
        }

        content += `</div>` // Close details section

        // Actions section
        content += `<div style="padding: 8px 16px; border-top: 1px solid #e0e0e0; display: flex; gap: 8px;">`
        
        // Directions button
        const directionsUrl = `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(address)}`
        content += `<a href="${directionsUrl}" target="_blank" style="flex: 1; padding: 8px; background: #4285f4; color: white; text-decoration: none; text-align: center; border-radius: 4px; font-size: 14px; font-weight: 500;">
          Directions
        </a>`
        
        // View in Google Maps
        if (place.url) {
          content += `<a href="${place.url}" target="_blank" style="flex: 1; padding: 8px; background: #f1f3f4; color: #1a1a1a; text-decoration: none; text-align: center; border-radius: 4px; font-size: 14px; font-weight: 500;">
            View
          </a>`
        }
        
        content += `</div>` // Close actions section
      } else {
        // Basic info if place details not available
        content += `<div style="padding: 12px 16px;">
          <a href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${restaurantName}, ${address}`)}" target="_blank" style="display: inline-block; padding: 8px 16px; background: #4285f4; color: white; text-decoration: none; border-radius: 4px; font-size: 14px; font-weight: 500;">
            View in Google Maps
          </a>
        </div>`
      }

      content += `</div>` // Close main container

      restaurantInfoWindow.setContent(content)
      restaurantInfoWindow.open(map, restaurantMarker)
    }

    // Search for place details
    searchPlaceDetails()

    // Add click listener to marker - reopen InfoWindow when clicked
    restaurantMarker.addListener('click', () => {
      restaurantInfoWindow.open(map, restaurantMarker)
    })

    markersRef.current.push(restaurantMarker)

    // Add user location marker if available using Google Maps default marker
    if (userLocation) {
      const userMarker = new google.maps.Marker({
        position: { lat: userLocation.lat, lng: userLocation.lng },
        map: map,
        title: 'Your Location'
      })

      const userInfoWindow = new google.maps.InfoWindow({
        content: '<div style="padding: 8px;"><strong>Your Location</strong></div>'
      })
      userMarker.addListener('click', () => {
        userInfoWindow.open(map, userMarker)
      })
      markersRef.current.push(userMarker)

      // Calculate and display driving route
      const directionsService = new google.maps.DirectionsService()
      const directionsRenderer = new google.maps.DirectionsRenderer({
        map: map,
        suppressMarkers: true, // Hide default markers since we already have custom markers
        preserveViewport: false, // Allow map to adjust viewport to fit route
        polylineOptions: {
          strokeColor: '#4285f4',
          strokeWeight: 5,
          strokeOpacity: 0.8
        }
      })

      directionsRendererRef.current = directionsRenderer

      // Request driving directions
      directionsService.route(
        {
          origin: { lat: userLocation.lat, lng: userLocation.lng },
          destination: { lat: finalLocation.lat, lng: finalLocation.lng },
          travelMode: google.maps.TravelMode.DRIVING
        },
        (result: any, status: string) => {
          if (status === 'OK') {
            directionsRenderer.setDirections(result)
            
            // Adjust map bounds to fit the route
            if (result.routes && result.routes[0] && result.routes[0].bounds) {
              map.fitBounds(result.routes[0].bounds, { padding: 50 })
            } else {
              // Fallback: adjust bounds to fit both markers
              const bounds = new google.maps.LatLngBounds()
              bounds.extend({ lat: userLocation.lat, lng: userLocation.lng })
              bounds.extend({ lat: finalLocation.lat, lng: finalLocation.lng })
              map.fitBounds(bounds, { padding: 50 })
            }
          } else {
            console.error('Directions request failed:', status)
            // If route fails, just adjust bounds to fit both markers
            const bounds = new google.maps.LatLngBounds()
            bounds.extend({ lat: userLocation.lat, lng: userLocation.lng })
            bounds.extend({ lat: finalLocation.lat, lng: finalLocation.lng })
            map.fitBounds(bounds, { padding: 50 })
          }
        }
      )
    } else {
      // If no user location, just center on restaurant
      map.setCenter({ lat: finalLocation.lat, lng: finalLocation.lng })
      map.setZoom(15)
    }

    mapInstanceRef.current = map

    // Cleanup function
    return () => {
      // Clear markers
      markersRef.current.forEach(marker => marker.setMap(null))
      markersRef.current = []
      
      // Clear directions renderer
      if (directionsRendererRef.current) {
        directionsRendererRef.current.setMap(null)
        directionsRendererRef.current = null
      }
    }
  }, [isOpen, coordinates, geocodedLocation, isGeocoding, userLocation, address, restaurantName, isGoogleMapsLoaded])

  // Function to zoom to restaurant location
  const zoomToRestaurant = () => {
    if (!mapInstanceRef.current) return
    
    const finalLocation = coordinates 
      ? { lat: coordinates.latitude, lng: coordinates.longitude }
      : geocodedLocation

    if (finalLocation) {
      mapInstanceRef.current.setCenter({ lat: finalLocation.lat, lng: finalLocation.lng })
      mapInstanceRef.current.setZoom(15)
    }
  }

  // Function to zoom to user location
  const zoomToUser = () => {
    if (!mapInstanceRef.current || !userLocation) return
    
    mapInstanceRef.current.setCenter({ lat: userLocation.lat, lng: userLocation.lng })
    mapInstanceRef.current.setZoom(15)
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
            {/* Legend - Simplified for Google Maps default markers */}
            <div style={{ display: 'flex', gap: '12px', alignItems: 'center', fontSize: '0.8em', color: 'var(--fg-secondary)' }}>
              <button 
                onClick={zoomToRestaurant}
                style={{ 
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  padding: '4px 8px',
                  borderRadius: 'var(--radius-sm)',
                  transition: 'all 0.2s',
                  color: 'var(--fg-secondary)',
                  fontSize: '0.8em'
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
                Restaurant
              </button>
              {userLocation && (
                <button 
                  onClick={zoomToUser}
                  style={{ 
                    background: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    padding: '4px 8px',
                    borderRadius: 'var(--radius-sm)',
                    transition: 'all 0.2s',
                    color: 'var(--fg-secondary)',
                    fontSize: '0.8em'
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
                  Your Location
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

