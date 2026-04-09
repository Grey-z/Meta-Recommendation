from metarec.agent.providers.base import BaseAsyncClient
from .utils import format_book_genre_search_query

class HardCoverClient(BaseAsyncClient):
    def __init__(
        self,
        api_key: str,
    ):
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        super().__init__(
            base_url='https://api.hardcover.app/v1/graphql',
            headers=headers,
        )
    
    async def search_books_by_genre(
        self,
        query: str,
        max_results: int=10,
    ):
        query_str = format_book_genre_search_query(
            query, 
            max_results=max_results
        )
        
        payload = {
            'query': query_str
        }

        resp = await self.client.post('/', json=payload)
        resp.raise_for_status()
        data = resp.json()
        
        results = data['data']['search']['results']['hits']
        return results
        
if __name__ == '__main__':
    from dotenv import load_dotenv, find_dotenv
    import os
    import asyncio
    
    path = find_dotenv()
    load_dotenv(path)
    api_key = os.getenv('HARDCOVER_API_KEY')
    client = HardCoverClient(api_key)

    res = asyncio.run(client.search_books_by_genre('horror, fantasy'))
    for item in res:
        print(item)

