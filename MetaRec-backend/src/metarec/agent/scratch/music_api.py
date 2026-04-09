import os
import requests
from dotenv import load_dotenv, find_dotenv

dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

query = 'Nyan cat'

params = {
    'q': query,
}

res = requests.get('https://api.discogs.com/database/search', params=params)
data = res.json()

print(data)

