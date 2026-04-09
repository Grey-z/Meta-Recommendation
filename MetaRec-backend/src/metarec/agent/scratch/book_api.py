import os
import requests
from dotenv import load_dotenv, find_dotenv

dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

API_KEY = os.getenv('SERPAPI_KEY')

query = 'Fantasy books'

params = {
    'engine': 'amazon',
    'k': query,
    'api_key': API_KEY,
}

res = requests.get('https://serpapi.com/search.json', params=params)
data = res.json()

print(data)

