import os
import requests
from dotenv import load_dotenv, find_dotenv

dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

TOKEN = os.getenv('TMDB_API_ACCESS_TOKEN')

query = 'Sci-fi movie'

params = {
    'query': query,
}

headers = {
    'Authorization': f"Bearer {TOKEN}",
    'accept': 'application/json'
}

res = requests.get('https://api.themoviedb.org/3/search/movie', params=params, headers=headers)
data = res.json()

print(data)

