# MetaRec API Documentation

## Overview
MetaRec is a restaurant recommendation system with AI-powered preference extraction and interactive confirmation flow. The API provides intelligent restaurant recommendations based on user queries and preferences.

## Base URL
```
http://localhost:8000
```

## Authentication
No authentication required for current implementation.

---

## API Endpoints

### 1. Health Check

#### GET `/health`
Check if the API is running and healthy.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

---

### 2. Root Endpoint

#### GET `/`
Get basic API information.

**Response:**
```json
{
  "message": "MetaRec API is running!",
  "version": "1.0.0"
}
```

---

### 3. Smart Restaurant Recommendations (Primary)

#### POST `/api/recommend`
Get restaurant recommendations based on user query only. The API will intelligently extract preferences from the query.

**Request Body:**
```typescript
{
  "query": string                    // User's natural language query
}
```

**Response:**
```typescript
{
  "restaurants": Restaurant[],        // Array of recommended restaurants (empty for confirmation)
  "confirmation_request": {          // Always present for confirmation
    "message": string,               // Full prompt with extracted preferences
    "preferences": Record<string, any>, // Extracted preferences
    "needs_confirmation": boolean    // Always true
  }
}
```

**Example Request:**
```json
{
  "query": "I want a romantic dinner for date night, budget 100-200 SGD, near Marina Bay"
}
```

**Example Response:**
```json
{
  "restaurants": [],
  "confirmation_request": {
    "message": "Based on your query 'I want a romantic dinner for date night, budget 100-200 SGD, near Marina Bay', I understand you want:\n\n• Restaurant Type: Fine Dining\n• Dining Purpose: Date Night\n• Budget Range: 100-200 SGD per person\n• Location: Marina Bay\n\nIs this correct?",
    "preferences": {
      "restaurant_types": ["fine-dining"],
      "flavor_profiles": ["any"],
      "dining_purpose": "date-night",
      "budget_range": {
        "min": 100,
        "max": 200,
        "currency": "SGD",
        "per": "person"
      },
      "location": "Marina Bay"
    },
    "needs_confirmation": true
  }
}
```

---

### 4. Direct Recommendations with Constraints

#### POST `/api/recommend-with-constraints`
Get restaurant recommendations with explicit constraints (bypasses confirmation).

**Request Body:**
```typescript
{
  "query": string,                    // User's natural language query
  "constraints": {
    "restaurantTypes": string[],      // ["casual", "fine-dining", "fast-casual", "street-food", "buffet", "cafe"]
    "flavorProfiles": string[],       // ["spicy", "savory", "sweet", "sour", "mild"]
    "diningPurpose": string,          // "date-night", "family", "business", "solo", "friends", "celebration"
    "budgetRange": {
      "min": number,                  // Optional: minimum budget
      "max": number,                  // Optional: maximum budget
      "currency": "SGD" | "USD" | "CNY" | "EUR",
      "per": "person" | "table"
    },
    "location": string                // Optional: location preference
  },
  "meta": {
    "source": string,                 // "MetaRec-UI"
    "sentAt": string,                 // ISO timestamp
    "uiVersion": string               // "0.0.1"
  }
}
```

**Response:**
```typescript
{
  "restaurants": Restaurant[],        // Array of recommended restaurants
  "thinking_steps": ThinkingStep[]    // AI thinking process
}
```

**Response Types:**
```typescript
interface Restaurant {
  id: string
  name: string
  cuisine?: string
  location?: string
  rating?: number
  price?: number
  highlights?: string[]
  reason?: string
  reference?: string
}

interface ThinkingStep {
  step: string
  description: string
  status: "thinking" | "completed" | "error"
  details?: string
}
```

---

### 5. Confirm Preferences and Start Processing

#### POST `/api/confirm`
Confirm user preferences and start background processing task.

**Request Body:**
```typescript
{
  "query": string,                    // Original user query
  "preferences": Record<string, any>  // Extracted preferences from confirmation
}
```

**Response:**
```typescript
{
  "task_id": string,                  // Task ID for polling status
  "message": string                   // Confirmation message
}
```

**Example Request:**
```json
{
  "query": "I want a romantic dinner for date night, budget 100-200 SGD, near Marina Bay",
  "preferences": {
    "restaurant_types": ["fine-dining"],
    "flavor_profiles": ["any"],
    "dining_purpose": "date-night",
    "budget_range": {
      "min": 100,
      "max": 200,
      "currency": "SGD",
      "per": "person"
    },
    "location": "Marina Bay"
  }
}
```

**Example Response:**
```json
{
  "task_id": "123e4567-e89b-12d3-a456-426614174000",
  "message": "Task started successfully"
}
```

---

### 6. Get Task Status

#### GET `/api/status/{task_id}`
Get the current status of a processing task.

**Response:**
```typescript
{
  "task_id": string,
  "status": "processing" | "completed" | "error",
  "progress": number,                 // 0-100
  "message": string,
  "result"?: RecommendationResponse,  // Present when completed
  "error"?: string                   // Present when error
}
```

**Example Response (Processing):**
```json
{
  "task_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "processing",
  "progress": 50,
  "message": "Searching restaurant database...",
  "result": null,
  "error": null
}
```

**Example Response (Completed):**
```json
{
  "task_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "completed",
  "progress": 100,
  "message": "Recommendations ready!",
  "result": {
    "restaurants": [
      {
        "id": "1",
        "name": "Odette",
        "cuisine": "French",
        "location": "Marina Bay",
        "rating": 4.8,
        "price": "$$$$",
        "highlights": ["Fine Dining", "3 Michelin Stars", "Romantic"],
        "reason": "World-class French cuisine with impeccable service and atmosphere",
        "reference": "https://www.odetterestaurant.com"
      }
    ],
    "thinking_steps": [
      {
        "step": "analyze_query",
        "description": "Analyzing your requirements...",
        "status": "completed",
        "details": "Identified keywords: romantic, dinner, date, night, budget, SGD, Marina, Bay"
      }
    ]
  },
  "error": null
}
```

---

### 7. Update Preferences

#### POST `/api/update-preferences`
Update user preferences and get processed constraints.

**Request Body:**
```typescript
{
  "restaurantTypes": string[],        // ["casual", "fine-dining", "fast-casual", "street-food", "buffet", "cafe"]
  "flavorProfiles": string[],         // ["spicy", "savory", "sweet", "sour", "mild"]
  "diningPurpose": string,            // "date-night", "family", "business", "solo", "friends", "celebration"
  "budgetRange": {
    "min": number,                    // Optional: minimum budget
    "max": number,                    // Optional: maximum budget
    "currency": "SGD" | "USD" | "CNY" | "EUR",
    "per": "person" | "table"
  },
  "location": string                  // Optional: location preference
}
```

**Response:**
```typescript
{
  "message": string,
  "preferences": Record<string, any>  // Processed preferences
}
```

---

### 5. Get All Restaurants (Debug)

#### GET `/api/restaurants`
Get all available restaurants in the database (for debugging purposes).

**Response:**
```json
{
  "restaurants": [
    {
      "id": "1",
      "name": "Din Tai Fung",
      "cuisine": "Taiwanese",
      "location": "Orchard",
      "rating": 4.2,
      "price": "$$",
      "highlights": ["Xiao Long Bao", "Noodles", "Family-friendly"],
      "reason": "Perfect for family dining with authentic Taiwanese cuisine and famous soup dumplings",
      "reference": "https://www.dintaifung.com.sg"
    }
  ]
}
```

---

## Frontend-Backend Interaction Flow

### 1. Smart Recommendation Flow (Primary)
```
1. Frontend → POST /api/recommend (query only)
2. Backend → Response with confirmation_request (always)
3. Frontend → Display confirmation dialog with full prompt
4. User → Confirm preferences
5. Frontend → POST /api/confirm (query + preferences)
6. Backend → Response with task_id
7. Frontend → Poll GET /api/status/{task_id} until completed
8. Backend → Response with recommendations + thinking_steps
```

### 2. Direct Recommendation Flow (Bypass Confirmation)
```
1. Frontend → POST /api/recommend-with-constraints (query + constraints)
2. Backend → Response with recommendations + thinking_steps
```

### 3. Manual Preferences Update
```
1. Frontend → User modifies preferences in UI
2. Frontend → POST /api/update-preferences (preferences)
3. Backend → Response with processed preferences
4. Frontend → Update UI with processed preferences
```

---

## Error Handling

### HTTP Status Codes
- `200` - Success
- `422` - Validation Error (invalid request body)
- `500` - Internal Server Error

### Error Response Format
```json
{
  "detail": "Error message description"
}
```

### Common Error Scenarios
1. **Invalid JSON**: Malformed request body
2. **Missing required fields**: Required fields not provided
3. **Server error**: Internal processing error

---

## Data Models

### Restaurant Types
- `casual` - Casual Dining
- `fine-dining` - Fine Dining
- `fast-casual` - Fast Casual
- `street-food` - Street Food
- `buffet` - Buffet
- `cafe` - Cafe

### Flavor Profiles
- `spicy` - Spicy
- `savory` - Savory
- `sweet` - Sweet
- `sour` - Sour
- `mild` - Mild

### Dining Purposes
- `date-night` - Date Night
- `family` - Family Dining
- `business` - Business Meeting
- `solo` - Solo Dining
- `friends` - Friends Gathering
- `celebration` - Celebration

### Price Levels
- `$` - Budget (under $20)
- `$$` - Moderate ($20-40)
- `$$$` - Expensive ($40-80)
- `$$$$` - Very Expensive ($80+)

---

## CORS Configuration
The API is configured to accept requests from:
- `http://localhost:5173` (Vite dev server)
- `http://127.0.0.1:5173` (Alternative localhost)

---

## Rate Limiting
Currently no rate limiting implemented.

---

## Testing
Use the interactive API documentation at:
```
http://localhost:8000/docs
```

This provides a Swagger UI for testing all endpoints directly in the browser.
