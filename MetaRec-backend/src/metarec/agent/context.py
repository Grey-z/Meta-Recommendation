import os
from metarec.agent.providers.musicbrainz.client import MusicBrainzClient
from metarec.agent.providers.tmdb.client import TMDBClient
from metarec.agent.providers.tikhub.client import TikHubClient
from metarec.agent.providers.discogs.client import DiscogsClient
from metarec.agent.providers.serpapi.client import SerpapiClient
from metarec.agent.providers.hardcover.client import HardCoverClient
from metarec.agent.providers.coverartarchive.client import CoverArtArchiveClient

class ClientContext:
    def __init__(self):
        """ Initializes clients for various APIs. """

        # entertainment/books
        # auth needed
        hardcover_api_key = os.getenv('HARDCOVER_API_KEY')
        self.hardcover = HardCoverClient(api_key=hardcover_api_key)

        # entertainment/music
        # no auth required
        self.musicbrainz = MusicBrainzClient()
        self.coverartarchive = CoverArtArchiveClient()

        # entertainment/music
        # no auth required, but providing auth allows higher rate limit
        discogs_consumer_key = os.getenv('DISCOGS_CONSUMER_KEY')
        discogs_consumer_secret = os.getenv('DISCOGS_CONSUMER_SECRET')
        self.discogs = DiscogsClient(
            consumer_key=discogs_consumer_key,
            consumer_secret=discogs_consumer_secret
        ),

        # entertainment/tv
        # entertainment/movie
        # auth needed
        tmdb_token = os.getenv('TMDB_API_ACCESS_TOKEN')
        self.tmdb = TMDBClient(token=tmdb_token)

        # restaurants
        # shopping
        # auth needed
        serpapi_api_key = os.getenv('SERPAPI_KEY')
        self.serpapi = SerpapiClient(api_key=serpapi_api_key)

        # restaurants
        # auth needed
        tikhub_api_key = os.getenv('TIKHUB_API_KEY')
        self.tikhub = TikHubClient(api_key=tikhub_api_key)

    
if __name__ == '__main__':
    import dotenv
    dotenv.load_dotenv(dotenv.find_dotenv())

    import asyncio
    import tools.entertainment
    import tools.restaurants

    async def test(ctx):
        await tools.entertainment.search_music('tag:rock', ctx)
        await tools.entertainment.search_movies('harry potter', ctx)
        await tools.entertainment.search_tv('harry potter', ctx)
        await tools.entertainment.search_books('horror', ctx)
        await tools.restaurants.search_restaurants_google('cantonese food', ctx)
        await tools.restaurants.search_restaurants_yelp('sichuan food', 'Singapore, Chinatown', ctx)

    ctx = ClientContext()
    asyncio.run(test(ctx))
