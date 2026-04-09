from typing import List
from metarec.agent.providers.base import BaseAsyncClient

class MusicBrainzClient(BaseAsyncClient):
    """ Client for MusicBrainz API. """
    def __init__(self):
        headers = {
            'Accept': 'application/json'
        }
        
        #self.client = httpx.AsyncClient(
        super().__init__(
            base_url='https://musicbrainz.org',
            headers=headers,
        )
    
    async def search_recordings(
        self,
        query: str, #lucene query
        limit: int=25,
    ) -> List[any]:
        """
        Lucene search entries within MusicBrainz database.

        Example query:
e       - tag:(rock OR pop)
        - recording:september
        - tag:(math rock) AND data:[2020 TO *]
        """

        params = {
            'query': query,
            'limit': limit,
        }
        resp = await self.client.get('/ws/2/recording', params=params)

        resp.raise_for_status()
        data = resp.json()
        
        results = data['recordings']
        return results
    

if __name__ == '__main__':
    import asyncio
    import json

    client = MusicBrainzClient()
    res = asyncio.run(
        #client.search_recordings('recording:september')
        #client.search_recordings('tag:(rock OR pop)'),
        client.search_recordings('tag:(math rock OR pop) AND date:[2020 TO 2024]', limit=100),
    )
    for item in res:
        artists = item['artist-credit']
        artists = list(map(lambda x: x['name'], artists))
        artists = ', '.join(artists)
        label = '{title} - {artist}'.format(
            title=item['title'],
            artist=artists,
        )
        print(label)
        #print(json.dumps(item, indent=2))
    
    
