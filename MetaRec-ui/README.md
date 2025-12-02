MetaRec UI (React + Vite)

Run:
- npm install
- npm run dev

Environment Variables:
- VITE_API_BASE_URL=http://localhost:8000 (optional)
- VITE_GOOGLE_MAPS_API_KEY=your_google_maps_api_key (required for map functionality)

To get a Google Maps API key:
1. Go to https://console.cloud.google.com/
2. Create a new project or select an existing one
3. Enable the following APIs:
   - Maps JavaScript API
   - Geocoding API
   - Places API (required for restaurant details)
4. Create credentials (API Key)
5. (Optional but recommended) Restrict the API key to specific APIs and domains
6. Set the API key in your .env file: VITE_GOOGLE_MAPS_API_KEY=your_key_here

Note: The Places API is used to fetch detailed restaurant information (ratings, photos, opening hours, etc.) when clicking on map markers, similar to the Google Maps app experience.

Endpoint: POST /api/recommend

Request shape:
{ query, constraints: { restaurantType, flavorProfile, diningPurpose, budgetTier, location }, meta }

Response shape:
{ restaurants: [{ id, name, cuisine, location, rating, price, highlights, reason, reference }] }





