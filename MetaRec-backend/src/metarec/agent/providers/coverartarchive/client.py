from metarec.agent.providers.base import BaseAsyncClient

class CoverArtArchiveClient(BaseAsyncClient):
    """ Client for CoverArtArchive API. """
    def __init__(self):
        headers = {
            'Accept': 'application/json'
        }
        
        #self.client = httpx.AsyncClient(
        super().__init__(
            base_url='https://coverartarchive.org',
            headers=headers,
        )
    
    async def get_cover_art(
        self,
        mbid: str #MusicBrainz ID
    ):
        """
        Fetches the image that is most suitable to be called the "front" cover art of a release.
        see: https://musicbrainz.org/doc/Cover_Art_Archive/API
        """

        resp = await self.client.get(f'/release/{mbid}/front')
        status_code = resp.status_code
        if status_code == 307:
            url = resp.headers.get('Location')
            return url
        else:
            raise Exception(f"Unable to get cover art: [{status_code}]")
