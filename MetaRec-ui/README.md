MetaRec UI (React + Vite)

Run:
- npm install
- npm run dev

Environment Variables:
- VITE_API_BASE_URL=http://localhost:8000 (optional)
- VITE_MAPBOX_TOKEN=your_mapbox_access_token (required for map functionality)

To get a Mapbox access token:
1. Go to https://account.mapbox.com/ and create a free account
2. Copy the default public token (pk.*) or create a new one
3. (Optional but recommended) Add URL restrictions to the token
4. Set the token in your .env file: VITE_MAPBOX_TOKEN=pk.your_token_here

Notes:
- The map, geocoding fallback, and driving-route drawing all use Mapbox APIs,
  each with a free monthly quota (50k map loads, 100k geocoding, 100k directions).
- Public tokens (pk.*) are designed to be shipped in frontend bundles.
- The map popup shows details (rating, price, hours, phone) from the
  recommendation data the backend already returned — no client-side
  place-details API is called.

Endpoint: POST /api/recommend

Request shape:
{ query, constraints: { restaurantType, flavorProfile, diningPurpose, budgetTier, location }, meta }

Response shape:
{ restaurants: [{ id, name, cuisine, location, rating, price, highlights, reason, reference }] }
