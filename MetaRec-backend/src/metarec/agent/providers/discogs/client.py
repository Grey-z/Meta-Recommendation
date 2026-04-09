from metarec.agent.providers.base import BaseAsyncClient
from typing import Optional

class DiscogsClient(BaseAsyncClient):
    """ Client for Discogs API. """
    def __init__(
        self,
        consumer_key: Optional[str]=None,
        consumer_secret: Optional[str]=None,
        token: Optional[str]=None,
    ):
        headers = {}
        if consumer_secret is not None and consumer_key is not None:
            headers['Authorization'] = f'Discogs key={consumer_key}, secret={consumer_secret}'
        elif token is not None:
            headers['Authorization'] = f'Discogs token={token}'
        
        super().__init__(
            base_url='https://api.discogs.com',
            headers=headers,
        )
    
    async def database_search(
        self,
        query: str,
    ):
        params = {
            #'release_title': query,
            'genre': query,
            #'query': query,
            'type': 'master',
        }
        resp = await self.client.get('/database/search', params=params)
        resp.raise_for_status()
        data = resp.json()
        
        return data['results']
        
if __name__ == '__main__':
    import asyncio
    client = DiscogsClient()
    res = asyncio.run(
        client.database_search('rock;punk')
    )
    for item in res:
        print(
            item['title'], 
            #item['master_id']
        )
