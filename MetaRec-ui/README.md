MetaRec UI (React + Vite)

Run:
- npm install
- npm run dev

Optional env:
- VITE_API_BASE_URL=http://localhost:8000

Endpoint: POST /api/recommend

Request shape:
{ query, constraints: { restaurantType, flavorProfile, diningPurpose, budgetTier, location }, meta }

Response shape:
{ restaurants: [{ id, name, cuisine, location, rating, price, highlights, reason, reference }] }





