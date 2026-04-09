from metarec.agent.providers.base import BaseAsyncClient
from typing import Optional

class TMDBClient(BaseAsyncClient):
    """ Client for TMDB API. """
    def __init__(
        self,
        token: Optional[str]=None,
        language: str='en',
    ):
        headers = {
            'Authorization': f'Bearer {token}',
            'accept': 'application/json',
        }
        super().__init__(
            base_url='https://api.themoviedb.org',
            headers=headers,
        )
        
        self.language = 'en'
    
    async def get_configuration(self):
        resp = await self.client.get('/3/configuration')
        resp.raise_for_status()
        data = resp.json()
        return data

    async def get_languages(self):
        resp = await self.client.get('/3/configuration/languages')
        resp.raise_for_status()
        data = resp.json()
        return data
    
    async def list_movie_genres(self):
        """ Retrieve id-genre name mappings for movies listed on TMDB. """
        params = {
            'language': self.language,
        }
        resp = await self.client.get('/3/genre/movie/list', params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get('genres', [])

    async def list_tv_genres(self):
        """ Retrieve id-genre name mappings for tv series listed on TMDB. """
        params = {
            'language': self.language,
        }
        resp = await self.client.get('/3/genre/tv/list', params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get('genres', [])
    
    async def search_movie_by_title(
        self,
        query: str,
    ):
        params = {
            'query': query,
        }
        resp = await self.client.get('/3/search/movie', params=params)
        resp.raise_for_status()
        data = resp.json()
        
        results = data['results']
        return results

    async def search_movie_by_filter(
        self,
        with_cast: Optional[str]=None,
        without_cast: Optional[str]=None,
        with_genres: Optional[str]=None,
        without_genres: Optional[str]=None,
    ):
        params = {}
        
        if with_cast is not None:
            params['with_cast'] = with_cast
        if without_cast is not None:
            params['without_cast'] = without_cast

        if with_genres is not None:
            params['with_genres'] = with_genres
        if without_genres is not None:
            params['without_genres'] = without_genres

        resp = await self.client.get('/3/discover/movie', params=params)
        resp.raise_for_status()
        data = resp.json()
        
        return data.get('results', [])

    async def search_tv_by_filter(
        self,
        with_cast: Optional[str]=None,
        without_cast: Optional[str]=None,
        with_genres: Optional[str]=None,
        without_genres: Optional[str]=None,
    ):
        params = {}
        
        if with_cast is not None:
            params['with_cast'] = with_cast
        if without_cast is not None:
            params['without_cast'] = without_cast

        if with_genres is not None:
            params['with_genres'] = with_genres
        if without_genres is not None:
            params['without_genres'] = without_genres

        resp = await self.client.get('/3/discover/tv', params=params)
        resp.raise_for_status()
        data = resp.json()
        
        return data.get('results', [])

    async def search_tv_by_title(
        self,
        query: str,
    ):
        params = {
            'query': query,
        }
        resp = await self.client.get('/3/search/tv', params=params)
        resp.raise_for_status()
        data = resp.json()

        results = data['results']
        return results

    def map_genre_ids_to_names(
        self,
        genre_ids,
        genre_list,
    ):
        """
        Utility function to map genre id list to genre name list
        e.g. genre_id 99 = Documentary
        """
        mappings = dict()
        for entry in genre_list:
            key = entry.get('id')
            val = entry.get('name')
            mappings[key] = val
        
        genres = []
        for id in genre_ids:
            genre = mappings.get(id)
            if genre is not None:
                genres.append(genre)
        
        return genres
            
    def map_language_code_to_name(
        self,
        language_code,
        language_list,
    ):
        """
        Utility function to map language iso_639_1 to english name
        """
        mappings = dict()
        for entry in language_list:
            key = entry.get('iso_639_1')
            val = entry.get('english_name')
            mappings[key] = val
        
        language = mappings.get(language_code, None)
        return language
            
