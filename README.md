---
title: MetaRec Restaurant Recommender
emoji: 🍽️
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
license: mit
---

# MetaRec - Intelligent Restaurant Recommender 🍽️

An intelligent restaurant recommendation system with natural language understanding and interactive confirmation flow.

## ✨ Features

- 🧠 **Natural Language Understanding** - Just describe what you want in plain English
- 💬 **Interactive Confirmation** - AI confirms understanding before recommendations
- 🤔 **Thinking Process Visualization** - See how the AI thinks and decides
- 🔍 **Multi-dimensional Filtering** - Restaurant type, flavor, budget, location, dining purpose
- 🌶️ **Flavor Preference Matching** - Spicy, savory, sweet, sour, mild preferences
- 👤 **User Preference Learning** - Remembers and adapts to your preferences
- 🎯 **Smart Intent Recognition** - Understands confirmations, rejections, and new queries

## 🚀 Quick Start

### Using on Hugging Face Spaces

Simply visit the deployed Space and start asking for restaurant recommendations!

Example queries:
- "I want spicy Sichuan food for dinner"
- "Looking for a romantic restaurant for date night, budget around 100-200 SGD"
- "Best Italian restaurants near Marina Bay"

### Local Development

#### Backend (FastAPI)
```bash
cd MetaRec-backend
pip install -r requirements.txt
python main.py
```

Server runs at `http://localhost:8000` (or port 7860 for HF Spaces)

#### Frontend (React + Vite)
```bash
cd MetaRec-ui
npm install
npm run dev
```

App runs at `http://localhost:5173`

### Docker Deployment

```bash
docker build -t metarec .
docker run -p 7860:7860 metarec
```

## 📁 Project Structure

```
Meta-Recommendation/
├── MetaRec-backend/          # Python FastAPI backend
│   ├── main.py               # FastAPI server with static file serving
│   ├── service.py            # Core recommendation service
│   └── requirements.txt      # Python dependencies
├── MetaRec-ui/               # React frontend
│   ├── src/
│   │   ├── ui/               # React components
│   │   └── utils/            # API utilities
│   └── package.json          # Node dependencies
└── Dockerfile                # Multi-stage build for HF Spaces
```

## 🛠️ Technology Stack

### Backend
- **FastAPI** - Modern Python web framework
- **Pydantic** - Data validation
- **Uvicorn** - ASGI server

### Frontend
- **React** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool

## 🌐 API Endpoints

- `GET /api` - API information
- `GET /health` - Health check
- `POST /api/recommend` - Smart recommendation with intent analysis
- `POST /api/confirm` - Confirm preferences and start task
- `GET /api/status/{task_id}` - Get task status
- `POST /api/update-preferences` - Update user preferences
- `GET /api/user-preferences/{user_id}` - Get user preferences

Full API documentation available at `/docs` (Swagger UI)

## 📝 Example Usage

### Simple Query
```
User: "I want some good restaurants"
AI: Shows thinking process → Displays recommendations
```

### Complex Query with Confirmation
```
User: "I want spicy Sichuan food for friends gathering, budget 50-80 SGD per person"
AI: "Just to confirm, you're looking for Sichuan cuisine, spicy flavor..."
User: "Yes, that's correct"
AI: Shows thinking process → Displays recommendations
```

## 🎯 Deployment on Hugging Face Spaces

This project is configured for easy deployment on Hugging Face Spaces using Docker SDK.

### Deployment Steps

1. Create a new Space on Hugging Face
2. Select **Docker** as the SDK
3. Push this repository to the Space
4. HF Spaces will automatically build and deploy

The Dockerfile handles:
- Building the React frontend
- Setting up the Python backend
- Serving static files
- Running on port 7860 (HF Spaces requirement)

## 🔧 Configuration

### Environment Variables

- `PORT` - Server port (default: 7860 for HF Spaces, 8000 for local)
- `VITE_API_BASE_URL` - Frontend API base URL (optional, auto-detected)
- `VITE_GOOGLE_MAPS_API_KEY` - Google Maps API key (required for map functionality)

#### Google Maps API Key Setup

To enable map functionality, you need to configure a Google Maps API key:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the following APIs:
   - **Maps JavaScript API** - For displaying maps
   - **Geocoding API** - For address to coordinates conversion
   - **Places API** - For restaurant details (ratings, photos, opening hours, etc.)
4. Create credentials (API Key)
5. (Optional but recommended) Restrict the API key to specific APIs and HTTP referrers for security
6. Set the API key in your `.env` file:
   ```
   VITE_GOOGLE_MAPS_API_KEY=your_google_maps_api_key_here
   ```

### Local vs Production

The application automatically detects the environment:
- **Development**: Frontend uses `http://localhost:8000` for API
- **Production**: Frontend uses relative URLs (same domain as backend)

## 📄 License

MIT License - see LICENSE file for details

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## 📧 Contact

For questions or feedback, please open an issue on the repository.