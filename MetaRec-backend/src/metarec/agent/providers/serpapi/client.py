from metarec.agent.providers.base import BaseAsyncClient
from typing import Optional

class SerpapiClient(BaseAsyncClient):
    def __init__(
        self,
        api_key: Optional[str]=None,
    ):
        params = {
            'api_key': api_key
        }
        super().__init__(
            base_url='https://serpapi.com',
            params=params,
        )
    
    async def search_google(
        self,
        query: str
    ):
        params = {
            'engine': 'google_maps',
            'search_type': 'search',
            'q': query,
        }
        resp = await self.client.get('/search.json', params=params)
        resp.raise_for_status()
        data = resp.json()

        results = data['local_results']
        return results
    
    async def search_yelp(
        self,
        query: str,
        location: str,
    ):
        params = {
            'engine': 'yelp',
            'find_desc': query,
            'find_loc': location,
        }
        resp = await self.client.get('/search.json', params=params)
        resp.raise_for_status()
        data = resp.json()
        
        results = data['organic_results']
        return results
    
    async def search_amazon(
        self,
        query: str,
    ):
        params = {
            'engine': 'amazon',
            'k': query,
        }
        resp = await self.client.get('/search.json', params=params)
        resp.raise_for_status()
        data = resp.json()
        results = data['organic_results']
        return results


if __name__ == '__main__':
    import os
    from dotenv import load_dotenv, find_dotenv
    import asyncio
    
    dotenv_path = find_dotenv()
    load_dotenv(dotenv_path)
    
    API_KEY = os.getenv('SERPAPI_KEY')
    client = SerpapiClient(api_key=API_KEY)
    
    data = asyncio.run(client.search_google('Sichuan Food'))
    print(data)
    
