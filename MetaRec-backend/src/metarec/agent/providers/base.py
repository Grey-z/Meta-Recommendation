from hishel import CacheOptions, SpecificationPolicy
from hishel.httpx import AsyncCacheClient
from hishel import AsyncSqliteStorage
from pathlib import Path

async def log_response(resp):
    is_cached = resp.extensions.get('hishel_from_cache', False)
    cached = 'HIT' if is_cached else 'MISS'
    status_code = resp.status_code
    url = resp.url 
    print(f'[{status_code}, CACHE {cached}] {url}')

class BaseAsyncClient:
    def __init__(self, *args, **kwargs):
        #print('init client', args, kwargs)
        database_path = Path('./temp_cache.db').resolve()
        storage = AsyncSqliteStorage(
            database_path=database_path,
        )
        
        event_hooks = {
            'response': [log_response],
        }
        self.client = AsyncCacheClient(
            *args, 
            **kwargs,
            policy=SpecificationPolicy(
                # cache requests for development purposes to reduce API usage
                # TODO: caching for production?
                cache_options=CacheOptions(
                    shared=True,
                    allow_stale=True,
                ),
            ),
            storage=storage,
            event_hooks=event_hooks,
        )
    

